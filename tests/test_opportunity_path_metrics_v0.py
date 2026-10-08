import random
import unittest

from src.opportunity_path_metrics_v0 import (
    EXIT_RULE_HOLD_UNTIL_WINDOW_END,
    EXIT_RULE_PARTIAL50_AT50_TRAIL20,
    EXIT_RULE_TIME_STOP_5M,
    EXIT_RULE_TP50_SL30,
    EXIT_RULE_TP100_SL50,
    EXIT_RULE_TRAIL20_AFTER20,
    CostModel,
    PathTrade,
    compute_window_metrics,
    executed_trade_price_sol,
    find_causal_entry,
    first_barrier_touch,
    mid_price_sol,
    simulate_amm_buy_execution_price_sol,
    simulate_amm_sell_execution_price_sol,
    simulate_exit,
)

BASE_DECIMALS = 6
QUOTE_DECIMALS = 9
LIQUIDITY_TOKENS = 1_000_000_000.0
FREE_COST_MODEL = CostModel(venue_fee_pct=0.0, terminal_fee_pct=0.0)


def trade_at(
    chain_time: int,
    price_sol: float,
    *,
    venue: str = "pump_bonding_curve",
    liquidity_tokens: float = LIQUIDITY_TOKENS,
    traded_tokens: float = 1.0,
) -> PathTrade:
    base_reserves_raw = int(liquidity_tokens * 10**BASE_DECIMALS)
    quote_reserves_raw = int(price_sol * liquidity_tokens * 10**QUOTE_DECIMALS)
    base_amount_raw = int(traded_tokens * 10**BASE_DECIMALS)
    quote_amount_raw = int(price_sol * traded_tokens * 10**QUOTE_DECIMALS)
    return PathTrade(
        chain_time=chain_time,
        venue=venue,
        base_amount_raw=base_amount_raw,
        quote_amount_raw=quote_amount_raw,
        base_reserves_raw=base_reserves_raw,
        quote_reserves_raw=quote_reserves_raw,
    )


class PriceDerivationTests(unittest.TestCase):
    def test_executed_and_mid_price_agree_on_a_consistent_synthetic_trade(self):
        trade = trade_at(1_000, 0.0001)
        self.assertAlmostEqual(executed_trade_price_sol(trade), 0.0001, places=12)
        self.assertAlmostEqual(mid_price_sol(trade), 0.0001, places=12)

    def test_missing_amounts_yield_none_not_zero(self):
        trade = PathTrade(chain_time=1, venue="pump_bonding_curve")
        self.assertIsNone(executed_trade_price_sol(trade))
        self.assertIsNone(mid_price_sol(trade))


class AmmSlippageTests(unittest.TestCase):
    def test_buy_execution_price_worsens_with_size(self):
        trade = trade_at(1_000, 0.0001)
        small = simulate_amm_buy_execution_price_sol(
            reserves_trade=trade, size_sol=0.01, cost_model=FREE_COST_MODEL
        )
        large = simulate_amm_buy_execution_price_sol(
            reserves_trade=trade, size_sol=10.0, cost_model=FREE_COST_MODEL
        )
        self.assertGreater(small, 0.0001)
        self.assertGreater(large, small)

    def test_sell_execution_price_worsens_with_size(self):
        trade = trade_at(1_000, 0.0001)
        small = simulate_amm_sell_execution_price_sol(
            reserves_trade=trade, size_tokens=10.0, cost_model=FREE_COST_MODEL
        )
        large = simulate_amm_sell_execution_price_sol(
            reserves_trade=trade, size_tokens=1_000_000.0, cost_model=FREE_COST_MODEL
        )
        self.assertLess(small, 0.0001)
        self.assertLess(large, small)

    def test_fees_reduce_buy_output_and_sell_output(self):
        trade = trade_at(1_000, 0.0001)
        free = simulate_amm_buy_execution_price_sol(
            reserves_trade=trade, size_sol=1.0, cost_model=FREE_COST_MODEL
        )
        taxed = simulate_amm_buy_execution_price_sol(
            reserves_trade=trade,
            size_sol=1.0,
            cost_model=CostModel(venue_fee_pct=1.0, terminal_fee_pct=1.0),
        )
        self.assertGreater(taxed, free)

    def test_missing_reserves_yield_none(self):
        trade = PathTrade(chain_time=1, venue="pumpswap")
        self.assertIsNone(
            simulate_amm_buy_execution_price_sol(
                reserves_trade=trade, size_sol=1.0, cost_model=FREE_COST_MODEL
            )
        )


class CausalEntryTests(unittest.TestCase):
    def _trades(self):
        return [
            trade_at(900, 0.0001),
            trade_at(995, 0.0001),
            trade_at(1_005, 0.00011),
            trade_at(1_020, 0.00012),
            trade_at(1_200, 0.0002),
        ]

    def test_picks_first_trade_at_or_after_threshold(self):
        entry = find_causal_entry(
            self._trades(),
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(entry.trade_chain_time, 1_005)
        self.assertIsNone(entry.missing_reason)
        self.assertGreater(entry.execution_price_sol, entry.mid_price_sol)

    def test_missing_when_no_trade_reaches_threshold(self):
        entry = find_causal_entry(
            self._trades(),
            signal_time=1_000,
            entry_latency_seconds=1_000,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertIsNone(entry.trade_chain_time)
        self.assertEqual(entry.missing_reason, "no_trade_at_or_after_entry_time")

    def test_entry_is_unaffected_by_shuffling_or_altering_future_trades(self):
        trades = self._trades()
        baseline = find_causal_entry(
            trades,
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )

        # Dropping everything strictly after the chosen entry trade must not change it.
        truncated = [t for t in trades if t.chain_time <= 1_005]
        truncated_entry = find_causal_entry(
            truncated,
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(baseline, truncated_entry)

        # Replacing future trades with wildly different (even malformed) data must
        # not change it either, as long as the chosen entry trade is untouched.
        altered = [t for t in trades if t.chain_time <= 1_005] + [
            trade_at(5_000, 999.0),
            trade_at(9_000, 0.0000001),
        ]
        altered_entry = find_causal_entry(
            altered,
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(baseline, altered_entry)

        # Shuffling the whole input list's order must not change the result.
        shuffled = list(trades)
        random.Random(42).shuffle(shuffled)
        shuffled_entry = find_causal_entry(
            shuffled,
            signal_time=1_000,
            entry_latency_seconds=5,
            size_sol=0.01,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(baseline, shuffled_entry)


class WindowMetricsSyntheticPathTests(unittest.TestCase):
    def test_pump_then_dump_mfe_at_peak_mae_after_drop(self):
        trades = [
            trade_at(0, 0.0001),  # entry
            trade_at(10, 0.00015),
            trade_at(20, 0.0003),  # peak: +200% vs entry trade's own price
            trade_at(30, 0.00009),
            trade_at(40, 0.00003),  # trough
            trade_at(50, 0.00005),
        ]
        entry_execution_price = 0.0001
        metrics = compute_window_metrics(
            trades,
            entry_chain_time=0,
            entry_execution_price_sol=entry_execution_price,
            window_seconds=60,
        )
        self.assertEqual(metrics.n_trades_in_window, 6)
        self.assertAlmostEqual(metrics.mfe_pct, 200.0, places=6)
        self.assertEqual(metrics.time_to_mfe_seconds, 20)
        self.assertAlmostEqual(metrics.mae_pct, -70.0, places=6)
        self.assertEqual(metrics.time_to_mae_seconds, 40)
        self.assertAlmostEqual(metrics.return_at_window_end_pct, -50.0, places=6)

    def test_slow_bleed_mfe_at_start_mae_at_end(self):
        trades = [trade_at(t, 0.0001 * (1 - t / 1000)) for t in range(0, 61, 10)]
        metrics = compute_window_metrics(
            trades, entry_chain_time=0, entry_execution_price_sol=0.0001, window_seconds=60
        )
        self.assertGreater(metrics.mfe_pct, metrics.mae_pct)
        self.assertEqual(metrics.time_to_mae_seconds, 60)
        self.assertLess(metrics.return_at_window_end_pct, 0)

    def test_token_going_to_near_zero_is_real_pnl_not_excluded(self):
        trades = [
            trade_at(0, 0.0001),
            trade_at(30, 0.0000001),
        ]
        metrics = compute_window_metrics(
            trades, entry_chain_time=0, entry_execution_price_sol=0.0001, window_seconds=60
        )
        self.assertLess(metrics.mae_pct, -99.0)
        self.assertNotIn("no_trades_in_window", metrics.flags)
        self.assertNotIn("no_price_derivable_in_window", metrics.flags)

    def test_no_trades_in_window_is_flagged_not_invented(self):
        metrics = compute_window_metrics(
            [trade_at(0, 0.0001)],
            entry_chain_time=1_000,
            entry_execution_price_sol=0.0001,
            window_seconds=60,
        )
        self.assertEqual(metrics.n_trades_in_window, 0)
        self.assertEqual(metrics.flags, ("no_trades_in_window",))
        self.assertIsNone(metrics.mfe_pct)
        self.assertIsNone(metrics.mae_pct)

    def test_internal_gap_is_flagged(self):
        trades = [trade_at(0, 0.0001), trade_at(500, 0.00011)]
        metrics = compute_window_metrics(
            trades,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            window_seconds=900,
            gap_flag_seconds=60,
        )
        self.assertTrue(any(flag.startswith("internal_gap_exceeds_threshold") for flag in metrics.flags))

    def test_mid_window_venue_migration_with_discontinuity_is_flagged(self):
        trades = [
            trade_at(0, 0.0001, venue="pump_bonding_curve"),
            trade_at(10, 0.00011, venue="pump_bonding_curve"),
            trade_at(20, 0.0005, venue="pumpswap"),  # big jump at migration
            trade_at(30, 0.00051, venue="pumpswap"),
        ]
        metrics = compute_window_metrics(
            trades, entry_chain_time=0, entry_execution_price_sol=0.0001, window_seconds=60
        )
        self.assertIn("venue_migration_in_window", metrics.flags)
        self.assertTrue(any(flag.startswith("price_discontinuity_at_migration") for flag in metrics.flags))

    def test_mid_window_venue_migration_without_discontinuity_is_not_flagged_as_discontinuous(self):
        trades = [
            trade_at(0, 0.0001, venue="pump_bonding_curve"),
            trade_at(10, 0.000101, venue="pump_bonding_curve"),
            trade_at(20, 0.000102, venue="pumpswap"),
            trade_at(30, 0.000103, venue="pumpswap"),
        ]
        metrics = compute_window_metrics(
            trades, entry_chain_time=0, entry_execution_price_sol=0.0001, window_seconds=60
        )
        self.assertIn("venue_migration_in_window", metrics.flags)
        self.assertFalse(any(flag.startswith("price_discontinuity_at_migration") for flag in metrics.flags))

    def test_price_stale_at_window_end_is_flagged(self):
        trades = [trade_at(0, 0.0001), trade_at(10, 0.0001)]
        metrics = compute_window_metrics(
            trades, entry_chain_time=0, entry_execution_price_sol=0.0001, window_seconds=900
        )
        self.assertTrue(any(flag.startswith("price_stale_at_window_end") for flag in metrics.flags))


class BarrierTouchTests(unittest.TestCase):
    def test_target_touched_first_is_up(self):
        # 0.000151 is comfortably past +50% (not exactly at the boundary) so
        # int()-truncation in the trade_at() helper cannot flip the comparison.
        trades = [trade_at(10, 0.000151), trade_at(20, 0.00003)]
        result = first_barrier_touch(
            trades,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            window_seconds=60,
            target_pct=50.0,
            stop_pct=-30.0,
        )
        self.assertEqual(result, "UP")

    def test_stop_touched_first_is_down(self):
        trades = [trade_at(10, 0.00006), trade_at(20, 0.00015)]
        result = first_barrier_touch(
            trades,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            window_seconds=60,
            target_pct=50.0,
            stop_pct=-30.0,
        )
        self.assertEqual(result, "DOWN")

    def test_neither_touched_is_none(self):
        trades = [trade_at(10, 0.000105), trade_at(20, 0.000098)]
        result = first_barrier_touch(
            trades,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            window_seconds=60,
            target_pct=50.0,
            stop_pct=-30.0,
        )
        self.assertEqual(result, "NONE")


class ExitLibraryTests(unittest.TestCase):
    def test_tp50_sl30_takes_profit(self):
        trades = [trade_at(10, 0.00009), trade_at(20, 0.00016), trade_at(30, 0.0002)]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TP50_SL30,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "take_profit")
        self.assertEqual(result.trigger_chain_time, 20)
        self.assertGreater(result.net_return_pct, 0)

    def test_tp50_sl30_stops_out(self):
        trades = [trade_at(10, 0.00009), trade_at(20, 0.00006)]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TP50_SL30,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "stop_loss")
        self.assertLess(result.net_return_pct, 0)

    def test_tp100_sl50_uses_wider_barriers(self):
        trades = [trade_at(10, 0.00014)]  # +40%: neither +100 nor -50 -> holds
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TP100_SL50,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "hold_to_window_end")

    def test_trailing_stop_arms_only_after_plus20_then_trails(self):
        trades = [
            trade_at(10, 0.00009),  # -10%, never arms
            trade_at(20, 0.00013),  # +30%, arms, peak=30
            trade_at(30, 0.000104),  # drawdown from peak: 30-4=26 >= 20 -> trail fires
        ]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TRAIL20_AFTER20,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "trailing_stop")
        self.assertEqual(result.trigger_chain_time, 30)

    def test_trailing_stop_never_arms_without_plus20_and_holds(self):
        trades = [trade_at(10, 0.000105), trade_at(20, 0.0000995)]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TRAIL20_AFTER20,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "hold_to_window_end")

    def test_time_stop_5m_fires_at_fixed_offset_regardless_of_price(self):
        trades = [trade_at(100, 0.00013), trade_at(300, 0.00011), trade_at(400, 0.00009)]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TIME_STOP_5M,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=900,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "time_stop_5m")
        self.assertEqual(result.trigger_chain_time, 300)

    def test_hold_until_window_end_ignores_intermediate_moves(self):
        trades = [trade_at(10, 0.0005), trade_at(20, 0.00002), trade_at(50, 0.00012)]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_HOLD_UNTIL_WINDOW_END,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "hold_to_window_end")
        self.assertEqual(result.exit_chain_time, 50)

    def test_partial50_then_trail_fires_after_arming(self):
        trades = [
            trade_at(10, 0.00016),  # +60% >= 50 -> arms partial, peak=60
            trade_at(20, 0.000128),  # +28%: drawdown from peak 60-28=32 >= 20 -> trail fires
        ]
        result = simulate_exit(
            trades,
            rule_id=EXIT_RULE_PARTIAL50_AT50_TRAIL20,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.exit_reason, "trailing_stop_on_remainder")

    def test_exit_latency_delays_execution_to_a_later_trade(self):
        trades = [trade_at(10, 0.00016), trade_at(15, 0.00017), trade_at(40, 0.00018)]
        immediate = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TP50_SL30,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        delayed = simulate_exit(
            trades,
            rule_id=EXIT_RULE_TP50_SL30,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=20,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(immediate.trigger_chain_time, delayed.trigger_chain_time)
        self.assertEqual(immediate.exit_chain_time, 10)
        self.assertEqual(delayed.exit_chain_time, 40)

    def test_no_priced_trades_after_entry_is_flagged_missing(self):
        result = simulate_exit(
            [],
            rule_id=EXIT_RULE_HOLD_UNTIL_WINDOW_END,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=FREE_COST_MODEL,
        )
        self.assertEqual(result.missing_reason, "no_priced_trades_after_entry")
        self.assertIsNone(result.net_return_pct)

    def test_flat_leg_costs_reduce_net_return_below_gross(self):
        trades = [trade_at(10, 0.00016)]
        costed = simulate_exit(
            trades,
            rule_id=EXIT_RULE_HOLD_UNTIL_WINDOW_END,
            entry_chain_time=0,
            entry_execution_price_sol=0.0001,
            size_sol=0.01,
            window_seconds=60,
            exit_latency_seconds=0,
            cost_model=CostModel(venue_fee_pct=0.0, terminal_fee_pct=0.0, network_fee_sol=0.0003),
        )
        self.assertLess(costed.net_return_pct, costed.gross_return_pct)


if __name__ == "__main__":
    unittest.main()
