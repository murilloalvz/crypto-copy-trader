from __future__ import annotations

import unittest

from src.route_research_feature_review_v47 import CausalFeatureRowV47
from src.route_research_prospective_holdout_v48 import (
    frozen_flow60_group_v48,
    group_metrics_v48,
    primary_gate_v48,
)


def _row(*, cohort: str, index: int, flow60, label_900: float) -> CausalFeatureRowV47:
    return CausalFeatureRowV47(
        acquisition_run_key=f"fresh-v48-{cohort}",
        cohort=cohort,
        episode_key=f"episode-{cohort}-{index}",
        token_mint=f"token-{cohort}-{index}",
        episode_t0=100,
        research_decision_as_of=110,
        features={"flow60_event_count": flow60},
        feature_observed_at={"flow60_event_count": 110},
        labels={300: label_900, 900: label_900, 3600: label_900},
        outcome_statuses={300: "AVAILABLE", 900: "AVAILABLE", 3600: "AVAILABLE"},
    )


def _passing_rows() -> tuple[CausalFeatureRowV47, ...]:
    rows = []
    for cohort in ("A", "B"):
        for i, label in enumerate((1.0, 2.0, 3.0, 4.0, 20.0)):
            rows.append(_row(cohort=cohort, index=i, flow60=20, label_900=label))
        for j, label in enumerate((-10.0, -8.0, -5.0, 1.0, 2.0), start=10):
            rows.append(_row(cohort=cohort, index=j, flow60=60, label_900=label))
        rows.append(_row(cohort=cohort, index=30, flow60=35, label_900=0.5))
    return tuple(rows)


class RouteResearchProspectiveHoldoutV48Tests(unittest.TestCase):
    def test_frozen_bins_are_exact_and_not_data_derived(self):
        self.assertEqual(frozen_flow60_group_v48(0), "LOW")
        self.assertEqual(frozen_flow60_group_v48(25), "LOW")
        self.assertEqual(frozen_flow60_group_v48(26), "MID")
        self.assertEqual(frozen_flow60_group_v48(47), "MID")
        self.assertEqual(frozen_flow60_group_v48(48), "HIGH")
        self.assertEqual(frozen_flow60_group_v48(10_000), "HIGH")

    def test_primary_gate_passes_only_when_frozen_replication_and_economics_pass(self):
        gate = primary_gate_v48(rows=_passing_rows())
        self.assertEqual(gate.classification, "PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS")
        self.assertTrue(gate.support_ok)
        self.assertTrue(gate.same_direction_ok)
        self.assertTrue(gate.low_positive_median_both)
        self.assertTrue(gate.low_pf_gt_one_both)
        self.assertTrue(gate.aggregate_low_pf_gt_one)
        self.assertTrue(gate.aggregate_low_mean_without_best_positive)

    def test_primary_gate_is_inconclusive_when_a_frozen_group_has_low_support(self):
        rows = list(_passing_rows())
        removed = False
        filtered = []
        for row in rows:
            if row.cohort == "A" and row.features["flow60_event_count"] > 47 and not removed:
                removed = True
                continue
            filtered.append(row)
        gate = primary_gate_v48(rows=tuple(filtered))
        self.assertEqual(gate.classification, "INCONCLUSIVE_V48_PRIMARY_SUPPORT")
        self.assertFalse(gate.support_ok)

    def test_primary_gate_fails_when_b_does_not_replicate_low_over_high(self):
        rows = [row for row in _passing_rows() if row.cohort == "A"]
        for i, label in enumerate((1.0, 2.0, 3.0, 4.0, 5.0)):
            rows.append(_row(cohort="B", index=i, flow60=20, label_900=label))
        for j, label in enumerate((10.0, 11.0, 12.0, 13.0, 14.0), start=10):
            rows.append(_row(cohort="B", index=j, flow60=60, label_900=label))
        gate = primary_gate_v48(rows=tuple(rows))
        self.assertEqual(gate.classification, "FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS")
        self.assertFalse(gate.same_direction_ok)

    def test_missing_primary_feature_fails_observability(self):
        rows = list(_passing_rows())
        row = rows[0]
        rows[0] = CausalFeatureRowV47(
            acquisition_run_key=row.acquisition_run_key,
            cohort=row.cohort,
            episode_key=row.episode_key,
            token_mint=row.token_mint,
            episode_t0=row.episode_t0,
            research_decision_as_of=row.research_decision_as_of,
            features={"flow60_event_count": None},
            feature_observed_at=row.feature_observed_at,
            labels=row.labels,
            outcome_statuses=row.outcome_statuses,
        )
        gate = primary_gate_v48(rows=tuple(rows))
        self.assertEqual(gate.classification, "FAIL_V48_FEATURE_OBSERVABILITY")
        self.assertLess(gate.feature_known, gate.feature_total)

    def test_mid_is_reported_but_not_needed_for_primary_support(self):
        rows = tuple(row for row in _passing_rows() if row.features["flow60_event_count"] != 35)
        metrics = group_metrics_v48(rows=rows, horizon_seconds=900, scope="ALL")
        self.assertEqual(metrics["MID"].n, 0)
        gate = primary_gate_v48(rows=rows)
        self.assertEqual(gate.classification, "PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS")


if __name__ == "__main__":
    unittest.main()
