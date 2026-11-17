import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_economic_v1.run import BLOCKED_CLASSIFICATION, run_economic_v1
from src.causal_quotes import CausalQuoteObservation
from src.launch_burst_economic_v1 import (
    CONTRACT_SCHEMA_VERSION,
    contract_hash_sha256,
    evaluate_episode,
    feature_snapshot_hash_sha256,
    freeze_contract,
    validate_contract,
)


PREREG_PATH = Path("benchmarks/launch_burst_prospective_economic_v1/pump_selection_preregistration_v1.json")
FROZEN_CONTRACT_PATH = Path("benchmarks/launch_burst_prospective_economic_v1/pump_economic_contract_v1.frozen.json")


def draft_contract():
    # Synthetic test values only; these are not the production Launch Burst hypothesis.
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "status": "DRAFT_UNARMED",
        "source_feature_report_sha256": "a" * 64,
        "selection_preregistration_sha256": "b" * 64,
        "primary_evidence": {"window_seconds": 5, "confirmation_window_seconds": None},
        "strata": ["pump_launch", "pumpswap_liquidity_launch"],
        "active_strata": ["pump_launch"],
        "selection_rule": {"mode": "all_of", "predicates": [{"feature": "event_count", "op": ">=", "value": 5}]},
        "entry": {"latency_seconds": 1, "max_quote_age_seconds": 10, "max_quote_wait_seconds": 10, "require_executable": True},
        "costs": {"entry_fee_bps": 25, "exit_fee_bps": 25, "entry_adverse_slippage_bps": 50, "exit_adverse_slippage_bps": 50},
        "position": {"notional_usd": 25.0, "max_fraction_of_reported_liquidity": 0.01, "require_liquidity_observation": True, "max_provider_price_impact_pct_points": 2.0},
        "exit": {"policy": "fixed_horizon_from_entry", "horizon_seconds": 60, "max_quote_age_seconds": 10, "max_quote_wait_seconds": 10, "require_executable": True},
        "failure_policy": {"entry_unavailable_return_pct": 0.0, "unexitable_return_pct": -100.0},
    }


def snapshot(stratum="pump_launch", complete=True, event_count=6, observed_t0=100):
    return {
        "stratum": stratum,
        "complete": complete,
        "observed_t0": observed_t0,
        "evidence_window_seconds": 5,
        "decision_as_of": observed_t0 + 5,
        "features": {"event_count": event_count, "unique_wallet_count": 4},
    }


def quote(side, observed_at, price, token="TOKEN", liquidity=10_000.0):
    return CausalQuoteObservation(
        token_mint=token, side=side, market_time=observed_at, observed_at=observed_at,
        price_usd=price, source="fixture", executable=True, liquidity_usd=liquidity,
        input_mint="USDC" if side == "buy" else token,
        output_mint=token if side == "buy" else "USDC",
        input_amount_raw="25000000", output_amount_raw="25000000",
        route_id=f"{side}-{observed_at}", provider_price_impact_pct_points=0.5,
    )


class LaunchBurstEconomicV1Tests(unittest.TestCase):
    def setUp(self):
        self.contract = freeze_contract(draft_contract())

    def test_contract_hash_and_no_post_hoc_threshold_mutation(self):
        validate_contract(self.contract, require_frozen=True)
        self.assertEqual(self.contract["contract_hash_sha256"], contract_hash_sha256(self.contract))
        mutated = copy.deepcopy(self.contract)
        mutated["selection_rule"]["predicates"][0]["value"] = 6
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_contract(mutated, require_frozen=True)

    def test_immutable_decision_snapshot_hash(self):
        original = snapshot()
        changed = copy.deepcopy(original)
        changed["features"]["event_count"] = 99
        self.assertNotEqual(feature_snapshot_hash_sha256(original), feature_snapshot_hash_sha256(changed))

    def test_right_censoring_is_not_zero(self):
        decision = evaluate_episode(token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(complete=False, event_count=0), quotes=(), contract=self.contract)
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.status, "RIGHT_CENSORED")
        self.assertIsNone(decision.net_return_pct)

    def test_decision_snapshot_must_be_exactly_observed_t0_plus_5s(self):
        bad = snapshot()
        bad["decision_as_of"] = 106
        with self.assertRaisesRegex(ValueError, r"observed_t0 \+ 5s"):
            evaluate_episode(token_mint="TOKEN", venue="pump", feature_snapshot=bad, quotes=(), contract=self.contract)

    def test_no_future_leakage_entry_is_after_cutoff_plus_latency(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
            quotes=(quote("buy", 105, 0.5), quote("buy", 106, 1.0), quote("sell", 166, 1.1)),
            contract=self.contract,
        )
        self.assertEqual(decision.entry_quote.observed_at, 106)
        self.assertEqual(decision.entry_quote.price_usd, 1.0)

    def test_fees_and_slippage_are_applied(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump_bonding_curve", feature_snapshot=snapshot(),
            quotes=(quote("buy", 106, 1.0), quote("sell", 166, 1.1)), contract=self.contract,
        )
        self.assertEqual(decision.status, "CLOSED")
        self.assertAlmostEqual(decision.gross_return_pct, 10.0)
        self.assertLess(decision.net_return_pct, decision.gross_return_pct)

    def test_zero_liquidity_rejects_entry_without_division_by_zero(self):
        decision = evaluate_episode(
            token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(),
            quotes=(quote("buy", 106, 1.0, liquidity=0.0),), contract=self.contract,
        )
        self.assertEqual(decision.status, "ENTRY_REJECTED:LIQUIDITY_UNAVAILABLE")

    def test_unexitable_exit_is_counted(self):
        decision = evaluate_episode(token_mint="TOKEN", venue="pump", feature_snapshot=snapshot(), quotes=(quote("buy", 106, 1.0),), contract=self.contract)
        self.assertEqual(decision.status, "UNEXITABLE")
        self.assertEqual(decision.net_return_pct, -100.0)
        self.assertEqual(decision.pnl_usd, -25.0)

    def test_pump_and_pumpswap_separation(self):
        pump = evaluate_episode(token_mint="TOKEN", venue="pump_bonding_curve", feature_snapshot=snapshot(), quotes=(), contract=self.contract)
        pumpswap = evaluate_episode(token_mint="TOKEN2", venue="pumpswap", feature_snapshot=snapshot(stratum="pumpswap_liquidity_launch"), quotes=(), contract=self.contract)
        self.assertEqual(pump.stratum, "pump_launch")
        self.assertEqual(pumpswap.stratum, "pumpswap_liquidity_launch")

    def test_draft_blocks_before_outcome_input_is_read(self):
        draft = draft_contract()
        draft["selection_rule"]["predicates"] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(draft), encoding="utf-8")
            result = run_economic_v1(contract_path=contract_path, input_path=root / "must-not-be-read.json", output_path=root / "result.json")
        self.assertEqual(result["classification"], BLOCKED_CLASSIFICATION)
        self.assertFalse(result["economic_outcomes_opened"])

    def test_runner_holds_inactive_pumpswap_without_economic_result(self):
        contract = freeze_contract(draft_contract())
        source = {
            "type": "launch_burst_prospective_economic_input_v1",
            "feature_snapshot_frozen_before_outcomes": True,
            "episodes": [
                {
                    "episode_key": "pumpswap-held",
                    "token_mint": "TOKEN2",
                    "venue": "pumpswap",
                    "feature_snapshot": snapshot(stratum="pumpswap_liquidity_launch"),
                    "quotes": [],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_path = root / "contract.json"
            input_path = root / "input.json"
            output_path = root / "output.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            input_path.write_text(json.dumps(source), encoding="utf-8")
            result = run_economic_v1(contract_path=contract_path, input_path=input_path, output_path=output_path)
        self.assertEqual(result["active_strata"], ["pump_launch"])
        self.assertEqual(result["status_counts"], {"STRATUM_HOLD": 1})
        self.assertEqual(result["strata"]["pumpswap_liquidity_launch"]["held"], 1)
        self.assertEqual(result["strata"]["pumpswap_liquidity_launch"]["economic_results"], 0)
        self.assertIsNone(result["decisions"][0]["net_return_pct"])

    def test_pump_selection_preregistration_is_frozen_and_outcome_blind(self):
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
        expected_hash = prereg.pop("preregistration_sha256")
        canonical = json.dumps(prereg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(expected_hash, actual_hash)
        self.assertEqual(expected_hash, "9a2f666a2e03e9c2ba39fc69ae9377de2ea2a0fcb2455e31256fdb473041865a")
        self.assertFalse(prereg["outcomes_opened"])
        self.assertEqual(prereg["economic_parameters_status"], "UNARMED")
        pump = prereg["strata"]["pump_launch"]
        self.assertEqual(pump["decision"], "ACTIVE_PROSPECTIVE_HYPOTHESIS")
        self.assertEqual(pump["primary_evidence"], {"window_seconds": 5, "confirmation_window_seconds": None})
        self.assertEqual(
            pump["selection_rule"]["predicates"],
            [{"feature": "signed_flow_over_event_reserve", "op": ">=", "value": 0.08}],
        )
        self.assertEqual(prereg["strata"]["pumpswap_liquidity_launch"]["decision"], "HOLD_INSUFFICIENT_FEATURE_SAMPLE")

    def test_frozen_pump_economic_contract_matches_preregistration(self):
        contract = json.loads(FROZEN_CONTRACT_PATH.read_text(encoding="utf-8"))
        validate_contract(contract, require_frozen=True)
        self.assertEqual(contract["contract_hash_sha256"], contract_hash_sha256(contract))
        self.assertEqual(
            contract["contract_hash_sha256"],
            "859a071145395789956d8df27bf348c134c1031eb43bc6e3ccf3aeec820222a5",
        )
        self.assertEqual(contract["active_strata"], ["pump_launch"])
        self.assertEqual(
            contract["selection_preregistration_sha256"],
            "9a2f666a2e03e9c2ba39fc69ae9377de2ea2a0fcb2455e31256fdb473041865a",
        )
        self.assertEqual(
            contract["selection_rule"]["predicates"],
            [{"feature": "signed_flow_over_event_reserve", "op": ">=", "value": 0.08}],
        )
        self.assertEqual(contract["entry"]["latency_seconds"], 2)
        self.assertEqual(contract["position"]["notional_usd"], 25.0)
        self.assertEqual(contract["exit"]["horizon_seconds"], 60)
        self.assertEqual(contract["failure_policy"]["unexitable_return_pct"], -100.0)


if __name__ == "__main__":
    unittest.main()
