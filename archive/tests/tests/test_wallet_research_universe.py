import unittest
from datetime import datetime, timezone

from src.discovery.models import TraderSnapshot
from src.wallet_research_universe import (
    frequency_bucket,
    research_rejection_reasons,
    select_research_universe,
)


NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def snapshot(address: str, *, trades: int, roi: float = 20.0, pnl: float = 1000.0):
    return TraderSnapshot(
        address=address,
        realized_pnl_usd=pnl,
        volume_usd=10_000.0,
        trading_days=12,
        profitable_days=8,
        losing_days=4,
        max_single_day_pnl_usd=200.0,
        roi_pct=roi,
        invested_usd=5_000.0,
        proceeds_usd=6_000.0,
        buys=trades // 2,
        sells=trades - trades // 2,
        trades=trades,
        tokens_traded=20,
        profitable_tokens=12,
        losing_tokens=8,
        closed_tokens=20,
        win_rate_pct=60.0,
        first_trade_ms=NOW_MS - 20 * 86_400_000,
        last_trade_ms=NOW_MS - 86_400_000,
        pnl_mode="strict",
    )


class WalletResearchUniverseTests(unittest.TestCase):
    def test_frequency_buckets_keep_high_frequency_as_research(self):
        self.assertEqual(frequency_bucket(300), "moderate")
        self.assertEqual(frequency_bucket(1000), "active")
        self.assertEqual(frequency_bucket(1001), "high_frequency")
        self.assertEqual(frequency_bucket(3001), "ultra_high_frequency")

    def test_high_frequency_is_not_rejected_by_research_quality_gate(self):
        item = snapshot("A" * 44, trades=5000)
        self.assertEqual(
            research_rejection_reasons(item, now_ms=NOW_MS),
            (),
        )

    def test_research_gate_still_rejects_nonpositive_roi(self):
        item = snapshot("B" * 44, trades=200, roi=0.0)
        self.assertIn(
            "roi_non_positive",
            research_rejection_reasons(item, now_ms=NOW_MS),
        )

    def test_shortlist_round_robins_frequency_archetypes(self):
        items = [
            snapshot("A" * 44, trades=100),
            snapshot("B" * 44, trades=600),
            snapshot("C" * 44, trades=1500),
            snapshot("D" * 44, trades=5000),
        ]
        report = select_research_universe(items, shortlist_limit=4, now=NOW)
        self.assertEqual(report.eligible_count, 4)
        self.assertEqual(
            [entry.frequency_bucket for entry in report.shortlist],
            ["moderate", "active", "high_frequency", "ultra_high_frequency"],
        )
        self.assertIn(
            "high_frequency_not_directly_copyable",
            report.shortlist[2].flags,
        )


if __name__ == "__main__":
    unittest.main()
