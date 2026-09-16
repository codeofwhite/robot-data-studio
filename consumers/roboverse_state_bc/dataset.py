from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import torch
from torch.utils.data import Dataset


PICK_CUBE_TASK = "maniskill.pick_cube_native"
PICK_CUBE_SCENE = "maniskill_pick_cube_native"
PICK_CUBE_EVALUATOR = "roboverse_maniskill_pick_cube_success"
SEED_SEMANTICS = "maniskill_source_episode_seed"
NATIVE_PAYLOAD_SCHEMA = "roboverse_maniskill_native_v2_pre_action"

JOINT_STATE_DIM = 18
OBJECT_POSE_DIM = 7
GOAL_POSITION_DIM = 3
OBSERVATION_DIM = JOINT_STATE_DIM + OBJECT_POSE_DIM + GOAL_POSITION_DIM
ACTION_DIM = 8


@dataclass(frozen=True)
class EpisodeRecord:
    database_id: int
    episode_uuid: str
    path: Path
    seed: int
    source_demo_trajectory: str
    num_frames: int

    def as_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "episode_uuid": self.episode_uuid,
            "path": str(self.path),
            "seed": self.seed,
            "source_demo_trajectory": self.source_demo_trajectory,
            "num_frames": self.num_frames,
        }


@dataclass(frozen=True)
class EpisodeArrays:
    observation: np.ndarray
    action: np.ndarray
    raw_action: np.ndarray


@dataclass(frozen=True)
class ObservationNormalizer:
    mean: np.ndarray
    std: np.ndarray
    action_low: float = -1.0
    action_high: float = 1.0

    def transform_numpy(self, observation: np.ndarray) -> np.ndarray:
        return ((observation - self.mean) / self.std).astype(np.float32)

    def transform_tensor(self, observation: torch.Tensor) -> torch.Tensor:
        mean = torch.as_tensor(self.mean, dtype=observation.dtype, device=observation.device)
        std = torch.as_tensor(self.std, dtype=observation.dtype, device=observation.device)
        return (observation - mean) / std

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            mean=self.mean.astype(np.float32),
            std=self.std.astype(np.float32),
            action_low=np.asarray(self.action_low, dtype=np.float32),
            action_high=np.asarray(self.action_high, dtype=np.float32),
        )

    @classmethod
    def load(cls, path: Path) -> ObservationNormalizer:
        with np.load(path, allow_pickle=False) as payload:
            return cls(
                mean=np.asarray(payload["mean"], dtype=np.float32),
                std=np.asarray(payload["std"], dtype=np.float32),
                action_low=float(payload["action_low"]),
                action_high=float(payload["action_high"]),
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_native_payload(episode_path: Path, scene: dict) -> Path:
    assets = scene.get("assets") or []
    matches = [asset for asset in assets if asset.get("role") == "native_payload"]
    if len(matches) != 1:
        raise ValueError(f"{episode_path}: expected exactly one native_payload asset")
    asset = matches[0]
    payload_path = episode_path / str(asset.get("path"))
    checksum_path = episode_path / str(asset.get("checksum"))
    if not payload_path.is_file() or not checksum_path.is_file():
        raise ValueError(f"{episode_path}: native payload or checksum is missing")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    actual = _sha256(payload_path)
    if actual != expected:
        raise ValueError(f"{episode_path}: native payload checksum mismatch")
    return payload_path


def _validated_record(row: sqlite3.Row) -> EpisodeRecord:
    episode_path = Path(row["path"])
    manifest_path = episode_path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{episode_path}: manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("episode_uuid") != row["episode_uuid"]:
        raise ValueError(f"{episode_path}: database and manifest UUID disagree")
    if manifest.get("task") != PICK_CUBE_TASK:
        raise ValueError(f"{episode_path}: expected task {PICK_CUBE_TASK}")

    scene = manifest.get("scene") or {}
    parameters = scene.get("parameters") or {}
    if scene.get("scene_id") != PICK_CUBE_SCENE:
        raise ValueError(f"{episode_path}: expected scene {PICK_CUBE_SCENE}")
    if parameters.get("seed_semantics") != SEED_SEMANTICS:
        raise ValueError(f"{episode_path}: incomplete P2 seed semantics")
    if parameters.get("control_mode") != "pd_joint_delta_pos":
        raise ValueError(f"{episode_path}: unexpected control mode")
    if parameters.get("native_payload_schema") != NATIVE_PAYLOAD_SCHEMA:
        raise ValueError(
            f"{episode_path}: legacy native payload lacks exact pre-action state"
        )
    if parameters.get("source_demo_success") is not True:
        raise ValueError(f"{episode_path}: source demo is not marked successful")

    evaluator = manifest.get("evaluator") or {}
    if evaluator.get("evaluator_id") != PICK_CUBE_EVALUATOR:
        raise ValueError(f"{episode_path}: unexpected evaluator")
    if evaluator.get("available") is not True or evaluator.get("success") is not True:
        raise ValueError(f"{episode_path}: native evaluator did not succeed")

    seed = scene.get("seed")
    lineage = manifest.get("lineage") or {}
    resolved = lineage.get("resolved_parameters") or {}
    if not isinstance(seed, int) or seed != resolved.get("source_episode_seed"):
        raise ValueError(f"{episode_path}: scene and lineage seeds disagree")
    source_demo = parameters.get("source_demo_trajectory")
    if source_demo != resolved.get("source_demo_trajectory"):
        raise ValueError(f"{episode_path}: source demo provenance disagrees")
    if not isinstance(source_demo, str) or not source_demo.startswith("traj_"):
        raise ValueError(f"{episode_path}: invalid source demo trajectory")

    _verify_native_payload(episode_path, scene)
    return EpisodeRecord(
        database_id=int(row["id"]),
        episode_uuid=str(row["episode_uuid"]),
        path=episode_path,
        seed=seed,
        source_demo_trajectory=source_demo,
        num_frames=int(row["num_frames"]),
    )


def _trajectory_number(record: EpisodeRecord) -> int:
    return int(record.source_demo_trajectory.removeprefix("traj_"))


def load_accepted_pickcube_episodes(
    db_path: Path,
    dataset_name: str,
    *,
    expected_count: int | None = None,
) -> list[EpisodeRecord]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT e.id, e.episode_uuid, e.path, e.num_frames
            FROM episodes AS e
            JOIN sessions AS s ON s.id = e.session_id
            JOIN datasets AS d ON d.id = s.dataset_id
            WHERE d.name = ? AND e.task = ? AND e.qa_status = 'accepted'
              AND e.auto_success = 1
            ORDER BY e.id
            """,
            (dataset_name, PICK_CUBE_TASK),
        ).fetchall()
    finally:
        connection.close()
    records = sorted((_validated_record(row) for row in rows), key=_trajectory_number)
    seeds = [record.seed for record in records]
    uuids = [record.episode_uuid for record in records]
    if len(seeds) != len(set(seeds)):
        raise ValueError("accepted PickCube episodes contain duplicate seeds")
    if len(uuids) != len(set(uuids)):
        raise ValueError("accepted PickCube episodes contain duplicate UUIDs")
    if expected_count is not None and len(records) != expected_count:
        raise ValueError(
            f"expected {expected_count} accepted PickCube episodes in {dataset_name}, "
            f"found {len(records)}"
        )
    return records


def load_episode_arrays(record: EpisodeRecord) -> EpisodeArrays:
    payload_path = record.path / "native_trajectory.npz"
    with np.load(payload_path, allow_pickle=False) as payload:
        required = {
            "joint_state": (JOINT_STATE_DIM,),
            "object_pose": (OBJECT_POSE_DIM,),
            "task_state": (OBJECT_POSE_DIM + GOAL_POSITION_DIM,),
            "pre_action_joint_state": (JOINT_STATE_DIM,),
            "pre_action_object_pose": (OBJECT_POSE_DIM,),
            "pre_action_task_state": (OBJECT_POSE_DIM + GOAL_POSITION_DIM,),
            "normalized_action": (ACTION_DIM,),
        }
        arrays: dict[str, np.ndarray] = {}
        for name, tail_shape in required.items():
            if name not in payload:
                raise ValueError(f"{record.path}: native payload is missing {name}")
            array = np.asarray(payload[name], dtype=np.float32)
            if array.ndim != 2 or array.shape[1:] != tail_shape:
                raise ValueError(
                    f"{record.path}: {name} has shape {array.shape}, "
                    f"expected (frames, {tail_shape[0]})"
                )
            arrays[name] = array
    frame_counts = {array.shape[0] for array in arrays.values()}
    if frame_counts != {record.num_frames}:
        raise ValueError(f"{record.path}: native arrays disagree with manifest frame count")
    if not all(np.isfinite(array).all() for array in arrays.values()):
        raise ValueError(f"{record.path}: native arrays contain non-finite values")
    if not np.allclose(arrays["task_state"][:, :OBJECT_POSE_DIM], arrays["object_pose"], atol=1e-6):
        raise ValueError(f"{record.path}: object pose and task state disagree")
    if not np.allclose(
        arrays["pre_action_task_state"][:, :OBJECT_POSE_DIM],
        arrays["pre_action_object_pose"],
        atol=1e-6,
    ):
        raise ValueError(f"{record.path}: pre-action object pose and task state disagree")

    observation = np.concatenate(
        (
            arrays["pre_action_joint_state"],
            arrays["pre_action_object_pose"],
            arrays["pre_action_task_state"][:, -GOAL_POSITION_DIM:],
        ),
        axis=1,
    ).astype(np.float32)
    raw_action = arrays["normalized_action"]
    action = np.clip(raw_action, -1.0, 1.0).astype(np.float32)
    return EpisodeArrays(observation=observation, action=action, raw_action=raw_action)


def split_episodes(
    records: Sequence[EpisodeRecord],
    *,
    train_count: int,
    validation_count: int,
    split_seed: int,
) -> tuple[list[EpisodeRecord], list[EpisodeRecord]]:
    if train_count <= 0 or validation_count <= 0:
        raise ValueError("train and validation counts must both be positive")
    if len(records) != train_count + validation_count:
        raise ValueError("episode count does not match requested train/validation split")
    permutation = np.random.default_rng(split_seed).permutation(len(records))
    train = [records[int(index)] for index in permutation[:train_count]]
    validation = [records[int(index)] for index in permutation[train_count:]]
    assert_disjoint_seeds(train, validation)
    return train, validation


def assert_disjoint_seeds(*groups: Iterable[EpisodeRecord | int]) -> None:
    seen: set[int] = set()
    for group in groups:
        seeds = {
            item.seed if isinstance(item, EpisodeRecord) else int(item)
            for item in group
        }
        overlap = seen.intersection(seeds)
        if overlap:
            raise ValueError(f"seed split overlap: {sorted(overlap)}")
        seen.update(seeds)


class StateActionChunkDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, records: Sequence[EpisodeRecord], *, action_horizon: int) -> None:
        if action_horizon <= 0:
            raise ValueError("action_horizon must be positive")
        self.records = list(records)
        self.action_horizon = action_horizon
        self.arrays = [load_episode_arrays(record) for record in self.records]
        self.samples = [
            (episode_index, frame_index)
            for episode_index, arrays in enumerate(self.arrays)
            for frame_index in range(arrays.observation.shape[0])
        ]

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        episode_index, frame_index = self.samples[index]
        arrays = self.arrays[episode_index]
        action_start = frame_index
        stop = min(action_start + self.action_horizon, arrays.action.shape[0])
        valid = stop - action_start
        action = np.zeros((self.action_horizon, ACTION_DIM), dtype=np.float32)
        action[:valid] = arrays.action[action_start:stop]
        mask = np.zeros(self.action_horizon, dtype=np.float32)
        mask[:valid] = 1.0
        return {
            "observation": torch.from_numpy(arrays.observation[frame_index]),
            "action": torch.from_numpy(action),
            "action_mask": torch.from_numpy(mask),
            "episode_index": torch.tensor(episode_index, dtype=torch.int64),
            "frame_index": torch.tensor(frame_index, dtype=torch.int64),
        }

    @property
    def observations(self) -> np.ndarray:
        return np.concatenate([arrays.observation for arrays in self.arrays], axis=0)

    def action_statistics(self) -> dict[str, object]:
        raw = np.concatenate([arrays.raw_action for arrays in self.arrays], axis=0)
        outside = np.abs(raw) > 1.0
        return {
            "elements": int(raw.size),
            "rows": int(raw.shape[0]),
            "out_of_bounds_elements": int(outside.sum()),
            "out_of_bounds_element_fraction": float(outside.mean()),
            "rows_with_out_of_bounds": int(np.any(outside, axis=1).sum()),
            "rows_with_out_of_bounds_fraction": float(np.any(outside, axis=1).mean()),
            "raw_min": raw.min(axis=0).tolist(),
            "raw_max": raw.max(axis=0).tolist(),
            "effective_min": np.clip(raw, -1.0, 1.0).min(axis=0).tolist(),
            "effective_max": np.clip(raw, -1.0, 1.0).max(axis=0).tolist(),
        }


def fit_observation_normalizer(dataset: StateActionChunkDataset) -> ObservationNormalizer:
    observation = dataset.observations.astype(np.float64)
    mean = observation.mean(axis=0)
    std = observation.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    return ObservationNormalizer(mean=mean.astype(np.float32), std=std.astype(np.float32))
