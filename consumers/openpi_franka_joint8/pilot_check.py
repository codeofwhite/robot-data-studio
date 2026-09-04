"""Validate an exported Isaac cube-lift dataset before OpenPI training."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np


PROVENANCE_FILE = "robot_data_provenance.jsonl"
REQUIRED_CAMERAS = ("base", "top", "wrist")
EXPECTED_ENGINE = "isaac_sim"
EXPECTED_SCENE = "rigid_cube_lift"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_provenance(rows: list[dict[str, Any]], expected_episodes: int) -> dict[str, Any]:
    if len(rows) != expected_episodes:
        raise ValueError(f"expected {expected_episodes} provenance rows, got {len(rows)}")
    engines = sorted({row.get("engine_id") for row in rows})
    scenes = sorted({row.get("scene_id") for row in rows})
    if engines != [EXPECTED_ENGINE]:
        raise ValueError(f"pilot requires only {EXPECTED_ENGINE}, got {engines}")
    if scenes != [EXPECTED_SCENE]:
        raise ValueError(f"pilot requires only {EXPECTED_SCENE}, got {scenes}")
    invalid = [
        row.get("source_episode_uuid", f"row-{index}")
        for index, row in enumerate(rows)
        if row.get("operator_success") is not True
        or row.get("automatic_success") is not True
        or row.get("evaluator_id") != "isaac_cube_lift_v1"
    ]
    if invalid:
        raise ValueError(
            "episodes lack matching operator and automatic success: " + ", ".join(invalid)
        )
    return {"engines": engines, "scenes": scenes, "validated_successes": len(rows)}


def validate_episode_actions(actions: np.ndarray) -> dict[str, int]:
    values = np.asarray(actions, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 8 or not np.isfinite(values).all():
        raise ValueError(f"episode actions must be finite [T, 8], got {values.shape}")
    closed = values[:, 7] >= 0.5
    close_rows = np.flatnonzero(closed)
    if not len(close_rows):
        raise ValueError("episode has no gripper close phase")
    first_close = int(close_rows[0])
    release_rows = np.flatnonzero((~closed) & (np.arange(len(closed)) > first_close))
    if first_close == 0:
        raise ValueError("episode has no open approach before close")
    if not len(release_rows):
        raise ValueError("episode has no release after close")
    first_release = int(release_rows[0])
    return {
        "frames": len(values),
        "approach_frames": first_close,
        "closed_frames": first_release - first_close,
        "post_release_frames": len(values) - first_release,
    }


def inspect_dataset(dataset_root: Path, expected_episodes: int) -> dict[str, Any]:
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata

    metadata = LeRobotDatasetMetadata(dataset_root.name, root=dataset_root)
    if str(metadata._version) != "2.1":
        raise ValueError(f"expected LeRobot v2.1, got {metadata._version}")
    if metadata.total_episodes != expected_episodes:
        raise ValueError(f"expected {expected_episodes} episodes, got {metadata.total_episodes}")

    feature_names = set(metadata.features)
    required_features = {"observation.state", "action"} | {
        f"observation.images.{name}" for name in REQUIRED_CAMERAS
    }
    missing = sorted(required_features - feature_names)
    if missing:
        raise ValueError("dataset is missing required features: " + ", ".join(missing))

    provenance_path = dataset_root / "meta" / PROVENANCE_FILE
    if not provenance_path.is_file():
        raise FileNotFoundError(f"dataset provenance is unavailable: {provenance_path}")
    provenance_rows = [
        json.loads(line) for line in provenance_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = validate_provenance(provenance_rows, expected_episodes)

    dataset = LeRobotDataset(dataset_root.name, root=dataset_root, video_backend="pyav")
    episode_rows: dict[int, list[int]] = defaultdict(list)
    for dataset_index, episode_index in enumerate(dataset.hf_dataset["episode_index"]):
        episode_rows[int(episode_index)].append(dataset_index)
    if len(episode_rows) != expected_episodes:
        raise ValueError(f"expected {expected_episodes} indexed episodes, got {len(episode_rows)}")

    episode_reports = []
    for episode_index in sorted(episode_rows):
        rows = episode_rows[episode_index]
        frame_indices = np.asarray([dataset.hf_dataset[index]["frame_index"] for index in rows])
        if not np.array_equal(frame_indices, np.arange(len(rows))):
            raise ValueError(f"episode {episode_index} frame indices are not contiguous")
        states = np.stack([np.asarray(dataset.hf_dataset[index]["observation.state"]) for index in rows])
        actions = np.stack([np.asarray(dataset.hf_dataset[index]["action"]) for index in rows])
        if states.shape != (len(rows), 8) or not np.isfinite(states).all():
            raise ValueError(f"episode {episode_index} states must be finite [T, 8]")
        phase = validate_episode_actions(actions)
        decoded = dataset[rows[0]]
        image_shapes = {}
        for camera in REQUIRED_CAMERAS:
            key = f"observation.images.{camera}"
            image = np.asarray(decoded[key])
            if image.ndim != 3 or 3 not in {image.shape[0], image.shape[-1]}:
                raise ValueError(f"episode {episode_index} camera {camera} is not RGB: {image.shape}")
            image_shapes[camera] = list(image.shape)
        episode_reports.append(
            {"episode_index": episode_index, **phase, "image_shapes": image_shapes}
        )

    return {
        "status": "passed",
        "dataset_root": str(dataset_root),
        "format": "lerobot_v2.1",
        "episodes": metadata.total_episodes,
        "frames": metadata.total_frames,
        "fps": metadata.fps,
        "required_cameras": list(REQUIRED_CAMERAS),
        "openpi_consumed_cameras": ["base", "wrist"],
        "qa_only_cameras": ["top"],
        "provenance": provenance,
        "episode_reports": episode_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--expected-episodes", type=int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_episodes <= 0:
        parser.error("--expected-episodes must be positive")
    dataset_root = args.dataset_root.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    started_at = _now()
    try:
        report = inspect_dataset(dataset_root, args.expected_episodes)
        report.update(started_at=started_at, finished_at=_now())
    except Exception as error:
        report = {
            "status": "failed",
            "dataset_root": str(dataset_root),
            "error": f"{type(error).__name__}: {error}",
            "started_at": started_at,
            "finished_at": _now(),
        }
        _write_report(report_path, report)
        raise
    _write_report(report_path, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
