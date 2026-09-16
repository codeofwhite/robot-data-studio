from __future__ import annotations

import unittest

from .evaluate_maniskill import classify_failure, paired_exact_greater, wilson_interval


class EvaluationTest(unittest.TestCase):
    def test_failure_breakdown(self) -> None:
        self.assertEqual(
            classify_failure(
                success=False,
                ever_grasped=False,
                ever_placed=False,
                final_placed=False,
                final_static=True,
            ),
            "never_grasped",
        )
        self.assertEqual(
            classify_failure(
                success=False,
                ever_grasped=True,
                ever_placed=False,
                final_placed=False,
                final_static=True,
            ),
            "grasped_but_not_placed",
        )
        self.assertEqual(
            classify_failure(
                success=False,
                ever_grasped=True,
                ever_placed=True,
                final_placed=True,
                final_static=False,
            ),
            "placed_but_not_static",
        )
        self.assertIsNone(
            classify_failure(
                success=True,
                ever_grasped=True,
                ever_placed=True,
                final_placed=True,
                final_static=True,
            )
        )

    def test_paired_exact_gate_statistics(self) -> None:
        comparison = paired_exact_greater([True] * 10 + [False] * 10, [False] * 20)
        self.assertEqual(comparison["policy_only_successes"], 10)
        self.assertLess(comparison["one_sided_exact_p_value"], 0.05)
        low, high = wilson_interval(10, 20)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)


if __name__ == "__main__":
    unittest.main()
