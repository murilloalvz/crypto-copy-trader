from __future__ import annotations

import math
import unittest

from src.route_research_feature_review_v47 import CausalFeatureRowV47, GroupingV47
from src.route_research_feature_robustness_v47 import (
    group_label_values_v47,
    robust_return_metrics_v47,
)


def _row(*, cohort: str, index: int, group: str, label: float | None) -> CausalFeatureRowV47:
    run_key = f"run-{cohort}"
    return CausalFeatureRowV47(
        acquisition_run_key=run_key,
        cohort=cohort,
        episode_key=f"episode-{cohort}-{index}",
        token_mint=f"token-{cohort}-{index}",
        episode_t0=100,
        research_decision_as_of=110,
        features={"x": group},
        feature_observed_at={"x": 110},
        labels={300: label},
        outcome_statuses={300: "AVAILABLE" if label is not None else "MISSING"},
    )


class RouteResearchFeatureRobustnessV47Tests(unittest.TestCase):
    def test_robust_metrics_expose_heavy_tail_concentration(self):
        metrics = robust_return_metrics_v47([-10.0, -5.0, 5.0, 100.0])
        self.assertEqual(metrics.n, 4)
        self.assertAlmostEqual(metrics.positive_share_pct or 0.0, 50.0)
        self.assertAlmostEqual(metrics.mean_return_pct or 0.0, 22.5)
        self.assertAlmostEqual(metrics.median_return_pct or 0.0, 0.0)
        self.assertAlmostEqual(metrics.profit_factor or 0.0, 7.0)
        self.assertAlmostEqual(metrics.best_return_pct or 0.0, 100.0)
        self.assertAlmostEqual(metrics.worst_return_pct or 0.0, -10.0)
        self.assertAlmostEqual(metrics.mean_without_best_pct or 0.0, -10.0 / 3.0)
        self.assertAlmostEqual(
            metrics.largest_winner_share_gross_profit_pct or 0.0,
            100.0 * 100.0 / 105.0,
        )

    def test_all_losses_have_zero_winner_concentration_and_zero_pf(self):
        metrics = robust_return_metrics_v47([-2.0, -1.0])
        self.assertEqual(metrics.profit_factor, 0.0)
        self.assertEqual(metrics.largest_winner_share_gross_profit_pct, 0.0)
        self.assertAlmostEqual(metrics.mean_without_best_pct or 0.0, -2.0)

    def test_single_value_has_no_mean_without_best(self):
        metrics = robust_return_metrics_v47([3.0])
        self.assertTrue(math.isinf(metrics.profit_factor or 0.0))
        self.assertIsNone(metrics.mean_without_best_pct)
        self.assertEqual(metrics.largest_winner_share_gross_profit_pct, 100.0)

    def test_group_values_respect_scope_group_and_missing_labels(self):
        rows = (
            _row(cohort="A", index=1, group="LOW", label=-2.0),
            _row(cohort="A", index=2, group="HIGH", label=4.0),
            _row(cohort="B", index=1, group="LOW", label=-3.0),
            _row(cohort="B", index=2, group="HIGH", label=None),
        )
        grouping = GroupingV47(
            feature_name="x",
            descriptor="test",
            assignments={
                (row.acquisition_run_key, row.episode_key): str(row.features["x"])
                for row in rows
            },
            ordered_groups=("LOW", "HIGH"),
        )
        self.assertEqual(
            group_label_values_v47(
                rows=rows,
                grouping=grouping,
                horizon_seconds=300,
                scope="A",
                group="HIGH",
            ),
            [4.0],
        )
        self.assertEqual(
            group_label_values_v47(
                rows=rows,
                grouping=grouping,
                horizon_seconds=300,
                scope="ALL",
                group="LOW",
            ),
            [-2.0, -3.0],
        )
        self.assertEqual(
            group_label_values_v47(
                rows=rows,
                grouping=grouping,
                horizon_seconds=300,
                scope="B",
                group="HIGH",
            ),
            [],
        )

    def test_nonfinite_return_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            robust_return_metrics_v47([1.0, float("nan")])


if __name__ == "__main__":
    unittest.main()
