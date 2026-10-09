import unittest

from src.exceptional_trade_case_control_v63 import (
    FrozenOutcomeLabelV63,
    PreEntryMatchCovariatesV63,
    match_exceptional_trade_cases_v63,
)


class ExceptionalTradeCaseControlV63Tests(unittest.TestCase):
    def label(self, key, wallet, label, value=None):
        return FrozenOutcomeLabelV63(
            reference_key=key,
            wallet_address=wallet,
            label=label,
            label_frozen_at=1_000,
            outcome_value=value,
        )

    def cov(self, key, wallet, when, *, strategy="sig", venue="pump", notional="small", age="fresh"):
        return PreEntryMatchCovariatesV63(
            reference_key=key,
            wallet_address=wallet,
            entry_chain_time=when,
            strategy_signature=strategy,
            venue_bucket=venue,
            entry_notional_bucket=notional,
            market_age_bucket=age,
        )

    def test_outcome_magnitude_does_not_change_pairing(self):
        labels_a = [
            self.label("case", "w", "case", 1000.0),
            self.label("control-near", "w", "control", -1.0),
            self.label("control-far", "w", "control", 999999.0),
        ]
        labels_b = [
            self.label("case", "w", "case", -999999.0),
            self.label("control-near", "w", "control", 999999.0),
            self.label("control-far", "w", "control", -1.0),
        ]
        covariates = [
            self.cov("case", "w", 100),
            self.cov("control-near", "w", 105),
            self.cov("control-far", "w", 500),
        ]
        first = match_exceptional_trade_cases_v63(
            outcome_labels=labels_a,
            preentry_covariates=covariates,
        )
        second = match_exceptional_trade_cases_v63(
            outcome_labels=labels_b,
            preentry_covariates=covariates,
        )
        self.assertEqual(first.pairs, second.pairs)
        self.assertEqual(first.pairs[0].control_reference_key, "control-near")

    def test_cross_wallet_control_is_never_used(self):
        result = match_exceptional_trade_cases_v63(
            outcome_labels=[
                self.label("case", "wallet-a", "case"),
                self.label("control", "wallet-b", "control"),
            ],
            preentry_covariates=[
                self.cov("case", "wallet-a", 100),
                self.cov("control", "wallet-b", 101),
            ],
        )
        self.assertEqual(result.matched_pair_count, 0)
        self.assertEqual(result.unmatched_case_reference_keys, ("case",))

    def test_no_relaxation_when_exact_preentry_stratum_differs(self):
        result = match_exceptional_trade_cases_v63(
            outcome_labels=[
                self.label("case", "w", "case"),
                self.label("control", "w", "control"),
            ],
            preentry_covariates=[
                self.cov("case", "w", 100, age="fresh"),
                self.cov("control", "w", 101, age="established"),
            ],
        )
        self.assertEqual(result.matched_pair_count, 0)
        self.assertEqual(result.unused_control_reference_keys, ("control",))

    def test_control_is_used_at_most_once(self):
        result = match_exceptional_trade_cases_v63(
            outcome_labels=[
                self.label("case-a", "w", "case"),
                self.label("case-b", "w", "case"),
                self.label("control", "w", "control"),
            ],
            preentry_covariates=[
                self.cov("case-a", "w", 100),
                self.cov("case-b", "w", 110),
                self.cov("control", "w", 105),
            ],
        )
        self.assertEqual(result.matched_pair_count, 1)
        self.assertEqual(len(result.unmatched_case_reference_keys), 1)

    def test_label_covariate_wallet_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "wallet mismatch"):
            match_exceptional_trade_cases_v63(
                outcome_labels=[self.label("case", "wallet-a", "case")],
                preentry_covariates=[self.cov("case", "wallet-b", 100)],
            )

    def test_every_labeled_reference_requires_preentry_covariates(self):
        with self.assertRaisesRegex(ValueError, "every labeled reference"):
            match_exceptional_trade_cases_v63(
                outcome_labels=[self.label("case", "w", "case")],
                preentry_covariates=[],
            )


if __name__ == "__main__":
    unittest.main()
