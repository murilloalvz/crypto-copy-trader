from __future__ import annotations

import unittest

from src.exceptional_trade_preentry_v56 import (
    ExceptionalTradeReferenceV56,
    build_exceptional_trade_preentry_snapshot_v56,
    derived_preentry_dynamics_v56,
)
from src.market_observation_store import StoredMarketTrade
from src.market_opportunity_radar import MarketTradeObservation


def row(
    *,
    event_key: str,
    chain_time: int,
    observed_at: int,
    wallet: str | None,
    side: str = "buy",
    notional: float | None = 10.0,
    price: float | None = 1.0,
    run_key: str = "run-A",
    mint: str = "TOKEN",
) -> StoredMarketTrade:
    return StoredMarketTrade(
        acquisition_run_key=run_key,
        event_key=event_key,
        source_provider="synthetic",
        observation=MarketTradeObservation(
            token_mint=mint,
            side=side,
            chain_time=chain_time,
            observed_at=observed_at,
            wallet_address=wallet,
            notional_usd=notional,
            price_usd=price,
            venue="synthetic",
            transaction_key=f"tx-{event_key}",
        ),
    )


class ExceptionalTradePreEntryV56Tests(unittest.TestCase):
    def setUp(self):
        self.reference = ExceptionalTradeReferenceV56(
            reference_key="ref-1",
            acquisition_run_key="run-A",
            wallet_address="target-wallet",
            token_mint="TOKEN",
            entry_chain_time=100,
            entry_observed_at=103,
        )

    def test_excludes_target_second_and_later_market_events(self):
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=(
                row(event_key="before", chain_time=99, observed_at=101, wallet="w1"),
                row(event_key="same", chain_time=100, observed_at=102, wallet="target-wallet"),
                row(event_key="later", chain_time=101, observed_at=102, wallet="w2"),
            ),
        )
        self.assertEqual(snapshot.rows_strictly_preentry, 1)
        self.assertEqual(snapshot.excluded_same_or_later_market_time, 2)
        self.assertEqual(next(w for w in snapshot.windows if w.window_seconds == 10).event_count, 1)

    def test_excludes_preentry_chain_event_not_known_before_entry(self):
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=(
                row(event_key="known", chain_time=98, observed_at=102, wallet="w1"),
                row(event_key="late", chain_time=99, observed_at=103, wallet="w2"),
            ),
        )
        self.assertEqual(snapshot.rows_strictly_preentry, 1)
        self.assertEqual(snapshot.excluded_not_known_before_entry, 1)
        self.assertIn(
            "preentry_chain_events_not_known_before_reference_entry",
            snapshot.data_quality_flags,
        )

    def test_complete_wallet_identity_enables_concentration_and_repetition(self):
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=(
                row(event_key="a", chain_time=95, observed_at=96, wallet="w1"),
                row(event_key="b", chain_time=96, observed_at=97, wallet="w1"),
                row(event_key="c", chain_time=97, observed_at=98, wallet="w2", side="sell"),
                row(event_key="d", chain_time=98, observed_at=99, wallet="w3"),
            ),
        )
        w10 = next(w for w in snapshot.windows if w.window_seconds == 10)
        self.assertEqual(w10.unique_wallet_count, 3)
        self.assertAlmostEqual(w10.repeated_wallet_event_share_pct or 0.0, 25.0)
        self.assertAlmostEqual(w10.top1_wallet_event_share_pct or 0.0, 50.0)
        self.assertAlmostEqual(w10.top3_wallet_event_share_pct or 0.0, 100.0)

    def test_partial_wallet_identity_keeps_structure_metrics_missing(self):
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=(
                row(event_key="a", chain_time=95, observed_at=96, wallet="w1"),
                row(event_key="b", chain_time=96, observed_at=97, wallet=None),
            ),
        )
        w10 = next(w for w in snapshot.windows if w.window_seconds == 10)
        self.assertEqual(w10.wallet_identity_coverage_pct, 50.0)
        self.assertIsNone(w10.unique_wallet_count)
        self.assertIsNone(w10.top1_wallet_event_share_pct)
        self.assertIsNone(w10.repeated_wallet_event_share_pct)
        self.assertIn("partial_wallet_identity_coverage", w10.data_quality_flags)

    def test_buy_sell_overlap_is_descriptive_only_and_exact(self):
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=(
                row(event_key="a", chain_time=95, observed_at=96, wallet="w1", side="buy"),
                row(event_key="b", chain_time=96, observed_at=97, wallet="w1", side="sell"),
                row(event_key="c", chain_time=97, observed_at=98, wallet="w2", side="buy"),
            ),
        )
        w10 = next(w for w in snapshot.windows if w.window_seconds == 10)
        self.assertEqual(w10.buy_sell_wallet_overlap_count, 1)
        self.assertAlmostEqual(w10.buy_sell_wallet_overlap_share_pct or 0.0, 50.0)

    def test_derived_dynamics_use_only_preentry_windows(self):
        rows = []
        for i, ts in enumerate(range(91, 100), start=1):
            rows.append(row(event_key=str(i), chain_time=ts, observed_at=ts + 1, wallet=f"w{i}"))
        snapshot = build_exceptional_trade_preentry_snapshot_v56(
            reference=self.reference,
            stored_trades=tuple(rows),
        )
        features = derived_preentry_dynamics_v56(snapshot)
        self.assertIsNotNone(features["event_rate_ratio_10_vs_60"])
        self.assertIsNotNone(features["unique_buy_wallet_rate_ratio_10_vs_60"])

    def test_reference_rejects_impossible_observation_clock(self):
        bad = ExceptionalTradeReferenceV56(
            reference_key="bad",
            acquisition_run_key="run-A",
            wallet_address="w",
            token_mint="TOKEN",
            entry_chain_time=100,
            entry_observed_at=99,
        )
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            build_exceptional_trade_preentry_snapshot_v56(
                reference=bad,
                stored_trades=(),
            )


if __name__ == "__main__":
    unittest.main()
