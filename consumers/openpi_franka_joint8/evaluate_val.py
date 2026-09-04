"""Evaluate a trained Franka joint8 checkpoint across phase-labelled validation frames."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from consumers.openpi_franka_joint8.config import ACTION_DIM, ACTION_HORIZON, make_train_config


PHASES = (
    "approach_open",
    "close_transition",
    "closed_transport",
    "release_transition",
    "post_release",
)


def assign_phases(
    episode_indices: np.ndarray,
    frame_indices: np.ndarray,
    gripper_targets: np.ndarray,
    *,
    transition_radius: int = 2,
) -> np.ndarray:
    """Label frames from each demonstration's first close and subsequent release."""
    phases = np.empty(len(gripper_targets), dtype=object)
    for episode in np.unique(episode_indices):
        rows = np.flatnonzero(episode_indices == episode)
        order = rows[np.argsort(frame_indices[rows])]
        closed = gripper_targets[order] >= 0.5
        close_candidates = np.flatnonzero(closed)
        if not len(close_candidates):
            raise ValueError(f"episode {int(episode)} has no close event")
        close_at = int(close_candidates[0])
        release_candidates = np.flatnonzero((~closed) & (np.arange(len(order)) > close_at))
        if not len(release_candidates):
            raise ValueError(f"episode {int(episode)} has no release after close")
        release_at = int(release_candidates[0])
        for local_index, row in enumerate(order):
            if abs(local_index - close_at) <= transition_radius:
                phase = "close_transition"
            elif abs(local_index - release_at) <= transition_radius:
                phase = "release_transition"
            elif local_index < close_at:
                phase = "approach_open"
            elif local_index < release_at:
                phase = "closed_transport"
            else:
                phase = "post_release"
            phases[row] = phase
    return phases


def summarize_errors(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"frames": 0}
    joint_first = np.stack([record["joint_first_abs_error"] for record in records])
    gripper_target = np.asarray([record["gripper_target"] for record in records])
    gripper_prediction = np.asarray([record["gripper_prediction"] for record in records])
    target_closed = gripper_target >= 0.5
    predicted_closed = gripper_prediction >= 0.5
    chunk_joint_error = np.concatenate([record["chunk_joint_abs_error"] for record in records])
    chunk_gripper_error = np.concatenate([record["chunk_gripper_abs_error"] for record in records])
    return {
        "frames": len(records),
        "joint_first_step_mae_rad": float(joint_first.mean()),
        "joint_first_step_mae_per_joint_rad": joint_first.mean(axis=0).astype(float).tolist(),
        "joint_chunk_mae_rad": float(chunk_joint_error.mean()),
        "gripper_first_step_mae": float(np.mean(np.abs(gripper_prediction - gripper_target))),
        "gripper_chunk_mae": float(chunk_gripper_error.mean()),
        "gripper_accuracy": float(np.mean(predicted_closed == target_closed)),
        "target_close_rate": float(np.mean(target_closed)),
        "predicted_close_rate": float(np.mean(predicted_closed)),
        "predicted_gripper_min": float(gripper_prediction.min()),
        "predicted_gripper_max": float(gripper_prediction.max()),
        "close_recall": (
            float(np.mean(predicted_closed[target_closed])) if np.any(target_closed) else None
        ),
        "open_specificity": (
            float(np.mean(~predicted_closed[~target_closed])) if np.any(~target_closed) else None
        ),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from openpi.policies import policy_config

    metadata = LeRobotDatasetMetadata(args.dataset_root.name, root=args.dataset_root)
    dataset = LeRobotDataset(
        args.dataset_root.name,
        root=args.dataset_root,
        delta_timestamps={"action": [step / metadata.fps for step in range(ACTION_HORIZON)]},
        video_backend="pyav",
    )
    actions = np.stack([np.asarray(value) for value in dataset.hf_dataset["action"]])
    episode_indices = np.asarray([int(value) for value in dataset.hf_dataset["episode_index"]])
    frame_indices = np.asarray([int(value) for value in dataset.hf_dataset["frame_index"]])
    phases = assign_phases(episode_indices, frame_indices, actions[:, 7])

    config = make_train_config(
        dataset_root=args.dataset_root,
        training_root=args.training_root,
        base_checkpoint=args.base_checkpoint,
        experiment_name=args.experiment_name,
        num_train_steps=args.num_train_steps,
    )
    policy = policy_config.create_trained_policy(
        config,
        args.checkpoint,
        sample_kwargs={"num_steps": args.inference_steps},
    )

    records: list[dict[str, Any]] = []
    by_phase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    event_windows: list[dict[str, Any]] = []
    inference_ms: list[float] = []
    for index in range(len(dataset)):
        sample = dataset[index]
        noise = np.random.default_rng(args.seed + index).standard_normal(
            (config.model.action_horizon, config.model.action_dim), dtype=np.float32
        )
        output = policy.infer(
            {
                "observation/image": sample["observation.images.base"],
                "observation/wrist_image": sample["observation.images.wrist"],
                "observation/state": np.asarray(sample["observation.state"], dtype=np.float32),
                "prompt": sample["task"],
            },
            noise=noise,
        )
        predicted = np.asarray(output["actions"], dtype=np.float32)
        target = np.asarray(sample["action"], dtype=np.float32)
        valid = ~np.asarray(sample["action_is_pad"], dtype=bool)
        if predicted.shape != (ACTION_HORIZON, ACTION_DIM) or not np.isfinite(predicted).all():
            raise ValueError(f"invalid prediction at dataset index {index}: {predicted.shape}")
        record = {
            "joint_first_abs_error": np.abs(predicted[0, :7] - target[0, :7]),
            "gripper_target": float(target[0, 7]),
            "gripper_prediction": float(predicted[0, 7]),
            "chunk_joint_abs_error": np.abs(predicted[valid, :7] - target[valid, :7]).reshape(-1),
            "chunk_gripper_abs_error": np.abs(predicted[valid, 7] - target[valid, 7]).reshape(-1),
        }
        records.append(record)
        phase = str(phases[index])
        by_phase[phase].append(record)
        inference_ms.append(float(output["policy_timing"]["infer_ms"]))
        if phase in {"close_transition", "release_transition"}:
            event_windows.append(
                {
                    "episode_index": int(episode_indices[index]),
                    "frame_index": int(frame_indices[index]),
                    "phase": phase,
                    "target_gripper": float(target[0, 7]),
                    "predicted_gripper": float(predicted[0, 7]),
                }
            )

    overall = summarize_errors(records)
    quality_gate = {
        "joint_first_step_mae_at_most_0_1_rad": overall["joint_first_step_mae_rad"] <= 0.1,
        "close_recall_at_least_0_8": (overall["close_recall"] or 0.0) >= 0.8,
        "open_specificity_at_least_0_9": (overall["open_specificity"] or 0.0) >= 0.9,
    }
    return {
        "stage": "phase_validation",
        "status": "passed",
        "checkpoint": str(args.checkpoint),
        "dataset_root": str(args.dataset_root),
        "episodes": int(metadata.total_episodes),
        "frames": len(dataset),
        "phase_definition": {
            "transition_radius_frames": args.transition_radius,
            "close_threshold": 0.5,
        },
        "overall": overall,
        "phases": {phase: summarize_errors(by_phase[phase]) for phase in PHASES},
        "quality_gate": {**quality_gate, "passed": all(quality_gate.values())},
        "event_windows": event_windows,
        "inference_timing_ms": {
            "mean": float(np.mean(inference_ms)),
            "median": float(np.median(inference_ms)),
            "max": float(np.max(inference_ms)),
        },
        "deterministic_noise_seed": args.seed,
        "started_at": args.started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--num-train-steps", type=int, required=True)
    parser.add_argument("--inference-steps", type=int, default=2)
    parser.add_argument("--transition-radius", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for name in ("dataset_root", "training_root", "base_checkpoint", "checkpoint", "report"):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.inference_steps < 1 or args.transition_radius < 0:
        parser.error("inference steps must be positive and transition radius nonnegative")
    args.started_at = datetime.now(timezone.utc).isoformat()
    return args


def main() -> None:
    args = parse_args()
    try:
        result = evaluate(args)
    except Exception as error:
        result = {
            "stage": "phase_validation",
            "status": "failed",
            "checkpoint": str(args.checkpoint),
            "error": f"{type(error).__name__}: {error}",
            "started_at": args.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_report(args.report, result)
        raise
    _write_report(args.report, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
