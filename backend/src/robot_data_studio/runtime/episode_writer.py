from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from typing import Any
from uuid import uuid4

import numpy as np


@dataclass
class _ActiveEpisode:
    index: int
    task: str
    tmp_dir: Path
    episode_uuid: str
    started_at: float
    arrays: dict[str, list[np.ndarray | np.generic]] = field(default_factory=dict)


class EpisodeWriter:
    """Engine-neutral, atomic writer for synchronized simulation episodes."""

    def __init__(
        self,
        root: str | Path,
        *,
        fps: int,
        engine_id: str,
        engine_version: str,
        scene_id: str,
        robot_id: str,
        control_source: str,
        state_names: list[str],
        action_names: list[str],
        camera_names: list[str],
        run_metadata: dict[str, Any],
        jpeg_quality: int = 95,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.fps = int(fps)
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        self.engine_id = engine_id
        self.engine_version = engine_version
        self.scene_id = scene_id
        self.robot_id = robot_id
        self.control_source = control_source
        self.state_names = list(state_names)
        self.action_names = list(action_names)
        self.camera_names = list(camera_names)
        self.run_metadata = dict(run_metadata)
        self.jpeg_quality = int(jpeg_quality)
        self._active: _ActiveEpisode | None = None

    @property
    def is_recording(self) -> bool:
        return self._active is not None

    @property
    def frame_count(self) -> int:
        return 0 if self._active is None else len(self._active.arrays.get("state", []))

    def start(self, task: str) -> int:
        if self.is_recording:
            raise RuntimeError("an episode is already recording")
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")
        index = self._next_index()
        tmp_dir = self.root / f"episode_{index:06d}.tmp"
        tmp_dir.mkdir(parents=False, exist_ok=False)
        for camera_name in self.camera_names:
            (tmp_dir / f"{camera_name}_rgb").mkdir()
        self._active = _ActiveEpisode(index, task, tmp_dir, str(uuid4()), time.monotonic())
        return index

    def add_frame(
        self,
        *,
        images: dict[str, np.ndarray],
        state: np.ndarray,
        action: np.ndarray,
        sim_time: float,
        control_sequence: int,
        control_timestamp_ns: int,
        extra_arrays: dict[str, np.ndarray] | None = None,
    ) -> None:
        active = self._require_active()
        frame_index = self.frame_count
        values: dict[str, np.ndarray | np.generic] = {
            "state": self._vector(state, len(self.state_names), "state"),
            "actions": self._vector(action, len(self.action_names), "actions"),
            "frame_index": np.int64(frame_index),
            "timestamp": np.float64(frame_index / self.fps),
            "sim_time": np.float64(sim_time),
            "monotonic_time": np.float64(time.monotonic() - active.started_at),
            "control_sequence": np.int64(control_sequence),
            "control_timestamp_ns": np.int64(control_timestamp_ns),
        }
        for name, value in (extra_arrays or {}).items():
            array = np.asarray(value)
            if array.ndim == 0 or not np.isfinite(array).all():
                raise ValueError(f"extra array {name} must be finite and non-scalar")
            values[name] = array
        for name, value in values.items():
            if frame_index and name in active.arrays and np.asarray(value).shape != np.asarray(active.arrays[name][0]).shape:
                raise ValueError(f"array {name} changed shape within the episode")
            active.arrays.setdefault(name, []).append(value)

        if set(images) != set(self.camera_names):
            raise ValueError(f"images has cameras {sorted(images)}, expected {sorted(self.camera_names)}")
        for camera_name, image in images.items():
            self._write_rgb(active.tmp_dir / f"{camera_name}_rgb" / f"{frame_index:06d}.jpg", image)

    def finish(self, *, operator_success: bool, episode_metrics: dict[str, Any] | None = None) -> Path:
        active = self._require_active()
        if self.frame_count == 0:
            raise RuntimeError("cannot save an empty episode")
        arrays = {name: np.stack(values) for name, values in active.arrays.items()}
        length = self.frame_count
        arrays["reward"] = np.zeros(length, dtype=np.float32)
        arrays["discount"] = np.ones(length, dtype=np.float32)
        arrays["is_first"] = np.zeros(length, dtype=np.bool_)
        arrays["is_last"] = np.zeros(length, dtype=np.bool_)
        arrays["is_terminal"] = np.zeros(length, dtype=np.bool_)
        arrays["is_first"][0] = True
        arrays["is_last"][-1] = True
        np.savez_compressed(active.tmp_dir / "trajectory.npz", **arrays)
        manifest = {
            "format": "robot_data_studio_episode",
            "format_version": 1,
            "episode_uuid": active.episode_uuid,
            "episode_index": active.index,
            "task": active.task,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "scene_id": self.scene_id,
            "robot_id": self.robot_id,
            "control_source": self.control_source,
            "operator_success": bool(operator_success),
            "auto_success": None,
            "automatic_outcome": "unavailable",
            "failure_reason": None if operator_success else "operator_marked_failure",
            "fps": self.fps,
            "num_frames": length,
            "state_names": self.state_names,
            "action_names": self.action_names,
            "camera_names": self.camera_names,
            "timing": "observation_t is recorded immediately before action_t is applied",
            "image_color_order": "RGB",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "episode_metrics": episode_metrics or {},
            "run_metadata": self.run_metadata,
        }
        (active.tmp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        final_dir = self.root / f"episode_{active.index:06d}"
        active.tmp_dir.rename(final_dir)
        self._active = None
        return final_dir

    def discard(self) -> None:
        active = self._require_active()
        shutil.rmtree(active.tmp_dir)
        self._active = None

    def _next_index(self) -> int:
        indices: list[int] = []
        for path in self.root.glob("episode_[0-9]*"):
            suffix = path.name.removesuffix(".tmp").removeprefix("episode_")
            if suffix.isdigit():
                indices.append(int(suffix))
        return max(indices, default=-1) + 1

    def _require_active(self) -> _ActiveEpisode:
        if self._active is None:
            raise RuntimeError("no episode is recording")
        return self._active

    @staticmethod
    def _vector(value: np.ndarray, size: int, name: str) -> np.ndarray:
        array = np.asarray(value, dtype=np.float32).reshape(-1)
        if array.shape != (size,) or not np.isfinite(array).all():
            raise ValueError(f"{name} must contain {size} finite values")
        return array

    def _write_rgb(self, path: Path, image: np.ndarray) -> None:
        image = np.asarray(image)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[-1] != 3:
            raise ValueError(f"expected uint8 HWC RGB image, got {image.dtype} {image.shape}")
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("OpenCV is required by the active engine to encode RGB frames") from error
        ok = cv2.imwrite(
            str(path),
            cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        if not ok:
            raise OSError(f"failed to write image: {path}")
