from __future__ import annotations

import unittest

from src.pumpswap_demand_only_prefetch_v54 import DemandOnlyPumpSwapIngressPrefetchV54
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class _ForbiddenResolver:
    async def resolve(self, *args, **kwargs):  # pragma: no cover - failure path only
        raise AssertionError("v54 speculative prefetch must never call resolver.resolve")


class DemandOnlyPumpSwapIngressPrefetchV54Tests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_records_candidates_without_creating_resolver_work(self):
        prefetch = DemandOnlyPumpSwapIngressPrefetchV54()
        notification = PumpSwapLogNotification(
            signature="sig-v54",
            slot=1,
            observed_at=100,
            trade_events=(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="pool-a",
                    user="wallet-a",
                    timestamp=100,
                    base_amount_raw=1,
                    quote_amount_raw=2,
                ),
                PumpSwapTradeEvent(
                    side="sell",
                    pool="pool-a",
                    user="wallet-b",
                    timestamp=100,
                    base_amount_raw=3,
                    quote_amount_raw=4,
                ),
                PumpSwapTradeEvent(
                    side="buy",
                    pool="pool-b",
                    user="wallet-c",
                    timestamp=100,
                    base_amount_raw=5,
                    quote_amount_raw=6,
                ),
            ),
        )

        prefetch.schedule(notification, _ForbiddenResolver())
        await prefetch.drain(timeout_seconds=0.01)

        snapshot = prefetch.snapshot_v54()
        self.assertEqual(snapshot.notifications_seen, 1)
        self.assertEqual(snapshot.candidate_pools, 2)
        self.assertEqual(snapshot.scheduled, 0)
        self.assertEqual(snapshot.skipped_speculative, 2)
        self.assertEqual(snapshot.active, 0)
        self.assertEqual(prefetch.snapshot_v53().admitted, 0)
        self.assertEqual(prefetch.snapshot_v53().skipped_capacity, 0)
        self.assertEqual(prefetch.snapshot_v53().skipped_pool_busy, 0)


if __name__ == "__main__":
    unittest.main()
