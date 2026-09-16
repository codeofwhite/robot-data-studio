from __future__ import annotations

import unittest

import torch

from .model import StateActionChunkMLP


class ModelTest(unittest.TestCase):
    def test_model_outputs_bounded_action_chunks(self) -> None:
        model = StateActionChunkMLP(action_horizon=8, hidden_dim=32, hidden_layers=2)
        output = model(torch.randn(4, 28))
        self.assertEqual(output.shape, (4, 8, 8))
        self.assertLessEqual(float(output.detach().max()), 1.0)
        self.assertGreaterEqual(float(output.detach().min()), -1.0)

    def test_wrong_observation_dimension_is_rejected(self) -> None:
        model = StateActionChunkMLP()
        with self.assertRaisesRegex(ValueError, "expected 28"):
            model(torch.randn(2, 27))


if __name__ == "__main__":
    unittest.main()
