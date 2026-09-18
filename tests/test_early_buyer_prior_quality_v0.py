from __future__ import annotations

from pathlib import Path
import unittest

from benchmarks.early_buyer_prior_quality_v0.run import (
    DEFAULT_PROTOCOL,
    FEATURE_ID,
    _decision,
    _history_feature,
    _partial_spearman,
    _read_json,
    _validate_protocol,
)


class EarlyBuyerPriorQualityV0Tests(unittest.TestCase):
    def test_protocol_hash_and_feature_are_frozen(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        _validate_protocol(protocol)
        self.assertEqual(
            protocol["protocol_hash_sha256"],
            "d503f57e2d114d98ecd48f3e491d78410c2f3722a7b0bfe03b15dc1329e0a4e2",
        )
        self.assertEqual(
            protocol["feature_contract"]["primary_feature_id"],
            FEATURE_ID,
        )
        self.assertFalse(protocol["analysis"]["threshold_search_performed"])

    def test_history_is_strictly_pre_t0_excludes_same_second_and_same_token(self):
        current = {
            "run_id": "current",
            "episode_key": "cur",
            "token_mint": "TOKEN",
            "observed_t0": 100,
            "buy_identity_complete": True,
            "buy_wallet_count": 2,
            "buy_wallets": ("A", "B"),
        }
        universe = [
            {
                "run_id": "old",
                "episode_key": "a-good",
                "token_mint": "OLD1",
                "baseline_admitted": True,
                "is_default_sol_quote": True,
                "buy_identity_complete": True,
                "buy_wallets": ("A",),
                "route_status": "ROUTE_CLOSED",
                "current_route_closed_gross_return_pct": 20.0,
                "exit_observed_at": 99,
            },
            {
                "run_id": "old",
                "episode_key": "a-same-second",
                "token_mint": "OLD2",
                "baseline_admitted": True,
                "is_default_sol_quote": True,
                "buy_identity_complete": True,
                "buy_wallets": ("A",),
                "route_status": "ROUTE_CLOSED",
                "current_route_closed_gross_return_pct": 100.0,
                "exit_observed_at": 100,
            },
            {
                "run_id": "old",
                "episode_key": "a-future",
                "token_mint": "OLD3",
                "baseline_admitted": True,
                "is_default_sol_quote": True,
                "buy_identity_complete": True,
                "buy_wallets": ("A",),
                "route_status": "ROUTE_CLOSED",
                "current_route_closed_gross_return_pct": 200.0,
                "exit_observed_at": 101,
            },
            {
                "run_id": "old",
                "episode_key": "same-token",
                "token_mint": "TOKEN",
                "baseline_admitted": True,
                "is_default_sol_quote": True,
                "buy_identity_complete": True,
                "buy_wallets": ("A",),
                "route_status": "ROUTE_CLOSED",
                "current_route_closed_gross_return_pct": 300.0,
                "exit_observed_at": 90,
            },
            {
                "run_id": "old",
                "episode_key": "b-loss",
                "token_mint": "OLD4",
                "baseline_admitted": True,
                "is_default_sol_quote": True,
                "buy_identity_complete": True,
                "buy_wallets": ("B",),
                "route_status": "ROUTE_CLOSED",
                "current_route_closed_gross_return_pct": -10.0,
                "exit_observed_at": 98,
            },
        ]

        result = _history_feature(current, universe)

        self.assertEqual(result["prior_association_count"], 2)
        self.assertEqual(result["prior_unique_episode_count"], 2)
        self.assertEqual(result["wallets_with_history"], 2)
        self.assertEqual(result["history_coverage_pct"], 100.0)
        self.assertEqual(result[FEATURE_ID], 5.0)
        self.assertEqual(result["prior_positive_association_share_pct"], 50.0)

    def test_missing_wallet_identity_remains_missing_not_bad_history(self):
        result = _history_feature(
            {
                "buy_identity_complete": False,
                "buy_wallet_count": None,
                "buy_wallets": (),
            },
            [],
        )
        self.assertIsNone(result[FEATURE_ID])
        self.assertIsNone(result["history_coverage_pct"])
        self.assertEqual(result["prior_association_count"], 0)

    def test_partial_spearman_can_detect_incremental_positive_relation(self):
        value = _partial_spearman(
            [1, 2, 3, 4, 5, 6, 7, 8],
            [1, 3, 2, 4, 6, 5, 7, 8],
            [
                [2, 1, 3, 2, 5, 4, 6, 5],
                [1, 1, 2, 3, 2, 4, 3, 5],
            ],
        )
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)

    def test_preregistered_signal_quality_keep_and_kill_rules(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        keep_primary = {
            "usable_pair_count": 30,
            "spearman": 0.25,
            "spearman_without_best_trade": 0.20,
            "leave_one_out_sign_consistency_fraction": 1.0,
        }
        keep_runs = {
            "a": {"usable_pair_count": 10, "spearman": 0.20},
            "b": {"usable_pair_count": 10, "spearman": 0.10},
            "c": {"usable_pair_count": 10, "spearman": -0.01},
        }
        decision, _, checks = _decision(
            protocol=protocol,
            primary=keep_primary,
            per_run=keep_runs,
            incremental={"partial_spearman": 0.15},
        )
        self.assertEqual(decision, "KEEP")
        self.assertTrue(checks["positive_direction_run_fraction_gte_0_67"])

        kill_primary = {
            "usable_pair_count": 30,
            "spearman": -0.20,
            "spearman_without_best_trade": -0.15,
            "leave_one_out_sign_consistency_fraction": 1.0,
        }
        kill_runs = {
            "a": {"usable_pair_count": 10, "spearman": -0.20},
            "b": {"usable_pair_count": 10, "spearman": -0.10},
            "c": {"usable_pair_count": 10, "spearman": 0.01},
        }
        decision, _, _ = _decision(
            protocol=protocol,
            primary=kill_primary,
            per_run=kill_runs,
            incremental={"partial_spearman": -0.10},
        )
        self.assertEqual(decision, "KILL")


if __name__ == "__main__":
    unittest.main()
