import numpy as np
import pytest

from consumers.openpi_franka_joint8.pilot_check import (
    validate_episode_actions,
    validate_provenance,
)


def test_validate_episode_actions_requires_open_close_release() -> None:
    actions = np.zeros((12, 8), dtype=np.float32)
    actions[3:9, 7] = 1.0

    assert validate_episode_actions(actions) == {
        "frames": 12,
        "approach_frames": 3,
        "closed_frames": 6,
        "post_release_frames": 3,
    }

    with pytest.raises(ValueError, match="no gripper close"):
        validate_episode_actions(np.zeros((12, 8), dtype=np.float32))
    with pytest.raises(ValueError, match="no release"):
        no_release = np.zeros((12, 8), dtype=np.float32)
        no_release[2:, 7] = 1.0
        validate_episode_actions(no_release)


def test_validate_provenance_requires_isaac_cube_lift_success() -> None:
    rows = [
        {
            "source_episode_uuid": "episode-1",
            "engine_id": "isaac_sim",
            "scene_id": "rigid_cube_lift",
            "operator_success": True,
            "automatic_success": True,
            "evaluator_id": "isaac_cube_lift_v1",
        }
    ]

    assert validate_provenance(rows, 1)["validated_successes"] == 1

    with pytest.raises(ValueError, match="automatic success"):
        validate_provenance([{**rows[0], "automatic_success": False}], 1)
    with pytest.raises(ValueError, match="requires only isaac_sim"):
        validate_provenance([{**rows[0], "engine_id": "genesis"}], 1)
