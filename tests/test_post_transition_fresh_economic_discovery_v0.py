from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from benchmarks.post_transition_reacceleration_v0.assembled_entry_preflight import (
    FAIL,
    PASS,
    run_preflight,
)
from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    load_and_validate_contract,
)
from benchmarks.post_transition_reacceleration_v0.fresh_economic_discovery_v0 import (
    _aggregate,
    _route_offsets,
    run_fresh_discovery,
)
from src.assets import USDC_MINT, WRAPPED_SOL_MINT
from src.jupiter_swap_v2 import JupiterOrder


def _order(*, transaction: str | None = "assembled", impact: float = 0.1):
    return JupiterOrder(
        input_mint=USDC_MINT,
        output_mint=WRAPPED_SOL_MINT,
        in_amount_raw="25000000",
        out_amount_raw="100000000",
        in_usd_value=25.0,
        out_usd_value=25.0,
        swap_usd_value=25.0,
        slippage_bps=100,
        price_impact_pct_points=impact,
        router="metis",
        mode="ExactIn",
        request_id="req",
        quote_id="quote",
        transaction=transaction,
        last_valid_block_height=None,
        expire_at=None,
        error_code=None,
        error_message=None,
        observed_at=1000,
    )


class PostTransitionFreshEconomicDiscoveryV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_and_validate_contract()

    def test_fresh_run_contract_is_frozen_before_outcomes(self):
        fresh = self.contract["fresh_run"]
        self.assertEqual(fresh["admission_duration_seconds"], 1800)
        self.assertEqual(fresh["route_observation_interval_seconds"], 5)
        self.assertEqual(fresh["route_observation_final_grace_seconds"], 5)
        self.assertFalse(fresh["automatic_extension_allowed"])
        self.assertEqual(fresh["provider_timeout_seconds"], 5)
        self.assertTrue(fresh["single_fresh_run_only_before_review"])
        self.assertFalse(
            self.contract["scientific_guardrails"][
                "fresh_economic_outcomes_opened"
            ]
        )
        self.assertEqual(
            self.contract["entry"]["research_execution_mode"],
            "ROUTE_ONLY_PAPER",
        )
        self.assertFalse(
            self.contract["entry"]["require_assembled_transaction"]
        )
        self.assertFalse(
            self.contract["scientific_guardrails"][
                "funded_wallet_required_for_research"
            ]
        )

    def test_fresh_runner_has_no_taker_or_wallet_argument(self):
        params = inspect.signature(run_fresh_discovery).parameters
        self.assertNotIn("taker_public_key", params)

    def test_route_grid_is_exactly_5_through_305(self):
        offsets = _route_offsets(self.contract)
        self.assertEqual(offsets[0], 5)
        self.assertEqual(offsets[-2], 300)
        self.assertEqual(offsets[-1], 305)
        self.assertEqual(len(offsets), 61)
        self.assertEqual(offsets, list(range(5, 306, 5)))

    def test_assembled_entry_preflight_passes_only_with_transaction(self):
        with patch(
            "benchmarks.post_transition_reacceleration_v0."
            "assembled_entry_preflight.JupiterSwapV2Client.order",
            return_value=_order(transaction="assembled"),
        ):
            report = run_preflight(
                api_key="test-key",
                taker_public_key="test-taker",
            )
        self.assertEqual(report["classification"], PASS)
        self.assertTrue(report["assembled_transaction_present"])
        self.assertEqual(report["cohort_tokens_queried"], 0)
        self.assertFalse(report["fresh_economic_outcomes_opened"])
        self.assertFalse(report["transaction_submitted"])

    def test_assembled_entry_preflight_fails_route_only(self):
        with patch(
            "benchmarks.post_transition_reacceleration_v0."
            "assembled_entry_preflight.JupiterSwapV2Client.order",
            return_value=_order(transaction=None),
        ):
            report = run_preflight(
                api_key="test-key",
                taker_public_key="test-taker",
            )
        self.assertEqual(report["classification"], FAIL)
        self.assertFalse(report["assembled_transaction_present"])

    def test_assembled_entry_preflight_fails_impact_over_limit(self):
        with patch(
            "benchmarks.post_transition_reacceleration_v0."
            "assembled_entry_preflight.JupiterSwapV2Client.order",
            return_value=_order(transaction="assembled", impact=2.01),
        ):
            report = run_preflight(
                api_key="test-key",
                taker_public_key="test-taker",
            )
        self.assertEqual(report["classification"], FAIL)
        self.assertFalse(
            report["gates"]["provider_price_impact_within_frozen_limit"]
        )

    def test_aggregate_preserves_tail_and_mean_without_best(self):
        result = _aggregate([100.0, 10.0, -20.0])
        self.assertEqual(result["n"], 3)
        self.assertAlmostEqual(result["mean_pct"], 30.0)
        self.assertAlmostEqual(result["mean_without_best_pct"], -5.0)
        self.assertAlmostEqual(result["win_rate_pct"], 200.0 / 3.0)
        self.assertAlmostEqual(result["profit_factor"], 5.5)


if __name__ == "__main__":
    unittest.main()
