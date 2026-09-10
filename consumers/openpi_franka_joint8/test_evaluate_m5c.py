from __future__ import annotations

from consumers.openpi_franka_joint8.evaluate_m5c import build_gates


def _passing_inputs():
    overall = {"joint_first_step_mae_rad": 0.01}
    events = {
        "approach_minus_5": {"open_specificity": 0.8},
        "approach_minus_2": {"open_specificity": 0.9},
        "close": {"close_recall": 0.8},
        "grasp": {"close_recall": 0.95},
        "lift": {"close_recall": 1.0},
    }
    timing = {"median_close_offset_error_frames": -1.0}
    return overall, events, timing


def test_build_gates_accepts_threshold_boundaries() -> None:
    overall, events, timing = _passing_inputs()
    gates = build_gates(overall, events, timing, arm_unchanged=True)
    assert all(gates.values())


def test_build_gates_rejects_early_close_and_open_lift() -> None:
    overall, events, timing = _passing_inputs()
    events["approach_minus_5"]["open_specificity"] = 0.5
    events["lift"]["close_recall"] = 0.75
    gates = build_gates(overall, events, timing, arm_unchanged=True)
    assert not gates["approach_minus_5_open_specificity_at_least_0_8"]
    assert not gates["lift_close_recall_at_least_0_95"]
    assert not gates["passed"]
