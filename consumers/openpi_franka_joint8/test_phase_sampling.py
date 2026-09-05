import numpy as np

from consumers.openpi_franka_joint8.phase_sampling import (
    DEFAULT_PHASE_PROBABILITIES,
    PHASES,
    CountingWeightedSampler,
    assign_phases,
    phase_weights,
)


def test_phase_weights_assign_requested_mass_to_each_phase():
    phases = np.asarray(
        ["approach_open"] * 50
        + ["close_transition"] * 5
        + ["closed_transport"] * 30
        + ["release_transition"] * 5
        + ["post_release"] * 10,
        dtype=object,
    )
    weights = phase_weights(phases, DEFAULT_PHASE_PROBABILITIES)

    for phase in PHASES:
        assert np.isclose(weights[phases == phase].sum(), DEFAULT_PHASE_PROBABILITIES[phase])


def test_counting_sampler_is_seeded_and_tracks_draws():
    phases = np.asarray(list(PHASES) * 100, dtype=object)
    first = CountingWeightedSampler(phases, DEFAULT_PHASE_PROBABILITIES, seed=7)
    second = CountingWeightedSampler(phases, DEFAULT_PHASE_PROBABILITIES, seed=7)

    assert list(first) == list(second)
    report = first.report()
    assert report["total_draws"] == len(phases)
    assert sum(report["observed_draws"].values()) == len(phases)


def test_assign_phases_rejects_missing_release():
    try:
        assign_phases(
            np.zeros(4, dtype=np.int64),
            np.arange(4),
            np.asarray([0.0, 1.0, 1.0, 1.0]),
        )
    except ValueError as exc:
        assert "no release" in str(exc)
    else:
        raise AssertionError("expected missing release to fail")
