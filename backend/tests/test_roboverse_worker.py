from pathlib import Path

import numpy as np

from robot_data_studio.workers.roboverse import (
    NATIVE_JOINTS,
    _camera_geometry,
    _write_native_payload,
    absolute_native_target,
    extract_native_state,
    successful_demo_keys,
)


class Joint:
    def __init__(self, name: str):
        self._name = name

    def get_name(self) -> str:
        return self._name


class Robot:
    def __init__(self, names: list[str]):
        self.names = names

    def get_active_joints(self):
        return [Joint(name) for name in self.names]

    def get_qpos(self):
        return np.arange(len(self.names), dtype=np.float32) + 10

    def get_qvel(self):
        return np.arange(len(self.names), dtype=np.float32) + 20


class Handler:
    def __init__(self, active_names: list[str], target_names: list[str]):
        self.object_ids = {"panda": Robot(active_names)}
        self.target_names = target_names

    def get_joint_names(self, _robot: str, *, sort: bool):
        assert sort is True
        return self.target_names


class Task:
    def __init__(self):
        active = list(reversed(NATIVE_JOINTS))
        targets = [NATIVE_JOINTS[2], *NATIVE_JOINTS[:2], *NATIVE_JOINTS[3:]]
        self.handler = Handler(active, targets)

    def _targets_from_action(self, _action):
        return np.arange(len(self.handler.target_names), dtype=np.float32)[None, :] + 100


def test_roboverse_joint_values_are_name_aligned() -> None:
    task = Task()
    state = extract_native_state(task)
    targets = absolute_native_target(task, np.zeros(8, dtype=np.float32))

    active_names = list(reversed(NATIVE_JOINTS))
    expected_qpos = [active_names.index(name) + 10 for name in NATIVE_JOINTS]
    expected_qvel = [active_names.index(name) + 20 for name in NATIVE_JOINTS]
    target_names = task.handler.target_names
    expected_targets = [target_names.index(name) + 100 for name in NATIVE_JOINTS]
    np.testing.assert_array_equal(state, np.asarray(expected_qpos + expected_qvel))
    np.testing.assert_array_equal(targets, np.asarray(expected_targets))


def test_successful_demo_selection_is_numeric_and_success_only() -> None:
    action = np.zeros((50, 8), dtype=np.float32)
    demos = {
        "traj_10": {"actions": action, "success": np.asarray([True])},
        "traj_2": {"actions": action, "success": np.asarray([True])},
        "traj_1": {"actions": action, "success": np.asarray([False])},
    }

    assert successful_demo_keys(demos, 2) == ["traj_2", "traj_10"]


def test_camera_intrinsics_match_the_configured_resolution() -> None:
    aperture, intrinsics = _camera_geometry(640, 480)
    assert aperture > 0
    assert intrinsics[0][0] == intrinsics[1][1]
    assert intrinsics[0][2] == 320
    assert intrinsics[1][2] == 240


def test_native_payload_has_matching_sha256(tmp_path: Path) -> None:
    arrays = {"action": [np.zeros(8, dtype=np.float32), np.ones(8, dtype=np.float32)]}
    _write_native_payload(tmp_path, arrays)
    payload = tmp_path / "native_trajectory.npz"
    checksum = (tmp_path / "native_payload.sha256").read_text(encoding="utf-8")
    assert payload.is_file()
    assert checksum.endswith("  native_trajectory.npz\n")
