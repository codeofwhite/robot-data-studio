import numpy as np

from consumers.openpi_franka_joint8.evaluate_val import assign_phases, summarize_errors


def test_assign_phases_uses_close_and_release_per_episode():
    episodes = np.asarray([0] * 10 + [1] * 10)
    frames = np.asarray(list(range(10)) * 2)
    gripper = np.asarray([0, 0, 0, 1, 1, 1, 1, 0, 0, 0] * 2, dtype=np.float32)

    phases = assign_phases(episodes, frames, gripper, transition_radius=1)

    assert phases[:10].tolist() == [
        "approach_open",
        "approach_open",
        "close_transition",
        "close_transition",
        "close_transition",
        "closed_transport",
        "release_transition",
        "release_transition",
        "release_transition",
        "post_release",
    ]
    assert phases[10:].tolist() == phases[:10].tolist()


def test_summarize_errors_reports_joint_and_gripper_metrics():
    records = [
        {
            "joint_first_abs_error": np.full(7, 0.1),
            "gripper_target": 1.0,
            "gripper_prediction": 0.75,
            "chunk_joint_abs_error": np.asarray([0.1, 0.2]),
            "chunk_gripper_abs_error": np.asarray([0.25]),
        },
        {
            "joint_first_abs_error": np.zeros(7),
            "gripper_target": 0.0,
            "gripper_prediction": 0.25,
            "chunk_joint_abs_error": np.asarray([0.0, 0.1]),
            "chunk_gripper_abs_error": np.asarray([0.25]),
        },
    ]

    result = summarize_errors(records)

    assert np.isclose(result["joint_first_step_mae_rad"], 0.05)
    assert np.isclose(result["joint_chunk_mae_rad"], 0.1)
    assert result["gripper_accuracy"] == 1.0
    assert result["close_recall"] == 1.0
    assert result["open_specificity"] == 1.0
