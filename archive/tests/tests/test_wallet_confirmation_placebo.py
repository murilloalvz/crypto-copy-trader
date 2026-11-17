import unittest

from src.opportunity_intelligence import WalletActionObservation
from src.wallet_confirmation_placebo import (
    ConfirmationPolicy,
    TokenOutcomeObservation,
    WalletCohort,
    build_wallet_confirmation_event,
    compare_target_to_placebos,
    validate_cohort_design,
)


class WalletConfirmationPlaceboTests(unittest.TestCase):
    def setUp(self):
        self.target = WalletCohort("smart", ("A", "B"), "target")
        self.placebo = WalletCohort("placebo_1", ("C", "D"), "placebo")
        self.policy = ConfirmationPolicy(window_seconds=300, min_unique_buy_wallets=2)

    def test_confirmation_uses_observed_at_and_excludes_future_observations(self):
        observations = [
            WalletActionObservation("A", "T", "buy", chain_time=100, observed_at=150),
            WalletActionObservation("B", "T", "buy", chain_time=120, observed_at=400),
        ]

        early = build_wallet_confirmation_event(
            observations,
            token_mint="T",
            as_of=300,
            cohort=self.target,
            policy=self.policy,
        )
        later = build_wallet_confirmation_event(
            observations,
            token_mint="T",
            as_of=450,
            cohort=self.target,
            policy=self.policy,
        )

        self.assertFalse(early.confirmed)
        self.assertEqual(early.unique_buy_wallet_count, 1)
        self.assertTrue(later.confirmed)
        self.assertEqual(later.unique_buy_wallet_count, 2)

    def test_old_observation_outside_window_does_not_confirm(self):
        observations = [
            WalletActionObservation("A", "T", "buy", 100, 120),
            WalletActionObservation("B", "T", "buy", 110, 130),
        ]
        event = build_wallet_confirmation_event(
            observations,
            token_mint="T",
            as_of=1_000,
            cohort=self.target,
            policy=self.policy,
        )
        self.assertFalse(event.confirmed)
        self.assertEqual(event.buy_action_count, 0)

    def test_cohorts_must_be_disjoint_and_equal_size_by_default(self):
        validate_cohort_design(self.target, [self.placebo])

        with self.assertRaises(ValueError):
            validate_cohort_design(
                self.target,
                [WalletCohort("overlap", ("B", "C"), "placebo")],
            )
        with self.assertRaises(ValueError):
            validate_cohort_design(
                self.target,
                [WalletCohort("small", ("C",), "placebo")],
            )

    def test_placebo_comparison_keeps_missingness_visible(self):
        observations = [
            WalletActionObservation("A", "T1", "buy", 90, 100),
            WalletActionObservation("B", "T1", "buy", 91, 101),
            WalletActionObservation("C", "T2", "buy", 90, 100),
            WalletActionObservation("D", "T2", "buy", 91, 101),
        ]
        events = [
            build_wallet_confirmation_event(
                observations,
                token_mint="T1",
                as_of=150,
                cohort=self.target,
                policy=self.policy,
            ),
            build_wallet_confirmation_event(
                observations,
                token_mint="T2",
                as_of=150,
                cohort=self.placebo,
                policy=self.policy,
            ),
        ]
        outcomes = [
            TokenOutcomeObservation("T1", 150, 15, "completed", 10.0),
            TokenOutcomeObservation("T2", 150, 15, "pending"),
        ]

        comparison = compare_target_to_placebos(
            events,
            outcomes,
            target_cohort_name="smart",
            placebo_cohort_names=("placebo_1",),
            horizon_minutes=15,
        )

        self.assertEqual(comparison.target.completed_count, 1)
        self.assertEqual(comparison.placebos[0].pending_or_missing_count, 1)
        self.assertEqual(comparison.placebos[0].coverage_pct, 0.0)
        self.assertEqual(comparison.interpretation_label, "NO_COMPARABLE_OUTCOMES")
        self.assertIsNone(comparison.target_minus_median_placebo_mean_return_pct)

    def test_comparison_reports_descriptive_increment_not_edge_claim(self):
        observations = [
            WalletActionObservation("A", "T1", "buy", 90, 100),
            WalletActionObservation("B", "T1", "buy", 91, 101),
            WalletActionObservation("C", "T2", "buy", 90, 100),
            WalletActionObservation("D", "T2", "buy", 91, 101),
        ]
        events = [
            build_wallet_confirmation_event(
                observations,
                token_mint="T1",
                as_of=150,
                cohort=self.target,
                policy=self.policy,
            ),
            build_wallet_confirmation_event(
                observations,
                token_mint="T2",
                as_of=150,
                cohort=self.placebo,
                policy=self.policy,
            ),
        ]
        outcomes = [
            TokenOutcomeObservation("T1", 150, 15, "completed", 12.0),
            TokenOutcomeObservation("T2", 150, 15, "completed", 2.0),
        ]

        comparison = compare_target_to_placebos(
            events,
            outcomes,
            target_cohort_name="smart",
            placebo_cohort_names=("placebo_1",),
            horizon_minutes=15,
        )

        self.assertEqual(
            comparison.interpretation_label,
            "DESCRIPTIVE_PLACEBO_COMPARISON",
        )
        self.assertAlmostEqual(
            comparison.target_minus_median_placebo_mean_return_pct,
            10.0,
        )
        self.assertFalse(hasattr(comparison, "edge_proven"))


if __name__ == "__main__":
    unittest.main()
