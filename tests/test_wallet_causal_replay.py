import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_causal_replay import (
    WalletCausalReplayConfig,
    replay_wallet_action,
    replay_wallet_actions,
    summarize_wallet_causal_replay,
)


def _quote(
    observed_at: int,
    *,
    token: str = "T",
    market_time: int | None = None,
    price: float = 10.0,
    executable: bool = True,
    resolution_seconds: int = 1,
) -> CausalQuoteObservation:
    return CausalQuoteObservation(
        token_mint=token,
        market_time=observed_at if market_time is None else market_time,
        observed_at=observed_at,
        price_usd=price,
        source="test_quote",
        executable=executable,
        resolution_seconds=resolution_seconds,
        liquidity_usd=50_000.0,
    )


class WalletCausalReplayTests(unittest.TestCase):
    def test_never_uses_quote_observed_before_decision_ready(self):
        action = WalletActionObservation("W", "T", "buy", 100, 120)
        quotes = [_quote(125, price=8.0), _quote(136, price=10.0)]
        config = WalletCausalReplayConfig(decision_delay_seconds=15)

        result = replay_wallet_action(action, quotes, config=config)

        self.assertEqual(result.status, "filled")
        self.assertEqual(result.decision_ready_at, 135)
        self.assertEqual(result.quote_observed_at, 136)
        self.assertEqual(result.market_price_usd, 10.0)

    def test_buy_and_sell_slippage_are_directionally_conservative(self):
        quote = _quote(130, price=10.0)
        config = WalletCausalReplayConfig(slippage_bps=200)

        buy = replay_wallet_action(
            WalletActionObservation("W", "T", "buy", 100, 120),
            [quote],
            config=config,
        )
        sell = replay_wallet_action(
            WalletActionObservation("W", "T", "sell", 100, 120),
            [quote],
            config=config,
        )

        self.assertAlmostEqual(buy.simulated_execution_price_usd, 10.2)
        self.assertAlmostEqual(sell.simulated_execution_price_usd, 9.8)

    def test_proxy_quote_is_rejected_by_default(self):
        action = WalletActionObservation("W", "T", "buy", 100, 120)

        result = replay_wallet_action(action, [_quote(125, executable=False)])

        self.assertEqual(result.status, "missing_quote")
        self.assertEqual(result.reason, "no_executable_quote_in_window")

    def test_proxy_quote_can_be_used_only_when_explicitly_allowed(self):
        action = WalletActionObservation("W", "T", "buy", 100, 120)
        config = WalletCausalReplayConfig(require_executable_quote=False)

        result = replay_wallet_action(
            action,
            [_quote(125, executable=False, resolution_seconds=60)],
            config=config,
        )

        self.assertEqual(result.status, "filled")
        self.assertFalse(result.quote_executable)
        self.assertEqual(result.quote_resolution_seconds, 60)

    def test_stale_quote_is_not_silently_accepted(self):
        action = WalletActionObservation("W", "T", "buy", 100, 120)
        stale = _quote(125, market_time=90)
        config = WalletCausalReplayConfig(max_quote_age_seconds=15)

        result = replay_wallet_action(action, [stale], config=config)

        self.assertEqual(result.status, "missing_quote")
        self.assertEqual(result.reason, "no_fresh_quote_in_window")

    def test_quote_arriving_after_wait_budget_is_missing(self):
        selection = select_first_causal_quote(
            [_quote(151)],
            token_mint="T",
            ready_at=120,
            max_quote_age_seconds=15,
            max_quote_wait_seconds=30,
        )

        self.assertIsNone(selection.quote)
        self.assertEqual(selection.reason, "no_quote_within_wait_window")

    def test_summary_reports_end_to_end_latency_and_coverage(self):
        actions = [
            WalletActionObservation("A", "T1", "buy", 100, 120),
            WalletActionObservation("B", "T2", "buy", 200, 230),
        ]
        quotes = [_quote(130, token="T1")]

        results = replay_wallet_actions(actions, quotes)
        summary = summarize_wallet_causal_replay(results)

        self.assertEqual(summary.action_count, 2)
        self.assertEqual(summary.filled_count, 1)
        self.assertEqual(summary.missing_count, 1)
        self.assertEqual(summary.fill_coverage_pct, 50.0)
        self.assertEqual(summary.wallet_count, 2)
        self.assertEqual(summary.token_count, 2)
        self.assertEqual(summary.median_source_lag_seconds, 25.0)
        self.assertEqual(summary.median_quote_wait_seconds, 10.0)
        self.assertEqual(summary.p95_total_chain_to_quote_seconds, 30.0)

    def test_quote_store_is_idempotent_and_respects_as_of(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = _quote(120, token="T")
                second = _quote(170, token="T")
                self.assertTrue(record_causal_quote(first, quote_key="q1"))
                self.assertFalse(record_causal_quote(first, quote_key="q1"))
                self.assertTrue(record_causal_quote(second, quote_key="q2"))

                early = load_causal_quotes(token_mint="T", as_of=150)
                all_rows = load_causal_quotes(token_mint="T")

        self.assertEqual(len(early), 1)
        self.assertEqual(len(all_rows), 2)

    def test_invalid_quote_cannot_claim_future_market_state_was_seen_earlier(self):
        invalid = _quote(100, market_time=101)
        with self.assertRaises(ValueError):
            select_first_causal_quote(
                [invalid],
                token_mint="T",
                ready_at=100,
                max_quote_age_seconds=15,
                max_quote_wait_seconds=30,
            )


if __name__ == "__main__":
    unittest.main()
