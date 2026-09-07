from __future__ import annotations

import unittest

from src.route_research_feature_review_v47 import (
    CausalFeatureRowV47,
    FeatureDefinitionV47,
    effect_for_feature_v47,
    grouping_for_feature_v47,
    numeric_grouping_v47,
    validate_feature_clocks_v47,
)


def _row(*, cohort: str, index: int, feature_value, label: float) -> CausalFeatureRowV47:
    run_key = f"run-{cohort}"
    return CausalFeatureRowV47(
        acquisition_run_key=run_key,
        cohort=cohort,
        episode_key=f"episode-{cohort}-{index}",
        token_mint=f"token-{cohort}-{index}",
        episode_t0=100,
        research_decision_as_of=110,
        features={"x": feature_value},
        feature_observed_at={"x": 110},
        labels={300: label, 900: label, 3600: label},
        outcome_statuses={300: "AVAILABLE", 900: "AVAILABLE", 3600: "AVAILABLE"},
    )


class RouteResearchFeatureReviewV47Tests(unittest.TestCase):
    def test_feature_after_decision_is_rejected(self):
        row = CausalFeatureRowV47(
            acquisition_run_key="run-A",
            cohort="A",
            episode_key="episode",
            token_mint="token",
            episode_t0=100,
            research_decision_as_of=110,
            features={"x": 1.0},
            feature_observed_at={"x": 111},
            labels={300: 1.0},
            outcome_statuses={300: "AVAILABLE"},
        )
        with self.assertRaisesRegex(ValueError, "observed after research_decision_as_of"):
            validate_feature_clocks_v47(row)

    def test_numeric_grouping_depends_only_on_feature_values_not_labels(self):
        rows_a = tuple(
            _row(cohort="A" if i < 6 else "B", index=i, feature_value=i, label=float(i))
            for i in range(12)
        )
        rows_b = tuple(
            CausalFeatureRowV47(
                acquisition_run_key=row.acquisition_run_key,
                cohort=row.cohort,
                episode_key=row.episode_key,
                token_mint=row.token_mint,
                episode_t0=row.episode_t0,
                research_decision_as_of=row.research_decision_as_of,
                features=dict(row.features),
                feature_observed_at=dict(row.feature_observed_at),
                labels={300: -1000.0 * float(i + 1)},
                outcome_statuses={300: "AVAILABLE"},
            )
            for i, row in enumerate(rows_a)
        )
        first = numeric_grouping_v47(rows=rows_a, feature_name="x")
        second = numeric_grouping_v47(rows=rows_b, feature_name="x")
        self.assertEqual(first.descriptor, second.descriptor)
        self.assertEqual(first.assignments, second.assignments)

    def test_same_direction_requires_support_in_both_subcohorts(self):
        rows = []
        # Each cohort has five LOW and five HIGH observations. HIGH has a better median in both.
        for cohort in ("A", "B"):
            for i in range(5):
                rows.append(_row(cohort=cohort, index=i, feature_value=0, label=-10.0 + i))
            for i in range(5, 10):
                rows.append(_row(cohort=cohort, index=i, feature_value=1, label=5.0 + i))
        definition = FeatureDefinitionV47("x", "test", "numeric")
        grouping = grouping_for_feature_v47(rows=tuple(rows), definition=definition)
        effect = effect_for_feature_v47(
            rows=tuple(rows),
            definition=definition,
            grouping=grouping,
            horizon_seconds=300,
        )
        self.assertEqual(effect.support_a, (5, 5))
        self.assertEqual(effect.support_b, (5, 5))
        self.assertEqual(effect.classification, "SAME_DIRECTION_DESCRIPTIVE_ONLY")
        self.assertGreater(effect.delta_median_a or 0.0, 0.0)
        self.assertGreater(effect.delta_median_b or 0.0, 0.0)

    def test_disagreement_between_a_and_b_is_unstable(self):
        rows = []
        for i in range(5):
            rows.append(_row(cohort="A", index=i, feature_value=0, label=-10.0))
            rows.append(_row(cohort="A", index=i + 5, feature_value=1, label=10.0))
            rows.append(_row(cohort="B", index=i, feature_value=0, label=10.0))
            rows.append(_row(cohort="B", index=i + 5, feature_value=1, label=-10.0))
        definition = FeatureDefinitionV47("x", "test", "numeric")
        grouping = grouping_for_feature_v47(rows=tuple(rows), definition=definition)
        effect = effect_for_feature_v47(
            rows=tuple(rows),
            definition=definition,
            grouping=grouping,
            horizon_seconds=300,
        )
        self.assertEqual(effect.classification, "UNSTABLE_ACROSS_SUBCOHORTS")


if __name__ == "__main__":
    unittest.main()
