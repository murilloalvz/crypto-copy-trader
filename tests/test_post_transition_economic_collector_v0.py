from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    DEFAULT_CONTRACT, FIXED_60, FIXED_300, TP50, TP100, TP200,
    assert_fresh_discovery_blocked, build_market_path, classify_route_mark,
    collector_capabilities, contract_hash_sha256, dynamic_exit_status,
    evaluate_entry, evaluate_episode, evaluate_fixed_outcome,
    evaluate_take_profit, load_and_validate_contract, market_path_metrics,
)
from src.causal_quotes import CausalQuoteObservation

TOKEN = "TOKEN"
USDC = "USDC"


def buy(*, observed_at=1032, market_time=None, executable=True, impact=0.5,
        output_amount_raw="1000"):
    return CausalQuoteObservation(
        token_mint=TOKEN, side="buy",
        market_time=observed_at if market_time is None else market_time,
        observed_at=observed_at, price_usd=1.0, source="test",
        executable=executable,
        input_mint=USDC if executable else None,
        output_mint=TOKEN if executable else None,
        input_amount_raw="25000000", output_amount_raw=output_amount_raw,
        provider_price_impact_pct_points=impact,
    )


def sell(offset, price, *, entry_at=1032, impact=0.5, executable=False,
         input_amount_raw="1000", age=0, resolution=1):
    observed_at = entry_at + offset
    return CausalQuoteObservation(
        token_mint=TOKEN, side="sell",
        market_time=observed_at - age, observed_at=observed_at,
        price_usd=price, source="test", executable=executable,
        input_mint=TOKEN if executable else None,
        output_mint=USDC if executable else None,
        input_amount_raw=input_amount_raw, output_amount_raw="25000000",
        provider_price_impact_pct_points=impact,
        resolution_seconds=resolution, liquidity_usd=10000.0,
    )


def snapshot(marker=False):
    return {
        "as_of_observed_at": 1030,
        "as_of_arrival_index": 7,
        "structural_reacceleration_candidate": marker,
        "identity": {"transition_observed_at": 1000, "opportunity_mint": TOKEN},
    }


class EconomicCollectorV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_and_validate_contract()

    def test_01_contract_hash_and_guardrails(self):
        self.assertEqual(self.contract["contract_hash_sha256"], contract_hash_sha256(self.contract))
        self.assertEqual(self.contract["discovery_contract"]["selector_predicates"], [])
        self.assertFalse(self.contract["discovery_contract"]["structural_reacceleration_candidate_is_selector"])
        self.assertFalse(self.contract["scientific_guardrails"]["fresh_economic_outcomes_opened"])
        self.assertIsNone(self.contract["censoring"]["maximum_horizon_seconds"])

    def test_02_fresh_discovery_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "maximum horizon/censoring"):
            assert_fresh_discovery_blocked(self.contract)

    def test_03_contract_rejects_selector_mutation(self):
        payload = copy.deepcopy(self.contract)
        payload["discovery_contract"]["selector_predicates"] = [{"feature": "structural_reacceleration_candidate"}]
        payload["contract_hash_sha256"] = contract_hash_sha256(payload)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mutated.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selector_empty"):
                load_and_validate_contract(p)

    def test_04_fixed_roles_frozen(self):
        self.assertEqual(self.contract["standardized_outcomes"]["fixed_60"]["role"], "PRIMARY")
        self.assertEqual(self.contract["standardized_outcomes"]["fixed_300"]["role"], "EXPLORATORY")

    def test_05_entry_first_causal_quote_at_decision_plus_2(self):
        early, valid = buy(observed_at=1031), buy(observed_at=1032)
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[early, valid], contract=self.contract)
        self.assertEqual(r.status, "ENTRY_USABLE")
        self.assertEqual(r.ready_at, 1032)
        self.assertEqual(r.quote, valid)

    def test_06_entry_wait_over_5_rejected(self):
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[buy(observed_at=1038)], contract=self.contract)
        self.assertEqual(r.status, "ENTRY_UNAVAILABLE")

    def test_07_entry_stale_quote_rejected(self):
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[buy(market_time=1016)], contract=self.contract)
        self.assertEqual(r.status, "ENTRY_UNAVAILABLE")

    def test_08_entry_impact_over_2_rejected(self):
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[buy(impact=2.01)], contract=self.contract)
        self.assertIn("PRICE_IMPACT", r.status)

    def test_09_entry_requires_assembled_transaction_semantics(self):
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[buy(executable=False)], contract=self.contract)
        self.assertEqual(r.status, "ENTRY_UNAVAILABLE")

    def test_10_route_mark_requires_exact_entry_quantity(self):
        m = classify_route_mark(entry=buy(), quote=sell(10, 1.2, input_amount_raw="999"), contract=self.contract)
        self.assertFalse(m.routeable)
        self.assertEqual(m.reason, "EXACT_QUANTITY_MISMATCH")

    def test_11_route_mark_rejects_stale_quote(self):
        m = classify_route_mark(entry=buy(), quote=sell(10, 1.2, age=16), contract=self.contract)
        self.assertFalse(m.routeable)
        self.assertEqual(m.reason, "STALE_QUOTE")

    def test_12_route_mark_rejects_impact_over_2(self):
        m = classify_route_mark(entry=buy(), quote=sell(10, 1.2, impact=2.1), contract=self.contract)
        self.assertFalse(m.routeable)
        self.assertEqual(m.reason, "PRICE_IMPACT_EXCEEDS_LIMIT")

    def test_13_fixed60_first_valid_routeable_mark(self):
        marks = build_market_path(entry=buy(), quotes=[sell(60, 2.0, impact=3), sell(61, 1.2), sell(66, 4)], contract=self.contract)
        r = evaluate_fixed_outcome(name=FIXED_60, marks=marks, contract=self.contract)
        self.assertEqual(r["status"], "ROUTE_CLOSED")
        self.assertEqual(r["actual_offset_seconds"], 61)

    def test_14_fixed300_independent(self):
        marks = build_market_path(entry=buy(), quotes=[sell(60, .8), sell(300, 1.5)], contract=self.contract)
        a = evaluate_fixed_outcome(name=FIXED_60, marks=marks, contract=self.contract)
        b = evaluate_fixed_outcome(name=FIXED_300, marks=marks, contract=self.contract)
        self.assertNotEqual(a["net_return_pct"], b["net_return_pct"])
        self.assertEqual(a["role"], "PRIMARY")
        self.assertEqual(b["role"], "EXPLORATORY")

    def test_15_unrouteable_fixed_after_usable_entry_is_minus_100(self):
        marks = build_market_path(entry=buy(), quotes=[sell(60, 1.5, impact=3)], contract=self.contract)
        r = evaluate_fixed_outcome(name=FIXED_60, marks=marks, contract=self.contract)
        self.assertEqual(r["status"], "UNROUTABLE_EXIT")
        self.assertEqual(r["net_return_pct"], -100.0)

    def test_16_tp50_first_routeable_crossing(self):
        marks = build_market_path(entry=buy(), quotes=[sell(10, 1.4), sell(20, 1.6), sell(30, 2.8)], contract=self.contract)
        r = evaluate_take_profit(name=TP50, marks=marks, contract=self.contract, maximum_horizon_seconds=300)
        self.assertTrue(r["threshold_reached"])
        self.assertEqual(r["time_to_threshold_seconds"], 20)

    def test_17_tp100_tp200_are_independent(self):
        marks = build_market_path(entry=buy(), quotes=[sell(20, 1.6), sell(40, 2.1), sell(80, 3.1)], contract=self.contract)
        a = evaluate_take_profit(name=TP100, marks=marks, contract=self.contract, maximum_horizon_seconds=300)
        b = evaluate_take_profit(name=TP200, marks=marks, contract=self.contract, maximum_horizon_seconds=300)
        self.assertEqual(a["time_to_threshold_seconds"], 40)
        self.assertEqual(b["time_to_threshold_seconds"], 80)

    def test_18_nonrouteable_tp_crossing_does_not_count(self):
        marks = build_market_path(entry=buy(), quotes=[sell(10, 2, impact=3), sell(20, 1.6)], contract=self.contract)
        r = evaluate_take_profit(name=TP50, marks=marks, contract=self.contract, maximum_horizon_seconds=300)
        self.assertEqual(r["time_to_threshold_seconds"], 20)

    def test_19_tp_not_reached_is_not_fake_exit(self):
        marks = build_market_path(entry=buy(), quotes=[sell(10, 1.1), sell(30, 1.2)], contract=self.contract)
        r = evaluate_take_profit(name=TP200, marks=marks, contract=self.contract, maximum_horizon_seconds=60)
        self.assertEqual(r["status"], "NOT_REACHED")
        self.assertFalse(r["threshold_reached"])
        self.assertIsNone(r["net_return_if_exited_pct"])

    def test_20_fees_and_slippage_applied_once(self):
        m = classify_route_mark(entry=buy(), quote=sell(10, 1.5), contract=self.contract)
        entry_drag = (20 + 100) / 10000
        exit_drag = (20 + 100) / 10000
        expected = 100 * ((1.5 * (1 - exit_drag)) / (1 * (1 + entry_drag)) - 1)
        self.assertAlmostEqual(m.net_return_pct or 0, expected, places=12)

    def test_21_mfe_mae_are_descriptive_not_exits(self):
        marks = build_market_path(entry=buy(), quotes=[sell(5, .9), sell(10, 1.6), sell(20, .8)], contract=self.contract)
        m = market_path_metrics(marks, self.contract)
        self.assertGreater(m["mfe_pct"], 0)
        self.assertLess(m["mae_pct"], 0)
        self.assertEqual(m["time_to_mfe_seconds"], 10)
        self.assertEqual(m["time_to_mae_seconds"], 20)
        self.assertFalse(m["mfe_is_simulated_exit"])

    def test_22_time_above_below_uses_observed_grid_no_interpolation(self):
        marks = build_market_path(entry=buy(), quotes=[sell(5, 1.2, resolution=2), sell(10, 1.5, resolution=3), sell(20, .8, resolution=4)], contract=self.contract)
        m = market_path_metrics(marks, self.contract)
        self.assertEqual(m["time_above_+10_pct_seconds"], 5)
        self.assertEqual(m["time_below_-10_pct_seconds"], 4)
        self.assertFalse(m["missing_route_marks_interpolated"])

    def test_23_same_second_and_future_decision_information_do_not_leak(self):
        r = evaluate_entry(token_mint=TOKEN, decision_as_of=1030, quotes=[buy(observed_at=1030), buy(observed_at=1032)], contract=self.contract)
        self.assertEqual(r.quote.observed_at, 1032)

    def test_24_structural_marker_remains_non_selector(self):
        quotes = [buy(), sell(60, 1.2), sell(300, 1.3)]
        a = evaluate_episode(token_mint=TOKEN, decision_snapshot=snapshot(False), quotes=quotes, contract=self.contract, maximum_horizon_seconds=300)
        b = evaluate_episode(token_mint=TOKEN, decision_snapshot=snapshot(True), quotes=quotes, contract=self.contract, maximum_horizon_seconds=300)
        self.assertEqual(a["entry"]["status"], b["entry"]["status"])
        self.assertEqual(a["fixed_60"]["net_return_pct"], b["fixed_60"]["net_return_pct"])

    def test_25_dynamic_exits_not_armed_and_retrospective_isolated(self):
        s = dynamic_exit_status(self.contract)
        self.assertTrue(all(v["status"] == "NOT_ARMED" for v in s.values()))
        self.assertFalse(self.contract["dynamic_exit_policies"]["retrospective_human_assisted_exit_v0_reused"])

    def test_26_capability_matrix_explicit(self):
        c = collector_capabilities(self.contract)
        self.assertEqual(c[TP50], "ARMED")
        self.assertEqual(c[TP100], "ARMED")
        self.assertEqual(c[TP200], "ARMED")
        self.assertEqual(c["fresh_discovery"], "BLOCKED_PENDING_CENSORING_HORIZON")

    def test_27_entry_missing_is_missing_not_zero_loss(self):
        r = evaluate_episode(token_mint=TOKEN, decision_snapshot=snapshot(), quotes=[], contract=self.contract, maximum_horizon_seconds=300)
        self.assertFalse(r["included_in_conditional_economics"])
        self.assertIsNone(r["fixed_60"])
        self.assertIsNone(r[TP50])
        self.assertFalse(r["fresh_economic_outcomes_opened"])


if __name__ == "__main__":
    unittest.main()
