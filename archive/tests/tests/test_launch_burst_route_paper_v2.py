import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_route_paper_v2.run import _metrics, run_route_paper_v2
from src.causal_quotes import CausalQuoteObservation
from src.launch_burst_route_paper_v2 import (
    contract_hash_sha256,
    evaluate_episode,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "benchmarks" / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def snapshot(*, stratum="pump_launch", flow=0.10, complete=True, wall_ns=100_250_000_000):
    observed_t0 = wall_ns // 1_000_000_000
    return {
        "stratum": stratum,
        "complete": complete,
        "observed_t0": observed_t0,
        "observed_t0_wall_ns": wall_ns,
        "evidence_window_seconds": 5,
        "decision_as_of": observed_t0 + 5,
        "decision_cutoff_wall_ns": wall_ns + 5_000_000_000,
        "features": {"signed_flow_over_event_reserve": flow},
    }


def quote(side, observed_at, price, *, executable, amount="1000", token="TOKEN", impact=0.5):
    return CausalQuoteObservation(
        token_mint=token,
        side=side,
        market_time=observed_at,
        observed_at=observed_at,
        price_usd=price,
        source="fixture",
        executable=executable,
        input_mint="USDC" if side == "buy" else token,
        output_mint=token if side == "buy" else "USDC",
        input_amount_raw="25000000" if side == "buy" else amount,
        output_amount_raw=amount if side == "buy" else "27500000",
        route_id=f"{side}-{observed_at}",
        provider_slippage_bps=100,
        provider_price_impact_pct_points=impact,
        provider_swap_usd_value=25.0,
    )


class LaunchBurstRoutePaperV2Tests(unittest.TestCase):
    def setUp(self):
        self.contract = contract()

    def test_frozen_contract_hash_is_valid(self):
        validate_contract(self.contract)
        self.assertEqual(self.contract["contract_hash_sha256"], contract_hash_sha256(self.contract))
        mutated = copy.deepcopy(self.contract)
        mutated["selection_rule"]["predicates"][0]["value"] = 0.09
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_contract(mutated)

    def test_pumpswap_remains_hold(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pumpswap",
            feature_snapshot=snapshot(stratum="pumpswap_liquidity_launch"),
            quotes=(), contract=self.contract,
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.status, "STRATUM_HOLD")
        self.assertIsNone(decision.net_route_return_pct)

    def test_selection_threshold_is_frozen_at_point_08(self):
        reject = evaluate_episode(token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(flow=0.0799), quotes=(), contract=self.contract)
        admit = evaluate_episode(token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(flow=0.08), quotes=(), contract=self.contract)
        self.assertEqual(reject.status, "SELECTION_REJECT:signed_flow_over_event_reserve")
        self.assertTrue(admit.admitted)
        self.assertEqual(admit.status, "ENTRY_UNAVAILABLE")

    def test_entry_cannot_precede_exact_wall_cutoff_plus_latency(self):
        # cutoff is 105.25s; +2s latency => ceil to 108s for second-resolution provider evidence.
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
            quotes=(
                quote("buy", 107, 0.5, executable=True),
                quote("buy", 108, 1.0, executable=True),
            ), contract=self.contract,
        )
        self.assertEqual(decision.entry_quote.observed_at, 108)

    def test_exit_must_be_route_only_and_exact_entry_quantity(self):
        with self.assertRaisesRegex(ValueError, "route-only/non-executable"):
            evaluate_episode(
                token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
                quotes=(quote("buy", 108, 1.0, executable=True), quote("sell", 168, 1.1, executable=True)),
                contract=self.contract,
            )
        with self.assertRaisesRegex(ValueError, "exactly equal"):
            evaluate_episode(
                token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
                quotes=(quote("buy", 108, 1.0, executable=True), quote("sell", 168, 1.1, executable=False, amount="999")),
                contract=self.contract,
            )

    def test_route_closed_applies_costs_without_claiming_fill(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
            quotes=(quote("buy", 108, 1.0, executable=True), quote("sell", 168, 1.1, executable=False)),
            contract=self.contract,
        )
        self.assertEqual(decision.status, "ROUTE_CLOSED")
        self.assertAlmostEqual(decision.gross_route_return_pct, 10.0)
        self.assertLess(decision.net_route_return_pct, decision.gross_route_return_pct)
        self.assertEqual(decision.scope, "ROUTE_PAPER_NOT_LANDED_FILL")

    def test_missing_exit_counts_negative(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
            quotes=(quote("buy", 108, 1.0, executable=True),), contract=self.contract,
        )
        self.assertEqual(decision.status, "UNROUTABLE_EXIT")
        self.assertEqual(decision.net_route_return_pct, -100.0)
        self.assertEqual(decision.route_paper_pnl_usd, -25.0)

    def test_entry_provider_miss_is_coverage_not_zero_return(self):
        rows = [
            {
                "admitted": True,
                "status": "ENTRY_UNAVAILABLE",
                "entry_quote": None,
                "net_route_return_pct": 0.0,
            }
        ]
        metrics = _metrics(rows)
        self.assertEqual(metrics["admitted"], 1)
        self.assertEqual(metrics["entry_unavailable"], 1)
        self.assertEqual(metrics["entry_provider_coverage_pct"], 0.0)
        self.assertEqual(metrics["entry_usable"], 0)
        self.assertEqual(metrics["conditional_route_results"], 0)
        self.assertIsNone(metrics["conditional_mean_net_route_return_pct"])

    def test_failed_exit_stays_negative_in_conditional_return_metrics(self):
        rows = [
            {
                "admitted": True,
                "status": "UNROUTABLE_EXIT",
                "entry_quote": {"route_id": "entry"},
                "net_route_return_pct": -100.0,
            }
        ]
        metrics = _metrics(rows)
        self.assertEqual(metrics["entry_provider_coverage_pct"], 100.0)
        self.assertEqual(metrics["entry_usable"], 1)
        self.assertEqual(metrics["failed_exits"], 1)
        self.assertEqual(metrics["conditional_route_results"], 1)
        self.assertEqual(metrics["conditional_mean_net_route_return_pct"], -100.0)

    def test_runner_requires_prospective_attestations(self):
        source = {
            "type": "launch_burst_prospective_route_input_v2",
            "feature_snapshot_frozen_before_provider_quotes": True,
            "source_capture_started_after_contract_freeze": True,
            "episodes": [{
                "episode_key": "fixture",
                "token_mint": "TOKEN",
                "venue": "pump",
                "feature_snapshot": snapshot(flow=0.0),
                "quotes": [],
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            input_path = Path(temp) / "input.json"
            output_path = Path(temp) / "output.json"
            input_path.write_text(json.dumps(source), encoding="utf-8")
            result = run_route_paper_v2(contract_path=CONTRACT_PATH, input_path=input_path, output_path=output_path)
        self.assertEqual(result["classification"], "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2")
        self.assertEqual(result["status_counts"], {"SELECTION_REJECT:signed_flow_over_event_reserve": 1})


if __name__ == "__main__":
    unittest.main()
