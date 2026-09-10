"""Independent event-aware gripper head that leaves OpenPI arm actions untouched."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from consumers.openpi_franka_joint8.phase_sampling import (
    DEFAULT_PHASE_PROBABILITIES,
    CountingWeightedSampler,
    assign_phases,
)


def _image_tensor(value: Any, *, size: tuple[int, int] = (96, 128)) -> torch.Tensor:
    tensor = torch.as_tensor(np.asarray(value), dtype=torch.float32)
    if tensor.ndim != 3:
        raise ValueError(f"image must be rank three, got {tuple(tensor.shape)}")
    if tensor.shape[-1] == 3:
        tensor = tensor.permute(2, 0, 1)
    if tensor.shape[0] != 3:
        raise ValueError(f"image must have three channels, got {tuple(tensor.shape)}")
    if float(tensor.max()) > 1.5:
        tensor = tensor / 255.0
    return F.interpolate(tensor[None], size=size, mode="bilinear", align_corners=False)[0]


class GripperEventHead(torch.nn.Module):
    def __init__(
        self,
        *,
        action_horizon: int = 10,
        state_mean: np.ndarray | torch.Tensor | None = None,
        state_std: np.ndarray | torch.Tensor | None = None,
    ) -> None:
        super().__init__()
        if action_horizon < 1:
            raise ValueError("action_horizon must be positive")
        self.action_horizon = int(action_horizon)
        self.encoder = torch.nn.Sequential(
            torch.nn.Conv2d(3, 16, kernel_size=5, stride=2, padding=2),
            torch.nn.SiLU(),
            torch.nn.Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
            torch.nn.SiLU(),
            torch.nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            torch.nn.SiLU(),
            torch.nn.AdaptiveAvgPool2d((2, 2)),
        )
        self.classifier = torch.nn.Sequential(
            torch.nn.Linear(64 * 2 * 2 * 2 + 8, 128),
            torch.nn.SiLU(),
            torch.nn.Linear(128, self.action_horizon),
        )
        mean = torch.zeros(8) if state_mean is None else torch.as_tensor(state_mean).float()
        std = torch.ones(8) if state_std is None else torch.as_tensor(state_std).float()
        if mean.shape != (8,) or std.shape != (8,) or torch.any(std <= 0):
            raise ValueError("state normalization must contain positive 8-D mean/std")
        self.register_buffer("state_mean", mean)
        self.register_buffer("state_std", std)

    def forward(
        self, state: torch.Tensor, base_image: torch.Tensor, wrist_image: torch.Tensor
    ) -> torch.Tensor:
        if state.ndim != 2 or state.shape[1] != 8:
            raise ValueError(f"state must have shape (B, 8), got {tuple(state.shape)}")
        base_features = self.encoder(base_image).flatten(1)
        wrist_features = self.encoder(wrist_image).flatten(1)
        normalized_state = (state - self.state_mean) / self.state_std
        return self.classifier(torch.cat((base_features, wrist_features, normalized_state), dim=1))


class _HeadDataset(torch.utils.data.Dataset):
    def __init__(self, dataset) -> None:
        self.dataset = dataset

    def __len__(self) -> int:
        return len(self.dataset)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        sample = self.dataset[index]
        return {
            "state": torch.as_tensor(np.asarray(sample["observation.state"]), dtype=torch.float32),
            "base": _image_tensor(sample["observation.images.base"]),
            "wrist": _image_tensor(sample["observation.images.wrist"]),
            "target": torch.as_tensor(np.asarray(sample["action"])[:, 7], dtype=torch.float32),
            "valid": ~torch.as_tensor(np.asarray(sample["action_is_pad"]), dtype=torch.bool),
        }


def load_gripper_head(path: str | Path, *, device: str | torch.device = "cpu") -> GripperEventHead:
    payload = torch.load(Path(path).expanduser().resolve(), map_location=device, weights_only=True)
    model = GripperEventHead(
        action_horizon=int(payload["action_horizon"]),
        state_mean=np.asarray(payload["state_mean"], dtype=np.float32),
        state_std=np.asarray(payload["state_std"], dtype=np.float32),
    )
    model.load_state_dict(payload["state_dict"])
    return model.to(device).eval()


def predict_gripper_chunk(
    model: GripperEventHead,
    observation: dict[str, Any],
    *,
    device: str | torch.device,
) -> np.ndarray:
    with torch.inference_mode():
        logits = model(
            torch.as_tensor(np.asarray(observation["observation/state"]), dtype=torch.float32, device=device)[None],
            _image_tensor(observation["observation/image"]).to(device)[None],
            _image_tensor(observation["observation/wrist_image"]).to(device)[None],
        )
    return torch.sigmoid(logits[0]).cpu().numpy().astype(np.float32)


class GripperOverridePolicy:
    """Use a frozen base policy for joints and override only its gripper column."""

    def __init__(self, base_policy, head: GripperEventHead, *, device: str) -> None:
        self.base_policy = base_policy
        self.head = head
        self.device = device
        self._metadata = dict(base_policy.metadata)
        self._metadata.update(
            gripper_policy="independent_binary_event_head",
            gripper_head_horizon=head.action_horizon,
            arm_action_source="unchanged_base_policy",
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    def infer(self, obs: dict, *, noise: np.ndarray | None = None) -> dict:
        result = self.base_policy.infer(obs, noise=noise)
        actions = np.asarray(result["actions"], dtype=np.float32).copy()
        probabilities = predict_gripper_chunk(self.head, obs, device=self.device)
        if actions.shape[0] != len(probabilities):
            raise ValueError(
                f"base/head horizons differ: {actions.shape[0]} versus {len(probabilities)}"
            )
        unchanged_joints = actions[:, :7].copy()
        actions[:, 7] = probabilities
        if not np.array_equal(actions[:, :7], unchanged_joints):
            raise AssertionError("gripper override changed an arm action")
        result["actions"] = actions
        result["gripper_head_probabilities"] = probabilities
        return result


def train_head(args: argparse.Namespace) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    metadata = LeRobotDatasetMetadata(args.dataset_root.name, root=args.dataset_root)
    dataset = LeRobotDataset(
        args.dataset_root.name,
        root=args.dataset_root,
        delta_timestamps={"action": [step / metadata.fps for step in range(args.action_horizon)]},
        video_backend="pyav",
    )
    table = dataset.hf_dataset
    states = np.stack([np.asarray(value, dtype=np.float32) for value in table["observation.state"]])
    state_mean = states.mean(axis=0)
    state_std = np.maximum(states.std(axis=0), 1e-6)
    episodes = np.asarray(table["episode_index"], dtype=np.int64)
    frames = np.asarray(table["frame_index"], dtype=np.int64)
    actions = np.stack([np.asarray(value, dtype=np.float32) for value in table["action"]])
    phases = assign_phases(episodes, frames, actions[:, 7])
    sampler = CountingWeightedSampler(phases, DEFAULT_PHASE_PROBABILITIES, seed=args.seed)
    loader = torch.utils.data.DataLoader(
        _HeadDataset(dataset),
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=args.num_workers,
        pin_memory=args.device.startswith("cuda"),
        drop_last=True,
    )
    model = GripperEventHead(
        action_horizon=args.action_horizon, state_mean=state_mean, state_std=state_std
    ).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    iterator = iter(loader)
    metrics: list[dict[str, float | int]] = []
    model.train()
    for step in range(args.train_steps):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        state = batch["state"].to(args.device, non_blocking=True)
        base = batch["base"].to(args.device, non_blocking=True)
        wrist = batch["wrist"].to(args.device, non_blocking=True)
        target = batch["target"].to(args.device, non_blocking=True)
        valid = batch["valid"].to(args.device, non_blocking=True)
        logits = model(state, base, wrist)
        loss_values = F.binary_cross_entropy_with_logits(logits, target, reduction="none")
        loss = loss_values[valid].mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        if step == 0 or (step + 1) % args.log_interval == 0 or step + 1 == args.train_steps:
            with torch.no_grad():
                accuracy = ((logits >= 0) == (target >= 0.5))[valid].float().mean()
            item = {"step": step, "loss": float(loss), "accuracy": float(accuracy)}
            metrics.append(item)
            print(json.dumps(item), flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "format": "franka_gripper_event_head_v1",
            "action_horizon": args.action_horizon,
            "state_mean": state_mean.tolist(),
            "state_std": state_std.tolist(),
            "state_dict": model.state_dict(),
        },
        args.output,
    )
    return {
        "stage": "m5c_gripper_head_train",
        "status": "completed",
        "dataset_root": str(args.dataset_root),
        "output": str(args.output),
        "episodes": int(metadata.total_episodes),
        "frames": len(dataset),
        "action_horizon": args.action_horizon,
        "train_steps": args.train_steps,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "sampling": sampler.report(),
        "metrics": metrics,
        "review_status": "SELF_REVIEWED_PROVISIONAL",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--action-horizon", type=int, default=10)
    parser.add_argument("--train-steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--log-interval", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    for name in ("dataset_root", "output", "report"):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if min(args.action_horizon, args.train_steps, args.batch_size, args.log_interval) < 1:
        parser.error("horizon, steps, batch size, and log interval must be positive")
    return args


def main() -> None:
    args = parse_args()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        report = train_head(args)
    except Exception as error:
        report = {"stage": "m5c_gripper_head_train", "status": "failed", "error": f"{type(error).__name__}: {error}"}
        raise
    finally:
        report.update(started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": report.get("output")}, indent=2))


if __name__ == "__main__":
    main()
