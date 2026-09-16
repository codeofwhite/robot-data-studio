from __future__ import annotations

import torch
from torch import nn

from .dataset import ACTION_DIM, OBSERVATION_DIM


class StateActionChunkMLP(nn.Module):
    def __init__(
        self,
        *,
        observation_dim: int = OBSERVATION_DIM,
        action_dim: int = ACTION_DIM,
        action_horizon: int = 8,
        hidden_dim: int = 256,
        hidden_layers: int = 3,
    ) -> None:
        super().__init__()
        if observation_dim <= 0 or action_dim <= 0 or action_horizon <= 0:
            raise ValueError("model dimensions must be positive")
        if hidden_dim <= 0 or hidden_layers <= 0:
            raise ValueError("hidden dimensions must be positive")
        self.observation_dim = observation_dim
        self.action_dim = action_dim
        self.action_horizon = action_horizon
        self.hidden_dim = hidden_dim
        self.hidden_layers = hidden_layers

        layers: list[nn.Module] = []
        input_dim = observation_dim
        for _ in range(hidden_layers):
            layers.extend(
                (
                    nn.Linear(input_dim, hidden_dim),
                    nn.LayerNorm(hidden_dim),
                    nn.GELU(),
                )
            )
            input_dim = hidden_dim
        layers.extend((nn.Linear(input_dim, action_horizon * action_dim), nn.Tanh()))
        self.network = nn.Sequential(*layers)

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        if observation.shape[-1] != self.observation_dim:
            raise ValueError(
                f"observation has dimension {observation.shape[-1]}, "
                f"expected {self.observation_dim}"
            )
        output = self.network(observation)
        return output.reshape(*observation.shape[:-1], self.action_horizon, self.action_dim)

    def configuration(self) -> dict[str, int]:
        return {
            "observation_dim": self.observation_dim,
            "action_dim": self.action_dim,
            "action_horizon": self.action_horizon,
            "hidden_dim": self.hidden_dim,
            "hidden_layers": self.hidden_layers,
        }
