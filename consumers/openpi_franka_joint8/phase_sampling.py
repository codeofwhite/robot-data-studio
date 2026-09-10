"""Deterministic event-aware sampling for Franka grasp/lift demonstrations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import numpy as np
import torch


PHASES = (
    "approach_open",
    "close_transition",
    "closed_transport",
    "release_transition",
    "post_release",
)

DEFAULT_PHASE_PROBABILITIES = {
    "approach_open": 0.25,
    "close_transition": 0.20,
    "closed_transport": 0.25,
    "release_transition": 0.20,
    "post_release": 0.10,
}

GRIPPER_EVENT_PHASES = (
    "approach_open",
    "preclose_open",
    "close_command",
    "closed_transport",
    "release_transition",
    "post_release",
)

GRIPPER_EVENT_PROBABILITIES = {
    "approach_open": 0.10,
    "preclose_open": 0.30,
    "close_command": 0.25,
    "closed_transport": 0.20,
    "release_transition": 0.10,
    "post_release": 0.05,
}


def assign_phases(
    episode_indices: np.ndarray,
    frame_indices: np.ndarray,
    gripper_targets: np.ndarray,
    *,
    transition_radius: int = 2,
) -> np.ndarray:
    """Label each frame from the episode's first close and later release."""
    episode_indices = np.asarray(episode_indices)
    frame_indices = np.asarray(frame_indices)
    gripper_targets = np.asarray(gripper_targets)
    if not (len(episode_indices) == len(frame_indices) == len(gripper_targets)):
        raise ValueError("phase inputs must have matching lengths")
    if transition_radius < 0:
        raise ValueError("transition_radius must be non-negative")

    phases = np.empty(len(gripper_targets), dtype=object)
    for episode in np.unique(episode_indices):
        rows = np.flatnonzero(episode_indices == episode)
        order = rows[np.argsort(frame_indices[rows])]
        closed = gripper_targets[order] >= 0.5
        close_candidates = np.flatnonzero(closed)
        if not len(close_candidates):
            raise ValueError(f"episode {int(episode)} has no close event")
        close_at = int(close_candidates[0])
        release_candidates = np.flatnonzero((~closed) & (np.arange(len(order)) > close_at))
        if not len(release_candidates):
            raise ValueError(f"episode {int(episode)} has no release after close")
        release_at = int(release_candidates[0])
        for local_index, row in enumerate(order):
            if abs(local_index - close_at) <= transition_radius:
                phase = "close_transition"
            elif abs(local_index - release_at) <= transition_radius:
                phase = "release_transition"
            elif local_index < close_at:
                phase = "approach_open"
            elif local_index < release_at:
                phase = "closed_transport"
            else:
                phase = "post_release"
            phases[row] = phase
    return phases


def assign_gripper_event_phases(
    episode_indices: np.ndarray,
    frame_indices: np.ndarray,
    gripper_targets: np.ndarray,
    *,
    preclose_frames: int = 5,
    postclose_frames: int = 2,
    release_radius: int = 2,
) -> np.ndarray:
    """Separate pre-close open labels from the close command and post-close labels."""
    episode_indices = np.asarray(episode_indices)
    frame_indices = np.asarray(frame_indices)
    gripper_targets = np.asarray(gripper_targets)
    if not (len(episode_indices) == len(frame_indices) == len(gripper_targets)):
        raise ValueError("gripper event inputs must have matching lengths")
    if min(preclose_frames, postclose_frames, release_radius) < 0:
        raise ValueError("gripper event window sizes must be non-negative")

    phases = np.empty(len(gripper_targets), dtype=object)
    for episode in np.unique(episode_indices):
        rows = np.flatnonzero(episode_indices == episode)
        order = rows[np.argsort(frame_indices[rows])]
        closed = gripper_targets[order] >= 0.5
        close_candidates = np.flatnonzero(closed)
        if not len(close_candidates):
            raise ValueError(f"episode {int(episode)} has no close event")
        close_at = int(close_candidates[0])
        release_candidates = np.flatnonzero((~closed) & (np.arange(len(order)) > close_at))
        if not len(release_candidates):
            raise ValueError(f"episode {int(episode)} has no release after close")
        release_at = int(release_candidates[0])
        for local_index, row in enumerate(order):
            if close_at - preclose_frames <= local_index < close_at:
                phase = "preclose_open"
            elif close_at <= local_index <= close_at + postclose_frames:
                phase = "close_command"
            elif abs(local_index - release_at) <= release_radius:
                phase = "release_transition"
            elif local_index < close_at:
                phase = "approach_open"
            elif local_index < release_at:
                phase = "closed_transport"
            else:
                phase = "post_release"
            phases[row] = phase
    return phases


def validate_phase_probabilities(values: Mapping[str, float]) -> dict[str, float]:
    expected = tuple(values)
    if not expected:
        raise ValueError("phase probabilities cannot be empty")
    result = {phase: float(values[phase]) for phase in expected}
    if any(not np.isfinite(value) or value <= 0 for value in result.values()):
        raise ValueError("phase probabilities must be finite and positive")
    total = sum(result.values())
    if not np.isclose(total, 1.0, atol=1e-8):
        raise ValueError(f"phase probabilities must sum to 1, got {total}")
    return result


def phase_weights(phases: Sequence[str], probabilities: Mapping[str, float]) -> np.ndarray:
    """Return per-row weights whose aggregate phase mass matches the target."""
    targets = validate_phase_probabilities(probabilities)
    counts = Counter(str(phase) for phase in phases)
    unknown = sorted(set(counts) - set(targets))
    if unknown:
        raise ValueError(f"phase probabilities are missing observed phases: {unknown}")
    missing = [phase for phase in targets if counts[phase] == 0]
    if missing:
        raise ValueError(f"cannot phase-balance a dataset missing phases: {missing}")
    return np.asarray([targets[str(phase)] / counts[str(phase)] for phase in phases], dtype=np.float64)


class CountingWeightedSampler(torch.utils.data.Sampler[int]):
    """Seeded weighted sampler that exposes the indices actually requested."""

    def __init__(self, phases: Sequence[str], probabilities: Mapping[str, float], *, seed: int):
        self.phases = np.asarray(phases, dtype=object)
        self.probabilities = validate_phase_probabilities(probabilities)
        self.weights = torch.as_tensor(phase_weights(self.phases, self.probabilities), dtype=torch.double)
        self.generator = torch.Generator().manual_seed(int(seed))
        self.draw_counts: Counter[str] = Counter()

    def __len__(self) -> int:
        return len(self.phases)

    def __iter__(self) -> Iterator[int]:
        indices = torch.multinomial(
            self.weights,
            num_samples=len(self),
            replacement=True,
            generator=self.generator,
        )
        for index in indices.tolist():
            self.draw_counts[str(self.phases[index])] += 1
            yield int(index)

    def report(self) -> dict[str, Any]:
        source = Counter(str(phase) for phase in self.phases)
        draws = sum(self.draw_counts.values())
        phase_names = tuple(self.probabilities)
        return {
            "strategy": "phase_balanced",
            "source_frames": {phase: source[phase] for phase in phase_names},
            "target_probabilities": dict(self.probabilities),
            "observed_draws": {phase: self.draw_counts[phase] for phase in phase_names},
            "observed_probabilities": {
                phase: (self.draw_counts[phase] / draws if draws else None)
                for phase in phase_names
            },
            "total_draws": draws,
        }
