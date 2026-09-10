"""Teacher-force the M5b successful M2 event frames through one OpenPI checkpoint."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from consumers.openpi_franka_joint8.config import ACTION_DIM, ACTION_HORIZON, make_train_config


EVENT_OFFSETS = {
    "approach_minus_5": ("close", -5),
    "approach_minus_2": ("close", -2),
    "close": ("close", 0),
    "close_plus_2": ("close", 2),
    "grasp": ("grasp", 0),
    "lift": ("lift", 0),
}


def phase_events(phase_id: np.ndarray) -> dict[str, int]:
    phases = np.asarray(phase_id, dtype=np.int64).reshape(-1)
    result: dict[str, int] = {}
    for name, value in (("close", 1), ("grasp", 2), ("lift", 3)):
        indices = np.flatnonzero(phases >= value)
        if not len(indices):
            raise ValueError(f"source trajectory has no {name} phase")
        result[name] = int(indices[0])
    return result


def event_frames(phase_id: np.ndarray, applied_action: np.ndarray) -> dict[str, int]:
    events = phase_events(phase_id)
    length = int(np.asarray(phase_id).shape[0])
    actions = np.asarray(applied_action, dtype=np.float64)
    if actions.ndim != 2 or actions.shape[0] != length or actions.shape[1] < ACTION_DIM:
        raise ValueError(
            f"applied_action must have shape ({length}, >={ACTION_DIM}), got {actions.shape}"
        )
    close_indices = np.flatnonzero(actions[:, 7] <= 0.04)
    if not len(close_indices):
        raise ValueError("source trajectory has no gripper close command")
    events["close"] = int(close_indices[0])
    return {
        label: min(max(events[event] + offset, 0), length - 1)
        for label, (event, offset) in EVENT_OFFSETS.items()
    }


def first_closed_offset(gripper_chunk: np.ndarray) -> int | None:
    indices = np.flatnonzero(np.asarray(gripper_chunk, dtype=np.float64).reshape(-1) >= 0.5)
    return int(indices[0]) if len(indices) else None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"frames": 0}
    first_joint = np.stack([record["joint_first_abs_error_rad"] for record in records])
    target_closed = np.asarray([record["target_closed"] for record in records], dtype=bool)
    predicted_closed = np.asarray([record["predicted_closed"] for record in records], dtype=bool)
    comparable_offsets = [
        record["predicted_first_close_offset_frames"]
        - record["target_first_close_offset_frames"]
        for record in records
        if record["target_first_close_offset_frames"] is not None
        and record["predicted_first_close_offset_frames"] is not None
    ]
    return {
        "frames": len(records),
        "joint_first_step_mae_rad": float(first_joint.mean()),
        "joint_first_step_mae_per_joint_rad": first_joint.mean(axis=0).tolist(),
        "gripper_first_step_mae": float(np.mean([
            abs(record["predicted_gripper"] - record["target_gripper"])
            for record in records
        ])),
        "target_close_rate": float(target_closed.mean()),
        "predicted_close_rate": float(predicted_closed.mean()),
        "gripper_accuracy": float(np.mean(target_closed == predicted_closed)),
        "close_recall": (
            float(np.mean(predicted_closed[target_closed])) if np.any(target_closed) else None
        ),
        "open_specificity": (
            float(np.mean(~predicted_closed[~target_closed])) if np.any(~target_closed) else None
        ),
        "chunk_target_contains_close_rate": float(np.mean([
            record["target_first_close_offset_frames"] is not None for record in records
        ])),
        "chunk_predicted_contains_close_rate": float(np.mean([
            record["predicted_first_close_offset_frames"] is not None for record in records
        ])),
        "median_close_offset_error_frames": (
            float(np.median(comparable_offsets)) if comparable_offsets else None
        ),
        "early_close_rate_among_comparable_chunks": (
            float(np.mean(np.asarray(comparable_offsets) < 0)) if comparable_offsets else None
        ),
    }


def selected_attempt_episode_indices(
    selection_report: dict[str, Any], selected_attempt_ids: set[str]
) -> dict[str, int]:
    episodes = selection_report["variants"]["human5_generated_success"]["episodes"]
    result = {
        str(item["attempt_id"]): index
        for index, item in enumerate(episodes)
        if item.get("attempt_id") in selected_attempt_ids
    }
    missing = selected_attempt_ids - set(result)
    if missing:
        raise ValueError(f"selected M2 attempts are absent from the training export: {sorted(missing)}")
    return result


def _load_inputs(args: argparse.Namespace) -> tuple[dict[str, Path], dict[str, int]]:
    generation_plan = json.loads(args.m2_plan.read_text(encoding="utf-8"))
    generation_report = json.loads(args.m2_report.read_text(encoding="utf-8"))
    evaluation_plan = json.loads(args.evaluation_plan.read_text(encoding="utf-8"))
    selection_report = json.loads(args.selection_report.read_text(encoding="utf-8"))
    successful = {
        item["attempt_id"]: Path(item["episode_path"])
        for item in generation_report["results"]
        if item["status"] == "succeeded"
    }
    selected_offsets = {
        tuple(condition["object_xy_offset_m"]) for condition in evaluation_plan["conditions"]
    }
    selected_paths = {
        attempt["attempt_id"]: successful[attempt["attempt_id"]]
        for attempt in generation_plan["attempts"]
        if attempt["attempt_id"] in successful
        and tuple(attempt["object_xy_offset_m"]) in selected_offsets
    }
    if not selected_paths:
        raise ValueError("no successful M2 demonstrations match the evaluation positions")
    episode_indices = selected_attempt_episode_indices(selection_report, set(selected_paths))
    return selected_paths, episode_indices


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from openpi.policies import policy_config

    selected_paths, selected_episode_indices = _load_inputs(args)
    metadata = LeRobotDatasetMetadata(args.dataset_root.name, root=args.dataset_root)
    dataset = LeRobotDataset(
        args.dataset_root.name,
        root=args.dataset_root,
        delta_timestamps={"action": [step / metadata.fps for step in range(ACTION_HORIZON)]},
        video_backend="pyav",
    )
    episode_column = np.asarray(dataset.hf_dataset["episode_index"], dtype=np.int64)
    frame_column = np.asarray(dataset.hf_dataset["frame_index"], dtype=np.int64)
    dataset_indices = {
        (int(episode), int(frame)): index
        for index, (episode, frame) in enumerate(zip(episode_column, frame_column))
    }
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
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cached: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray, float]] = {}
    for attempt_id, episode_path in sorted(selected_paths.items()):
        with np.load(episode_path / "trajectory.npz", allow_pickle=False) as archive:
            frames = event_frames(archive["trajectory_phase_id"], archive["applied_action"])
        episode_index = selected_episode_indices[attempt_id]
        for event, frame_index in frames.items():
            key = (episode_index, frame_index)
            if key not in dataset_indices:
                raise ValueError(f"training export is missing episode/frame {key}")
            if key not in cached:
                sample = dataset[dataset_indices[key]]
                noise_seed = args.seed + episode_index * 100_000 + frame_index
                noise = np.random.default_rng(noise_seed).standard_normal(
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
                if predicted.shape != (ACTION_HORIZON, ACTION_DIM):
                    raise ValueError(f"invalid prediction shape at {key}: {predicted.shape}")
                cached[key] = (
                    predicted,
                    target,
                    valid,
                    float(output["policy_timing"]["infer_ms"]),
                )
            predicted, target, valid, infer_ms = cached[key]
            record = {
                "attempt_id": attempt_id,
                "episode_index": episode_index,
                "frame_index": frame_index,
                "event": event,
                "target_joint": target[0, :7].tolist(),
                "predicted_joint": predicted[0, :7].tolist(),
                "joint_first_abs_error_rad": np.abs(predicted[0, :7] - target[0, :7]),
                "joint_chunk_mae_rad": float(
                    np.mean(np.abs(predicted[valid, :7] - target[valid, :7]))
                ),
                "target_gripper": float(target[0, 7]),
                "predicted_gripper": float(predicted[0, 7]),
                "target_closed": bool(target[0, 7] >= 0.5),
                "predicted_closed": bool(predicted[0, 7] >= 0.5),
                "target_first_close_offset_frames": first_closed_offset(target[valid, 7]),
                "predicted_first_close_offset_frames": first_closed_offset(predicted[valid, 7]),
                "infer_ms": infer_ms,
            }
            records.append(record)
            by_event[event].append(record)

    close_records = by_event["close"] + by_event["close_plus_2"]
    approach_records = by_event["approach_minus_5"] + by_event["approach_minus_2"]
    close_summary = summarize(close_records)
    approach_summary = summarize(approach_records)
    overall = summarize(records)
    joint_gate = overall["joint_first_step_mae_rad"] <= 0.1
    close_gate = (close_summary["close_recall"] or 0.0) >= 0.8
    open_gate = (approach_summary["open_specificity"] or 0.0) >= 0.8
    alignment = json.loads(args.alignment_report.read_text(encoding="utf-8"))
    if alignment.get("diagnosis") in {
        "action_contract_or_normalization_failure", "executor_tracking_failure"
    }:
        diagnosis = alignment["diagnosis"]
    elif not (joint_gate and close_gate and open_gate):
        diagnosis = "teacher_forced_model_fit_or_label_ambiguity"
    elif alignment.get("diagnosis") == "policy_close_timing_failure":
        diagnosis = "closed_loop_covariate_shift_or_event_timing_failure"
    else:
        diagnosis = "mixed_or_unresolved"
    return {
        "stage": "m5b_teacher_forced_alignment",
        "status": "completed",
        "review_status": "SELF_REVIEWED_PROVISIONAL",
        "checkpoint": str(args.checkpoint),
        "dataset_root": str(args.dataset_root),
        "selected_successful_m2_episodes": len(selected_paths),
        "unique_inference_frames": len(cached),
        "event_records": len(records),
        "overall": overall,
        "events": {event: summarize(by_event[event]) for event in EVENT_OFFSETS},
        "gates": {
            "joint_first_step_mae_at_most_0_1_rad": joint_gate,
            "close_event_recall_at_least_0_8": close_gate,
            "preclose_open_specificity_at_least_0_8": open_gate,
        },
        "alignment_diagnosis": alignment.get("diagnosis"),
        "diagnosis": diagnosis,
        "inference_timing_ms": {
            "median": float(np.median([value[3] for value in cached.values()])),
            "max": float(np.max([value[3] for value in cached.values()])),
        },
        "records": [
            {
                **record,
                "joint_first_abs_error_rad": record["joint_first_abs_error_rad"].tolist(),
            }
            for record in records
        ],
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
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--m2-plan", type=Path, required=True)
    parser.add_argument("--m2-report", type=Path, required=True)
    parser.add_argument("--evaluation-plan", type=Path, required=True)
    parser.add_argument("--alignment-report", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261107)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for name in (
        "dataset_root", "training_root", "base_checkpoint", "checkpoint", "selection_report",
        "m2_plan", "m2_report", "evaluation_plan", "alignment_report", "report",
    ):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    return args


def main() -> None:
    args = parse_args()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = evaluate(args)
    except Exception as error:
        result = {
            "stage": "m5b_teacher_forced_alignment",
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise
    result["started_at"] = started_at
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "diagnosis", "gates")}, indent=2))


if __name__ == "__main__":
    main()
