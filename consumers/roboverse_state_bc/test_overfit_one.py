from __future__ import annotations

import unittest

import torch

from .overfit_one import action_error_metrics, diagnostic_gate_passed


class OverfitGateTest(unittest.TestCase):
    def test_gate_uses_non_saturated_mse_and_three_closed_loop_successes(self) -> None:
        target = torch.tensor([[[1.0, 0.25], [-1.0, -0.25]]])
        prediction = target.clone()
        prediction[..., 0] += 0.01
        prediction[..., 1] += 5e-4
        mask = torch.ones((1, 2))

        metrics = action_error_metrics(prediction, target, mask)

        self.assertGreater(float(metrics["overall_mse"]), 1e-6)
        self.assertLessEqual(float(metrics["non_saturated_mse"]), 1e-6)
        self.assertTrue(
            diagnostic_gate_passed(
                metrics, target_mse=1e-6, successes=3, rollouts=3
            )
        )
        self.assertFalse(
            diagnostic_gate_passed(
                metrics, target_mse=1e-6, successes=2, rollouts=3
            )
        )

    def test_gate_rejects_large_non_saturated_error(self) -> None:
        target = torch.tensor([[[1.0, 0.25]]])
        prediction = torch.tensor([[[1.0, 0.252]]])
        metrics = action_error_metrics(prediction, target, torch.ones((1, 1)))

        self.assertGreater(float(metrics["non_saturated_mse"]), 1e-6)
        self.assertFalse(
            diagnostic_gate_passed(
                metrics, target_mse=1e-6, successes=3, rollouts=3
            )
        )


if __name__ == "__main__":
    unittest.main()
