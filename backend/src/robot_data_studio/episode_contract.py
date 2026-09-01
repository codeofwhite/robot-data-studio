from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class EpisodeDescriptor:
    episode_uuid: str
    task: str
    num_frames: int
    operator_success: bool | None
    auto_success: bool | None
    failure_reason: str | None
    created_at: str | None
    manifest: dict


def inspect_episode(manifest_path: Path, *, engine_id: str) -> EpisodeDescriptor:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    episode_uuid = str(manifest["episode_uuid"])
    task = str(manifest["task"])
    num_frames = int(manifest["num_frames"])
    fps = int(manifest["fps"])
    if not episode_uuid or not task or num_frames <= 0 or fps <= 0:
        raise ValueError("episode identity, task, num_frames, and fps must be valid")

    trajectory_path = manifest_path.parent / "trajectory.npz"
    with np.load(trajectory_path, allow_pickle=False) as arrays:
        required = {"state", "actions", "frame_index", "timestamp", "sim_time"}
        missing = sorted(required - set(arrays.files))
        if missing:
            raise ValueError(f"episode is missing required arrays: {missing}")
        for name in arrays.files:
            value = arrays[name]
            if value.ndim == 0 or value.shape[0] != num_frames:
                raise ValueError(f"array {name} does not have {num_frames} frames")
            if np.issubdtype(value.dtype, np.number) and not np.isfinite(value).all():
                raise ValueError(f"array {name} contains NaN or Inf")
        if not np.array_equal(arrays["frame_index"], np.arange(num_frames)):
            raise ValueError("frame_index must be contiguous and zero based")
        expected_time = np.arange(num_frames, dtype=np.float64) / fps
        if not np.allclose(arrays["timestamp"], expected_time, atol=1e-6, rtol=0.0):
            raise ValueError("timestamp must equal frame_index / fps")

    camera_names = manifest.get("camera_names", [])
    if not isinstance(camera_names, list) or any(not isinstance(name, str) or not name for name in camera_names):
        raise ValueError("camera_names must be a list of non-empty strings")
    for camera_name in camera_names:
        count = len(list((manifest_path.parent / f"{camera_name}_rgb").glob("*.jpg")))
        if count != num_frames:
            raise ValueError(f"camera {camera_name} has {count} frames, expected {num_frames}")

    normalized = dict(manifest)
    normalized.setdefault("engine_id", engine_id)
    automatic_outcome = normalized.get("automatic_outcome")
    auto_success = normalized.get("auto_success")
    if automatic_outcome == "unavailable" or auto_success is None:
        parsed_auto_success = None
    else:
        parsed_auto_success = bool(auto_success)
    operator_success = normalized.get("operator_success")
    return EpisodeDescriptor(
        episode_uuid=episode_uuid,
        task=task,
        num_frames=num_frames,
        operator_success=None if operator_success is None else bool(operator_success),
        auto_success=parsed_auto_success,
        failure_reason=normalized.get("failure_reason"),
        created_at=normalized.get("created_at"),
        manifest=normalized,
    )
