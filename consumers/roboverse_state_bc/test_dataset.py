from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from .dataset import (
    OBSERVATION_DIM,
    StateActionChunkDataset,
    fit_observation_normalizer,
    load_accepted_pickcube_episodes,
    split_episodes,
)


def _write_episode(root: Path, uuid: str, seed: int, *, seed_semantics: str) -> Path:
    episode = root / uuid
    episode.mkdir()
    frames = 4
    joint_state = np.full((frames, 18), seed / 100.0, dtype=np.float32)
    pre_action_joint_state = joint_state - 0.01
    object_pose = np.zeros((frames, 7), dtype=np.float32)
    object_pose[:, 3] = 1.0
    goal = np.full((frames, 3), 0.1, dtype=np.float32)
    task_state = np.concatenate((object_pose, goal), axis=1)
    normalized_action = np.zeros((frames, 8), dtype=np.float32)
    normalized_action[:, 0] = np.arange(frames, dtype=np.float32) / frames
    normalized_action[:, -1] = 3.0
    payload = episode / "native_trajectory.npz"
    np.savez_compressed(
        payload,
        joint_state=joint_state,
        pre_action_joint_state=pre_action_joint_state,
        object_pose=object_pose,
        pre_action_object_pose=object_pose,
        task_state=task_state,
        pre_action_task_state=task_state,
        normalized_action=normalized_action,
    )
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    (episode / "native_payload.sha256").write_text(
        f"{digest}  native_trajectory.npz\n", encoding="utf-8"
    )
    manifest = {
        "episode_uuid": uuid,
        "task": "maniskill.pick_cube_native",
        "scene": {
            "scene_id": "maniskill_pick_cube_native",
            "seed": seed,
            "parameters": {
                "seed_semantics": seed_semantics,
                "control_mode": "pd_joint_delta_pos",
                "native_payload_schema": "roboverse_maniskill_native_v2_pre_action",
                "source_demo_success": True,
                "source_demo_trajectory": f"traj_{seed}",
            },
            "assets": [
                {
                    "role": "native_payload",
                    "path": "native_trajectory.npz",
                    "checksum": "native_payload.sha256",
                }
            ],
        },
        "evaluator": {
            "evaluator_id": "roboverse_maniskill_pick_cube_success",
            "available": True,
            "success": True,
        },
        "lineage": {
            "resolved_parameters": {
                "source_episode_seed": seed,
                "source_demo_trajectory": f"traj_{seed}",
            }
        },
    }
    (episode / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return episode


def _database(path: Path, episodes: list[tuple[str, Path, int, str, int]]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE datasets(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE sessions(id TEXT PRIMARY KEY, dataset_id INTEGER);
        CREATE TABLE episodes(
          id INTEGER PRIMARY KEY,
          session_id TEXT,
          episode_uuid TEXT,
          path TEXT,
          task TEXT,
          auto_success INTEGER,
          qa_status TEXT,
          num_frames INTEGER
        );
        INSERT INTO datasets(id, name) VALUES (1, 'test_dataset');
        INSERT INTO sessions(id, dataset_id) VALUES ('session', 1);
        """
    )
    connection.executemany(
        """
        INSERT INTO episodes(
          id, session_id, episode_uuid, path, task, auto_success, qa_status, num_frames
        ) VALUES (?, 'session', ?, ?, 'maniskill.pick_cube_native', ?, ?, 4)
        """,
        [
            (index, uuid, str(episode), auto_success, qa_status)
            for index, (uuid, episode, auto_success, qa_status, _seed) in enumerate(
                episodes, start=1
            )
        ],
    )
    connection.commit()
    connection.close()


class DatasetTest(unittest.TestCase):
    def test_only_accepted_successful_episodes_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = _write_episode(
                root, "accepted", 11, seed_semantics="maniskill_source_episode_seed"
            )
            rejected = _write_episode(
                root, "rejected", 12, seed_semantics="maniskill_source_episode_seed"
            )
            db = root / "studio.db"
            _database(
                db,
                [
                    ("accepted", accepted, 1, "accepted", 11),
                    ("rejected", rejected, 1, "rejected", 12),
                ],
            )
            records = load_accepted_pickcube_episodes(
                db, "test_dataset", expected_count=1
            )
            self.assertEqual([record.episode_uuid for record in records], ["accepted"])

    def test_incomplete_seed_semantics_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode = _write_episode(root, "bad", 11, seed_semantics="incrementing")
            db = root / "studio.db"
            _database(db, [("bad", episode, 1, "accepted", 11)])
            with self.assertRaisesRegex(ValueError, "seed semantics"):
                load_accepted_pickcube_episodes(db, "test_dataset")

    def test_episode_split_chunk_mask_and_train_only_normalizer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries: list[tuple[str, Path, int, str, int]] = []
            for seed in range(1, 5):
                episode = _write_episode(
                    root,
                    f"episode-{seed}",
                    seed,
                    seed_semantics="maniskill_source_episode_seed",
                )
                entries.append((f"episode-{seed}", episode, 1, "accepted", seed))
            db = root / "studio.db"
            _database(db, entries)
            records = load_accepted_pickcube_episodes(
                db, "test_dataset", expected_count=4
            )
            train, validation = split_episodes(
                records, train_count=3, validation_count=1, split_seed=7
            )
            self.assertFalse(
                {record.seed for record in train}
                & {record.seed for record in validation}
            )
            dataset = StateActionChunkDataset(train, action_horizon=3)
            first = dataset[0]
            self.assertAlmostEqual(float(first["action"][0, 0]), 0.0)
            self.assertAlmostEqual(
                float(first["observation"][0]), train[0].seed / 100.0 - 0.01
            )
            last = dataset[len(dataset) - 1]
            self.assertEqual(last["observation"].shape, (OBSERVATION_DIM,))
            self.assertEqual(last["action"].shape, (3, 8))
            self.assertEqual(last["action_mask"].tolist(), [1.0, 0.0, 0.0])
            self.assertLessEqual(float(last["action"].abs().max()), 1.0)
            normalizer = fit_observation_normalizer(dataset)
            self.assertEqual(normalizer.mean.shape, (OBSERVATION_DIM,))
            expected_joint_mean = np.mean(
                [record.seed / 100.0 - 0.01 for record in train]
            )
            self.assertAlmostEqual(float(normalizer.mean[0]), expected_joint_mean)

    def test_legacy_post_action_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode = _write_episode(
                root, "legacy", 11, seed_semantics="maniskill_source_episode_seed"
            )
            manifest_path = episode / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["scene"]["parameters"]["native_payload_schema"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            db = root / "studio.db"
            _database(db, [("legacy", episode, 1, "accepted", 11)])
            with self.assertRaisesRegex(ValueError, "legacy native payload"):
                load_accepted_pickcube_episodes(db, "test_dataset")


if __name__ == "__main__":
    unittest.main()
