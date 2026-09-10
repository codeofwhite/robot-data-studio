from __future__ import annotations

import numpy as np

from consumers.openpi_franka_joint8.evaluate_m5b_alignment import (
    event_frames,
    first_closed_offset,
    selected_attempt_episode_indices,
    summarize,
)


def test_event_frames_are_relative_to_physical_phase_boundaries() -> None:
    phases = np.asarray([0] * 8 + [1] * 3 + [2] * 4 + [3] * 2, dtype=np.int8)
    actions = np.zeros((len(phases), 8), dtype=np.float32)
    actions[:10, 7] = 0.08
    assert event_frames(phases, actions) == {
        "approach_minus_5": 5,
        "approach_minus_2": 8,
        "close": 10,
        "close_plus_2": 12,
        "grasp": 11,
        "lift": 15,
    }


def test_selected_attempts_follow_export_episode_order() -> None:
    report = {
        "variants": {
            "human5_generated_success": {
                "episodes": [
                    {"path": "human"},
                    {"attempt_id": "a"},
                    {"attempt_id": "b"},
                ]
            }
        }
    }
    assert selected_attempt_episode_indices(report, {"b"}) == {"b": 2}


def test_first_closed_offset_reports_position_inside_action_chunk() -> None:
    assert first_closed_offset(np.asarray([0.0, 0.2, 0.8, 1.0])) == 2
    assert first_closed_offset(np.asarray([0.0, 0.2])) is None


def test_summarize_reports_joint_and_gripper_events() -> None:
    records = [
        {
            "joint_first_abs_error_rad": np.full(7, 0.02),
            "target_closed": True,
            "predicted_closed": True,
            "target_gripper": 1.0,
            "predicted_gripper": 0.8,
            "target_first_close_offset_frames": 0,
            "predicted_first_close_offset_frames": 0,
        },
        {
            "joint_first_abs_error_rad": np.full(7, 0.04),
            "target_closed": False,
            "predicted_closed": False,
            "target_gripper": 0.0,
            "predicted_gripper": 0.1,
            "target_first_close_offset_frames": 3,
            "predicted_first_close_offset_frames": 1,
        },
    ]
    result = summarize(records)
    assert np.isclose(result["joint_first_step_mae_rad"], 0.03)
    assert result["close_recall"] == 1.0
    assert result["open_specificity"] == 1.0
    assert result["median_close_offset_error_frames"] == -1.0
    assert result["early_close_rate_among_comparable_chunks"] == 0.5
