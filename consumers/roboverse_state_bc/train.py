from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import random
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from .dataset import (
    ACTION_DIM,
    OBSERVATION_DIM,
    EpisodeRecord,
    StateActionChunkDataset,
    fit_observation_normalizer,
    load_accepted_pickcube_episodes,
    split_episodes,
)
from .model import StateActionChunkMLP


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TrainingConfig:
    dataset_name: str
    episode_count: int
    train_episodes: int
    validation_episodes: int
    split_seed: int
    training_seed: int
    action_horizon: int
    hidden_dim: int
    hidden_layers: int
    batch_size: int
    epochs: int
    learning_rate: float
    weight_decay: float
    patience: int
    device: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_state() -> dict[str, object]:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
    )
    diff = subprocess.check_output(["git", "diff", "--binary"], cwd=PROJECT_ROOT)
    source_digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source_digest.update(path.name.encode("utf-8"))
        source_digest.update(path.read_bytes())
    return {
        "revision": revision,
        "dirty": bool(status.strip()),
        "diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
        "consumer_source_sha256": source_digest.hexdigest(),
    }


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("torch", "numpy", "gymnasium", "mani-skill", "h5py"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _records_payload(records: list[EpisodeRecord]) -> list[dict[str, object]]:
    return [record.as_dict() for record in records]


def _masked_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    per_step = torch.square(prediction - target).mean(dim=-1)
    return (per_step * mask).sum() / mask.sum().clamp_min(1.0)


def _run_epoch(
    model: StateActionChunkMLP,
    loader: DataLoader,
    normalizer_mean: torch.Tensor,
    normalizer_std: torch.Tensor,
    *,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None,
) -> float:
    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    total_weight = 0
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for batch in loader:
            observation = batch["observation"].to(device)
            action = batch["action"].to(device)
            mask = batch["action_mask"].to(device)
            observation = (observation - normalizer_mean) / normalizer_std
            prediction = model(observation)
            loss = _masked_loss(prediction, action, mask)
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            batch_size = int(observation.shape[0])
            total_loss += float(loss.detach().cpu()) * batch_size
            total_weight += batch_size
    return total_loss / max(total_weight, 1)


def train(args: argparse.Namespace) -> Path:
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    random.seed(args.training_seed)
    np.random.seed(args.training_seed)
    torch.manual_seed(args.training_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.training_seed)
    torch.use_deterministic_algorithms(True, warn_only=True)

    output_dir = args.output_root / args.run_name
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"training output already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_accepted_pickcube_episodes(
        args.db,
        args.dataset_name,
        expected_count=args.episode_count,
    )
    train_records, validation_records = split_episodes(
        records,
        train_count=args.train_episodes,
        validation_count=args.validation_episodes,
        split_seed=args.split_seed,
    )
    train_dataset = StateActionChunkDataset(
        train_records, action_horizon=args.action_horizon
    )
    validation_dataset = StateActionChunkDataset(
        validation_records, action_horizon=args.action_horizon
    )
    normalizer = fit_observation_normalizer(train_dataset)
    normalizer.save(output_dir / "normalizer.npz")

    generator = torch.Generator().manual_seed(args.training_seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )
    first_batch = next(iter(train_loader))

    model = StateActionChunkMLP(
        observation_dim=OBSERVATION_DIM,
        action_dim=ACTION_DIM,
        action_horizon=args.action_horizon,
        hidden_dim=args.hidden_dim,
        hidden_layers=args.hidden_layers,
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    mean = torch.as_tensor(normalizer.mean, dtype=torch.float32, device=device)
    std = torch.as_tensor(normalizer.std, dtype=torch.float32, device=device)

    config = TrainingConfig(
        dataset_name=args.dataset_name,
        episode_count=args.episode_count,
        train_episodes=args.train_episodes,
        validation_episodes=args.validation_episodes,
        split_seed=args.split_seed,
        training_seed=args.training_seed,
        action_horizon=args.action_horizon,
        hidden_dim=args.hidden_dim,
        hidden_layers=args.hidden_layers,
        batch_size=args.batch_size,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        patience=args.patience,
        device=str(device),
    )
    git_state = _git_state()
    split_payload = {
        "split_seed": args.split_seed,
        "train": _records_payload(train_records),
        "validation": _records_payload(validation_records),
    }
    (output_dir / "config.json").write_text(
        json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "split.json").write_text(
        json.dumps(split_payload, indent=2) + "\n", encoding="utf-8"
    )

    history: list[dict[str, float | int]] = []
    best_validation_loss = float("inf")
    best_epoch = -1
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0
    started_at = _utc_now()
    for epoch in range(args.epochs):
        train_loss = _run_epoch(
            model,
            train_loader,
            mean,
            std,
            device=device,
            optimizer=optimizer,
        )
        validation_loss = _run_epoch(
            model,
            validation_loader,
            mean,
            std,
            device=device,
            optimizer=None,
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= args.patience:
            break
    if best_state is None:
        raise RuntimeError("training did not produce a checkpoint")

    checkpoint = {
        "format": "robot_data_studio_roboverse_state_bc_v1",
        "model": model.configuration(),
        "model_state_dict": best_state,
        "training_config": asdict(config),
        "best_epoch": best_epoch,
        "best_validation_loss": best_validation_loss,
        "train_episode_uuids": [record.episode_uuid for record in train_records],
        "validation_episode_uuids": [
            record.episode_uuid for record in validation_records
        ],
        "train_seeds": [record.seed for record in train_records],
        "validation_seeds": [record.seed for record in validation_records],
        "git": git_state,
        "dependencies": _package_versions(),
    }
    torch.save(checkpoint, output_dir / "checkpoint.pt")
    report = {
        "status": "completed",
        "started_at": started_at,
        "finished_at": _utc_now(),
        "output_dir": str(output_dir.resolve()),
        "device": str(device),
        "git": git_state,
        "dependencies": _package_versions(),
        "dataset": {
            "name": args.dataset_name,
            "episodes": len(records),
            "train_episodes": len(train_records),
            "validation_episodes": len(validation_records),
            "train_frames": len(train_dataset),
            "validation_frames": len(validation_dataset),
            "action_statistics": train_dataset.action_statistics(),
        },
        "dataloader_batch": {
            key: list(value.shape) for key, value in first_batch.items()
        },
        "model": model.configuration(),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "best_epoch": best_epoch,
        "best_validation_loss": best_validation_loss,
        "epochs_completed": len(history),
        "history": history,
    }
    (output_dir / "train_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in ("status", "output_dir", "best_epoch", "best_validation_loss")}, indent=2))
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a small state action-chunk BC policy for native ManiSkill PickCube"
    )
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data/studio.db")
    parser.add_argument("--dataset-name", default="roboverse_p2_20260916")
    parser.add_argument("--episode-count", type=int, default=20)
    parser.add_argument("--train-episodes", type=int, default=15)
    parser.add_argument("--validation-episodes", type=int, default=5)
    parser.add_argument("--split-seed", type=int, default=20260916)
    parser.add_argument("--training-seed", type=int, default=20260916)
    parser.add_argument("--action-horizon", type=int, default=8)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--hidden-layers", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--patience", type=int, default=50)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/training/roboverse_state_bc",
    )
    parser.add_argument("--run-name", default="pickcube_bc_v1")
    return parser


def main() -> None:
    train(build_parser().parse_args())


if __name__ == "__main__":
    main()
