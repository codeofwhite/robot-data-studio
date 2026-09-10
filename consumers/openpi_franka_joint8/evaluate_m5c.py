"""Evaluate M5c gripper-timing variants on the fixed M5b event frames."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from consumers.openpi_franka_joint8.config import ACTION_DIM, make_train_config
from consumers.openpi_franka_joint8.evaluate_m5b_alignment import (
    _load_inputs,
    event_frames,
    first_closed_offset,
    summarize,
)


def build_gates(
    overall: dict[str, Any],
    events: dict[str, dict[str, Any]],
    timing_summary: dict[str, Any],
    *,
    arm_unchanged: bool,
) -> dict[str, bool]:
    gates = {
        "joint_first_step_mae_at_most_0_1_rad": overall["joint_first_step_mae_rad"]
        <= 0.1,
        "approach_minus_5_open_specificity_at_least_0_8": (
            events["approach_minus_5"]["open_specificity"] or 0.0
        )
        >= 0.8,
        "approach_minus_2_open_specificity_at_least_0_8": (
            events["approach_minus_2"]["open_specificity"] or 0.0
        )
        >= 0.8,
        "close_recall_at_least_0_8": (events["close"]["close_recall"] or 0.0)
        >= 0.8,
        "grasp_close_recall_at_least_0_95": (
            events["grasp"]["close_recall"] or 0.0
        )
        >= 0.95,
        "lift_close_recall_at_least_0_95": (
            events["lift"]["close_recall"] or 0.0
        )
        >= 0.95,
        "median_close_offset_error_within_1_frame": (
            timing_summary["median_close_offset_error_frames"] is not None
            and abs(timing_summary["median_close_offset_error_frames"]) <= 1.0
        ),
        "arm_actions_unchanged_when_overridden": arm_unchanged,
    }
    return {**gates, "passed": all(gates.values())}


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata
    from openpi.policies import policy_config

    selected_paths, selected_episode_indices = _load_inputs(args)
    metadata = LeRobotDatasetMetadata(args.dataset_root.name, root=args.dataset_root)
    dataset = LeRobotDataset(
        args.dataset_root.name,
        root=args.dataset_root,
        delta_timestamps={
            "action": [step / metadata.fps for step in range(args.action_horizon)]
        },
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
        action_horizon=args.action_horizon,
    )
    policy = policy_config.create_trained_policy(
        config, args.checkpoint, sample_kwargs={"num_steps": args.inference_steps}
    )
    head = None
    if args.gripper_head is not None:
        from consumers.openpi_franka_joint8.gripper_event_head import load_gripper_head

        head = load_gripper_head(args.gripper_head, device=args.gripper_head_device)
        if head.action_horizon != args.action_horizon:
            raise ValueError("policy and gripper head horizons differ")

    records: list[dict[str, Any]] = []
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inference_ms: list[float] = []
    arm_unchanged = True
    for attempt_id, episode_path in sorted(selected_paths.items()):
        with np.load(episode_path / "trajectory.npz", allow_pickle=False) as archive:
            frames = event_frames(archive["trajectory_phase_id"], archive["applied_action"])
        episode_index = selected_episode_indices[attempt_id]
        for event, frame_index in frames.items():
            dataset_index = dataset_indices[(episode_index, frame_index)]
            sample = dataset[dataset_index]
            observation = {
                "observation/image": sample["observation.images.base"],
                "observation/wrist_image": sample["observation.images.wrist"],
                "observation/state": np.asarray(sample["observation.state"], dtype=np.float32),
                "prompt": sample["task"],
            }
            noise = np.random.default_rng(
                args.seed + episode_index * 100_000 + frame_index
            ).standard_normal(
                (config.model.action_horizon, config.model.action_dim), dtype=np.float32
            )
            output = policy.infer(observation, noise=noise)
            base_prediction = np.asarray(output["actions"], dtype=np.float32)
            predicted = base_prediction.copy()
            if head is not None:
                from consumers.openpi_franka_joint8.gripper_event_head import (
                    predict_gripper_chunk,
                )

                predicted[:, 7] = predict_gripper_chunk(
                    head, observation, device=args.gripper_head_device
                )
                arm_unchanged = arm_unchanged and np.array_equal(
                    predicted[:, :7], base_prediction[:, :7]
                )
            target = np.asarray(sample["action"], dtype=np.float32)
            valid = ~np.asarray(sample["action_is_pad"], dtype=bool)
            if predicted.shape != (args.action_horizon, ACTION_DIM):
                raise ValueError(f"invalid prediction shape: {predicted.shape}")
            record = {
                "attempt_id": attempt_id,
                "episode_index": episode_index,
                "frame_index": frame_index,
                "event": event,
                "joint_first_abs_error_rad": np.abs(predicted[0, :7] - target[0, :7]),
                "target_gripper": float(target[0, 7]),
                "predicted_gripper": float(predicted[0, 7]),
                "target_closed": bool(target[0, 7] >= 0.5),
                "predicted_closed": bool(predicted[0, 7] >= 0.5),
                "target_first_close_offset_frames": first_closed_offset(target[valid, 7]),
                "predicted_first_close_offset_frames": first_closed_offset(predicted[valid, 7]),
            }
            records.append(record)
            by_event[event].append(record)
            inference_ms.append(float(output["policy_timing"]["infer_ms"]))

    events = {name: summarize(values) for name, values in by_event.items()}
    timing_records = (
        by_event["approach_minus_5"] + by_event["approach_minus_2"] + by_event["close"]
    )
    timing_summary = summarize(timing_records)
    overall = summarize(records)
    gates = build_gates(
        overall, events, timing_summary, arm_unchanged=arm_unchanged
    )
    return {
        "stage": "m5c_teacher_forced",
        "status": "completed",
        "variant": args.variant,
        "checkpoint": str(args.checkpoint),
        "gripper_head": str(args.gripper_head) if args.gripper_head else None,
        "action_horizon": args.action_horizon,
        "selected_successful_m2_episodes": len(selected_paths),
        "event_records": len(records),
        "overall": overall,
        "timing": timing_summary,
        "events": events,
        "gates": gates,
        "inference_timing_ms": {
            "median": float(np.median(inference_ms)),
            "max": float(np.max(inference_ms)),
        },
        "review_status": "SELF_REVIEWED_PROVISIONAL",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--num-train-steps", type=int, required=True)
    parser.add_argument("--action-horizon", type=int, required=True)
    parser.add_argument("--inference-steps", type=int, default=2)
    parser.add_argument("--gripper-head", type=Path)
    parser.add_argument("--gripper-head-device", default="cpu")
    parser.add_argument("--selection-report", type=Path, required=True)
    parser.add_argument("--m2-plan", type=Path, required=True)
    parser.add_argument("--m2-report", type=Path, required=True)
    parser.add_argument("--evaluation-plan", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261107)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for name in (
        "dataset_root", "training_root", "base_checkpoint", "checkpoint",
        "selection_report", "m2_plan", "m2_report", "evaluation_plan", "report",
    ):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.gripper_head is not None:
        args.gripper_head = args.gripper_head.expanduser().resolve()
    if min(args.num_train_steps, args.action_horizon, args.inference_steps) < 1:
        parser.error("training steps, horizon, and inference steps must be positive")
    return args


def main() -> None:
    args = parse_args()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = evaluate(args)
    except Exception as error:
        result = {
            "stage": "m5c_teacher_forced",
            "status": "failed",
            "variant": args.variant,
            "error": f"{type(error).__name__}: {error}",
        }
        raise
    finally:
        result.update(started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"variant": result["variant"], "gates": result.get("gates")}, indent=2))


if __name__ == "__main__":
    main()
