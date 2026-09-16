from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
from torch.utils.data import DataLoader

from .dataset import (
    ACTION_DIM,
    OBSERVATION_DIM,
    StateActionChunkDataset,
    fit_observation_normalizer,
    load_accepted_pickcube_episodes,
)
from .evaluate_maniskill import (
    _make_env,
    _scalar_bool,
    _scalar_int,
    _to_numpy,
    classify_failure,
    observation_vector,
)
from .model import StateActionChunkMLP
from .train import _git_state, _masked_loss, _package_versions


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SATURATION_EPSILON = 1e-6


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def action_error_metrics(
    prediction: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
    *,
    saturation_epsilon: float = SATURATION_EPSILON,
) -> dict[str, float | int]:
    """Split teacher-forced action error by target saturation."""
    valid = mask.to(dtype=torch.bool).unsqueeze(-1).expand_as(target)
    saturated = valid & (target.abs() >= 1.0 - saturation_epsilon)
    non_saturated = valid & ~saturated
    squared_error = torch.square(prediction - target)

    def selected_mse(selection: torch.Tensor) -> float:
        count = int(selection.sum().detach().cpu())
        if count == 0:
            raise ValueError("action error metric selection is empty")
        return float(squared_error[selection].mean().detach().cpu())

    valid_count = int(valid.sum().detach().cpu())
    saturated_count = int(saturated.sum().detach().cpu())
    non_saturated_count = int(non_saturated.sum().detach().cpu())
    return {
        "overall_mse": selected_mse(valid),
        "saturated_mse": selected_mse(saturated),
        "non_saturated_mse": selected_mse(non_saturated),
        "valid_element_count": valid_count,
        "saturated_element_count": saturated_count,
        "non_saturated_element_count": non_saturated_count,
        "saturated_fraction": saturated_count / valid_count,
        "saturation_epsilon": saturation_epsilon,
    }


def diagnostic_gate_passed(
    metrics: dict[str, float | int],
    *,
    target_mse: float,
    successes: int,
    rollouts: int,
) -> bool:
    return bool(
        float(metrics["non_saturated_mse"]) <= target_mse
        and successes == rollouts
    )


def _rollout(
    model: StateActionChunkMLP,
    normalizer,
    *,
    model_device: torch.device,
    sim_backend: str,
    seed: int,
    initial_state_arrays: dict[str, dict[str, np.ndarray]],
    expert_actions: np.ndarray,
) -> dict[str, Any]:
    env = _make_env(sim_backend)
    try:
        unwrapped = env.unwrapped
        env_device = torch.device(unwrapped.device)
        state = {
            section: {
                name: torch.as_tensor(value, device=env_device).reshape(1, -1)
                for name, value in names.items()
            }
            for section, names in initial_state_arrays.items()
        }
        _, info = env.reset(seed=seed)
        unwrapped.set_state_dict(state)
        unwrapped.goal_pos = state["actors"]["goal_site"][:, :3]
        observation = unwrapped.get_obs(info=info)
        success = False
        ever_grasped = _scalar_bool(info["is_grasped"])
        ever_placed = _scalar_bool(info["is_obj_placed"])
        minimum_distance = float("inf")
        details: list[dict[str, Any]] = []
        for step in range(min(50, len(expert_actions))):
            vector = normalizer.transform_numpy(observation_vector(observation))
            tensor = torch.as_tensor(vector, device=model_device).unsqueeze(0)
            with torch.no_grad():
                action = model(tensor)[0, 0].detach().cpu().numpy()
            observation, _, terminated, truncated, info = env.step(action)
            object_position = _to_numpy(observation["extra"]["obj_pose"]).reshape(-1)[:3]
            goal_position = _to_numpy(observation["extra"]["goal_pos"]).reshape(-1)
            minimum_distance = min(
                minimum_distance,
                float(np.linalg.norm(object_position - goal_position)),
            )
            grasped = _scalar_bool(info["is_grasped"])
            placed = _scalar_bool(info["is_obj_placed"])
            static = _scalar_bool(info["is_robot_static"])
            success = success or _scalar_bool(info["success"])
            ever_grasped = ever_grasped or grasped
            ever_placed = ever_placed or placed
            details.append(
                {
                    "step": step,
                    "model_action": action.tolist(),
                    "expert_action": expert_actions[step].tolist(),
                    "action_l2_vs_expert_t": float(
                        np.linalg.norm(action - expert_actions[step])
                    ),
                    "grasped": grasped,
                    "placed": placed,
                    "static": static,
                }
            )
            if success or _scalar_bool(terminated) or _scalar_bool(truncated):
                break
        final_placed = _scalar_bool(info["is_obj_placed"])
        final_static = _scalar_bool(info["is_robot_static"])
        return {
            "success": success,
            "steps": _scalar_int(info["elapsed_steps"]),
            "failure_reason": classify_failure(
                success=success,
                ever_grasped=ever_grasped,
                ever_placed=ever_placed,
                final_placed=final_placed,
                final_static=final_static,
            ),
            "ever_grasped": ever_grasped,
            "ever_placed": ever_placed,
            "final_placed": final_placed,
            "final_static": final_static,
            "minimum_goal_distance_m": minimum_distance,
            "action_trace": details,
        }
    finally:
        env.close()


def run(args: argparse.Namespace) -> Path:
    output_dir = args.output_root / args.run_name
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"diagnostic output already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.training_seed)
    np.random.seed(args.training_seed)
    torch.manual_seed(args.training_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.training_seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    if args.device == "auto":
        model_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        model_device = torch.device(args.device)

    records = load_accepted_pickcube_episodes(
        args.db, args.dataset_name, expected_count=1
    )
    record = records[0]
    dataset = StateActionChunkDataset(records, action_horizon=args.action_horizon)
    normalizer = fit_observation_normalizer(dataset)
    normalizer.save(output_dir / "normalizer.npz")
    loader = DataLoader(dataset, batch_size=len(dataset), shuffle=False, num_workers=0)
    batch = next(iter(loader))
    observation = batch["observation"].to(model_device)
    action = batch["action"].to(model_device)
    mask = batch["action_mask"].to(model_device)
    mean = torch.as_tensor(normalizer.mean, device=model_device)
    std = torch.as_tensor(normalizer.std, device=model_device)
    normalized_observation = (observation - mean) / std

    model = StateActionChunkMLP(
        observation_dim=OBSERVATION_DIM,
        action_dim=ACTION_DIM,
        action_horizon=args.action_horizon,
        hidden_dim=args.hidden_dim,
        hidden_layers=args.hidden_layers,
    ).to(model_device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=0.0
    )
    started_at = _utc_now()
    loss_value = float("inf")
    steps_completed = 0
    for step in range(args.max_train_steps):
        prediction = model(normalized_observation)
        loss = _masked_loss(prediction, action, mask)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        loss_value = float(loss.detach().cpu())
        steps_completed = step + 1
        if loss_value <= args.target_mse:
            break
    model.eval()
    with torch.no_grad():
        prediction = model(normalized_observation)
        error_metrics = action_error_metrics(prediction, action, mask)
        first_action_l2 = float(
            torch.linalg.vector_norm(prediction[0, 0] - action[0, 0]).detach().cpu()
        )

    native_payload = record.path / "native_trajectory.npz"
    with np.load(native_payload, allow_pickle=False) as payload:
        expert_actions = np.clip(
            np.asarray(payload["normalized_action"], dtype=np.float32), -1.0, 1.0
        )
    with h5py.File(args.demo_h5, "r") as demos:
        if record.source_demo_trajectory not in demos:
            raise ValueError(
                f"official demo is missing {record.source_demo_trajectory}"
            )
        group = demos[record.source_demo_trajectory]
        source_actions = np.clip(
            np.asarray(group["actions"], dtype=np.float32)[: len(expert_actions)],
            -1.0,
            1.0,
        )
        if not np.array_equal(source_actions, expert_actions):
            raise ValueError("native payload actions disagree with the checksummed source demo")
        initial_state_arrays = {
            section: {
                name: np.asarray(dataset[0], dtype=np.float32)
                for name, dataset in group["env_states"][section].items()
            }
            for section in ("actors", "articulations")
        }

    rollouts = [
        _rollout(
            model,
            normalizer,
            model_device=model_device,
            sim_backend=args.sim_backend,
            seed=record.seed,
            initial_state_arrays=initial_state_arrays,
            expert_actions=expert_actions,
        )
        for _ in range(args.rollouts)
    ]
    successes = sum(bool(result["success"]) for result in rollouts)
    gate_passed = diagnostic_gate_passed(
        error_metrics,
        target_mse=args.target_mse,
        successes=successes,
        rollouts=args.rollouts,
    )
    git_state = _git_state()
    checkpoint = {
        "format": "robot_data_studio_roboverse_state_bc_overfit_v1",
        "model": model.configuration(),
        "model_state_dict": model.state_dict(),
        "episode_uuid": record.episode_uuid,
        "episode_seed": record.seed,
        "source_demo_trajectory": record.source_demo_trajectory,
        "git": git_state,
        "dependencies": _package_versions(),
    }
    torch.save(checkpoint, output_dir / "checkpoint.pt")
    config = {
        "dataset_name": args.dataset_name,
        "episode_uuid": record.episode_uuid,
        "episode_seed": record.seed,
        "source_demo_trajectory": record.source_demo_trajectory,
        "action_horizon": args.action_horizon,
        "hidden_dim": args.hidden_dim,
        "hidden_layers": args.hidden_layers,
        "learning_rate": args.learning_rate,
        "max_train_steps": args.max_train_steps,
        "non_saturated_target_mse": args.target_mse,
        "rollouts": args.rollouts,
        "sim_backend": args.sim_backend,
        "device": str(model_device),
    }
    (output_dir / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "status": "completed",
        "evidence_label": (
            "single_episode_overfit_gate_passed"
            if gate_passed
            else "single_episode_overfit_gate_failed"
        ),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "git": git_state,
        "dependencies": _package_versions(),
        "config": config,
        "dataloader_batch": {key: list(value.shape) for key, value in batch.items()},
        "training": {
            "steps_completed": steps_completed,
            "final_online_loss": loss_value,
            "teacher_forced_action_error": error_metrics,
            "first_action_l2": first_action_l2,
        },
        "closed_loop": {
            "initial_state_restored": True,
            "action_replay": False,
            "successes": successes,
            "rollouts": args.rollouts,
            "results": rollouts,
        },
        "gate": {
            "non_saturated_mse_at_most": args.target_mse,
            "required_successes": args.rollouts,
            "passed": gate_passed,
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "evidence_label": report["evidence_label"],
                "teacher_forced_action_error": error_metrics,
                "first_action_l2": first_action_l2,
                "closed_loop_successes": successes,
                "rollouts": args.rollouts,
                "output": str(output_dir.resolve()),
            },
            indent=2,
        )
    )
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    demo_root = PROJECT_ROOT / "data/cache/maniskill/PickCube-v1/rl"
    parser = argparse.ArgumentParser(
        description="Overfit one accepted pre-action PickCube Episode and replay it closed loop"
    )
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data/studio.db")
    parser.add_argument("--dataset-name", default="roboverse_p2b1_pickcube_overfit")
    parser.add_argument("--action-horizon", type=int, default=8)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--hidden-layers", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--max-train-steps", type=int, default=5000)
    parser.add_argument(
        "--non-saturated-target-mse",
        "--target-mse",
        dest="target_mse",
        type=float,
        default=1e-6,
        help="maximum teacher-forced MSE on target actions below saturation",
    )
    parser.add_argument("--training-seed", type=int, default=20260916)
    parser.add_argument("--rollouts", type=int, default=3)
    parser.add_argument("--sim-backend", choices=("physx_cuda", "physx_cpu"), default="physx_cuda")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--demo-h5",
        type=Path,
        default=demo_root / "trajectory.none.pd_joint_delta_pos.physx_cuda.h5",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/training/roboverse_state_bc",
    )
    parser.add_argument("--run-name", default="pickcube_single_episode_overfit_v1")
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
