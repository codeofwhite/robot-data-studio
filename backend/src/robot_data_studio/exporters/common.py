from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from robot_data_contracts import CanonicalEpisode, open_canonical_episode


PROVENANCE_FILE = "robot_data_provenance.jsonl"


def discover_episodes(root: Path) -> list[Path]:
    source = root.expanduser().resolve()
    if (source / "manifest.json").is_file():
        return [source]
    return sorted(
        path.parent
        for path in source.rglob("manifest.json")
        if not path.parent.name.endswith(".tmp")
    )


def load_canonical_episodes(paths: Iterable[Path]) -> list[CanonicalEpisode]:
    episodes = [open_canonical_episode(path) for path in paths]
    if not episodes:
        raise ValueError("No canonical episodes were selected")
    first = episodes[0].manifest
    for episode in episodes[1:]:
        manifest = episode.manifest
        if manifest.robot_id != first.robot_id:
            raise ValueError("all episodes must use the same robot_id")
        if manifest.fps != first.fps:
            raise ValueError("all episodes must use the same fps")
        if manifest.action_profile != first.action_profile:
            raise ValueError("all episodes must use the same action profile")
        if tuple(manifest.camera_names) != tuple(first.camera_names):
            raise ValueError("all episodes must use the same ordered camera set")
        for key in ("ee_pose", "object_pose"):
            if (key in episode.arrays) != (key in episodes[0].arrays):
                raise ValueError(f"all episodes must agree on optional array {key}")
    return episodes


def read_rgb(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required in the configured image export environment") from error
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def provenance_record(episode: CanonicalEpisode, output_episode_index: int) -> dict:
    manifest = episode.manifest
    software = manifest.software
    return {
        "output_episode_index": output_episode_index,
        "source_episode_uuid": manifest.episode_uuid,
        "source_episode_index": manifest.episode_index,
        "engine_id": software.engine_id,
        "engine_version": software.engine_version,
        "worker_id": software.worker_id,
        "scene_id": manifest.scene.scene_id,
        "seed": manifest.scene.seed,
        "control_source": manifest.control_source,
        "generation_method": manifest.lineage.generation_method,
        "git_revisions": software.git_revisions,
    }


def write_directory_provenance(output: Path, episodes: list[CanonicalEpisode]) -> Path:
    metadata_root = output / "meta"
    metadata_root.mkdir(parents=True, exist_ok=True)
    destination = metadata_root / PROVENANCE_FILE
    rows = [
        json.dumps(provenance_record(episode, index), sort_keys=True)
        for index, episode in enumerate(episodes)
    ]
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return destination


def deterministic_split(episode_uuid: str, explicit: str | None = None) -> str:
    if explicit in {"train", "valid", "test"}:
        return explicit
    bucket = int(hashlib.sha256(episode_uuid.encode()).hexdigest()[:8], 16) % 100
    return "valid" if bucket < 10 else "test" if bucket < 20 else "train"


def normalize_franka_joint8(action: np.ndarray) -> np.ndarray:
    value = np.asarray(action, dtype=np.float32).reshape(-1)
    low = np.asarray([-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973, 0.0], dtype=np.float32)
    high = np.asarray([2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973, 0.08], dtype=np.float32)
    if value.shape != (8,) or not np.isfinite(value).all():
        raise ValueError("canonical Franka action must contain 8 finite values")
    return np.clip(2.0 * (value - low) / (high - low) - 1.0, -1.0, 1.0).astype(np.float32)
