import unittest
from dataclasses import asdict, replace

from src.wallet_placebo_matching import (
    build_placebo_match_diagnostic,
    rank_placebo_candidates,
    select_disjoint_placebo_addresses,
)
from src.wallet_strategy_lab import WalletStrategyFingerprint


def fingerprint(address: str, **changes) -> WalletStrategyFingerprint:
    item = WalletStrategyFingerprint(
        address=address,
        swap_count=100,
        token_count=20,
        observed_span_days=30.0,
        sample_grade="DEVELOPING",
        swaps_per_day=3.3,
        frequency_rate_per_day=4.0,
        frequency_basis="median_active_day_swaps",
        holding_bucket="intraday",
        exit_bucket="mixed_exit",
        reentry_bucket="rare_reentry",
        frequency_bucket="moderate",
        median_first_exit_seconds=3_600.0,
        roundtrip_share_pct=70.0,
        scale_in_share_pct=10.0,
        multi_sell_share_pct=30.0,
        reentry_share_pct=10.0,
        complete_like_sizing_count=10,
        complete_multi_sell_count=3,
        median_complete_multi_first_sell_fraction_pct=50.0,
        median_complete_multi_runner_pct=50.0,
        dominant_dex="Jupiter",
        dominant_dex_share_pct=60.0,
        signature="intraday|mixed_exit|rare_reentry|moderate",
        flags=(),
    )
    return replace(item, **changes)


class WalletPlaceboMatchingTests(unittest.TestCase):
    def test_diagnostic_uses_behavioral_covariates_not_profitability(self):
        diagnostic = build_placebo_match_diagnostic(
            fingerprint("TARGET"),
            fingerprint(
                "CANDIDATE",
                frequency_rate_per_day=8.0,
                token_count=10,
                observed_span_days=15.0,
                median_first_exit_seconds=7_200.0,
                roundtrip_share_pct=60.0,
            ),
        )

        self.assertEqual(diagnostic.comparable_dimensions, 4)
        self.assertEqual(diagnostic.bucket_similarity_pct, 100.0)
        self.assertAlmostEqual(diagnostic.active_day_rate_ratio, 2.0)
        self.assertAlmostEqual(diagnostic.token_breadth_ratio, 2.0)
        self.assertAlmostEqual(diagnostic.observed_span_ratio, 2.0)
        self.assertAlmostEqual(diagnostic.first_exit_ratio, 2.0)
        self.assertAlmostEqual(diagnostic.roundtrip_abs_diff_pct, 10.0)
        self.assertTrue(diagnostic.dominant_dex_match)
        keys = set(asdict(diagnostic))
        self.assertNotIn("pnl", keys)
        self.assertNotIn("profit", keys)
        self.assertNotIn("roi", keys)
        self.assertNotIn("score", keys)

    def test_candidate_evidence_gap_is_visible_and_ranked_after_ready_candidate(self):
        target = fingerprint("TARGET")
        low_coverage = fingerprint(
            "LOW",
            token_count=5,
            flags=("strategy_token_sample_too_small",),
        )
        ready_but_less_similar = fingerprint(
            "READY",
            holding_bucket="one_day",
            signature="one_day|mixed_exit|rare_reentry|moderate",
        )

        ranked = rank_placebo_candidates(target, [low_coverage, ready_but_less_similar])

        self.assertEqual(ranked[0].candidate_address, "READY")
        self.assertEqual(ranked[1].candidate_address, "LOW")
        self.assertIn("candidate_evidence_not_ready", ranked[1].warnings)
        self.assertIn("candidate_token_sample_narrow", ranked[1].warnings)

    def test_matching_does_not_reuse_target_or_duplicate_candidates(self):
        target = fingerprint("TARGET")
        candidate = fingerprint("CANDIDATE")
        ranked = rank_placebo_candidates(
            target,
            [target, candidate, candidate],
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].candidate_address, "CANDIDATE")
        with self.assertRaises(ValueError):
            build_placebo_match_diagnostic(target, target)

    def test_require_ready_filters_descriptive_only_candidates(self):
        target = fingerprint("TARGET")
        ready = fingerprint("READY")
        weak = fingerprint(
            "WEAK",
            roundtrip_share_pct=30.0,
            flags=("sequence_coverage_low",),
        )

        ranked = rank_placebo_candidates(
            target,
            [weak, ready],
            require_evidence_ready=True,
        )

        self.assertEqual([item.candidate_address for item in ranked], ["READY"])

    def test_select_disjoint_placebos_fails_closed_when_universe_is_too_small(self):
        target = fingerprint("TARGET")
        ranked = rank_placebo_candidates(
            target,
            [fingerprint("A"), fingerprint("B")],
        )

        self.assertEqual(
            select_disjoint_placebo_addresses(ranked, count=2),
            ("A", "B"),
        )
        with self.assertRaises(ValueError):
            select_disjoint_placebo_addresses(ranked, count=3)

    def test_uncomparable_fields_are_not_silently_imputed(self):
        target = fingerprint("TARGET", median_first_exit_seconds=None)
        candidate = fingerprint(
            "CANDIDATE",
            frequency_rate_per_day=0.0,
            dominant_dex=None,
        )

        diagnostic = build_placebo_match_diagnostic(target, candidate)

        self.assertIsNone(diagnostic.active_day_rate_ratio)
        self.assertIsNone(diagnostic.first_exit_ratio)
        self.assertIsNone(diagnostic.dominant_dex_match)
        self.assertIn("activity_rate_uncomparable", diagnostic.warnings)
        self.assertIn("holding_time_uncomparable", diagnostic.warnings)
        self.assertIn("dominant_dex_unavailable", diagnostic.warnings)


if __name__ == "__main__":
    unittest.main()
