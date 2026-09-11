import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_episode_adapter_v0 import (
    persist_indexed_kernel_trigger_as_market_episode_v0,
)
from src.market_opportunity_radar import (
    MarketLifecycleObservation,
    MarketRadarConfig,
    MarketTradeObservation,
)
from src.market_signal_kernel import IndexedMarketSignalKernel


class MarketActivityDiscoveryEpisodeAdapterV0Tests(unittest.TestCase):
    def _kernel(self):
        return IndexedMarketSignalKernel(
            MarketRadarConfig(
                fast_window_seconds=30,
                baseline_horizon_seconds=300,
                min_fast_events=1,
                min_unique_wallets=1,
                min_unique_transactions=1,
                min_baseline_events=1,
                min_activity_acceleration_ratio=1.0,
                fresh_market_max_age_seconds=120,
                pressure_threshold_pct=20.0,
            )
        )

    def _trade(self, *, chain_time, observed_at, wallet, tx):
        return MarketTradeObservation(
            token_mint="MINT_A",
            side="buy",
            chain_time=chain_time,
            observed_at=observed_at,
            wallet_address=wallet,
            notional_usd=10.0,
            price_usd=1.0,
            venue="pump",
            transaction_key=tx,
        )

    def _prime_lifecycle(self, kernel):
        kernel.ingest_lifecycle(
            MarketLifecycleObservation(
                token_mint="MINT_A",
                market_started_at=990,
                observed_at=999,
                venue="pump",
            )
        )

    def test_first_kernel_trigger_persists_episode_and_emits_discovery_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adapter.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                kernel = self._kernel()
                self._prime_lifecycle(kernel)
                trade = self._trade(chain_time=1000, observed_at=1000, wallet="W1", tx="TX1")
                trigger = kernel.ingest_trade(trade)
                self.assertIsNotNone(trigger)
                result = persist_indexed_kernel_trigger_as_market_episode_v0(
                    acquisition_run_key="RUN1",
                    source_event_key="EVENT1",
                    source_trade=trade,
                    trigger=trigger,
                )

        self.assertIsNotNone(result.discovery_handoff)
        self.assertEqual(result.episode.first_trigger_observed_at, trigger.as_of)
        self.assertEqual(result.episode.first_trigger_chain_time, trigger.features.chain_as_of)
        self.assertEqual(result.discovery_handoff.decision_as_of, trigger.as_of)
        self.assertEqual(result.discovery_handoff.chain_as_of, trigger.features.chain_as_of)
        self.assertEqual(result.provider_calls_performed, 0)

    def test_continuation_trigger_maps_same_episode_but_emits_no_second_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuation.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                kernel = self._kernel()
                self._prime_lifecycle(kernel)
                first_trade = self._trade(chain_time=1000, observed_at=1000, wallet="W1", tx="TX1")
                first_trigger = kernel.ingest_trade(first_trade)
                first = persist_indexed_kernel_trigger_as_market_episode_v0(
                    acquisition_run_key="RUN1",
                    source_event_key="EVENT1",
                    source_trade=first_trade,
                    trigger=first_trigger,
                )
                second_trade = self._trade(chain_time=1001, observed_at=1001, wallet="W2", tx="TX2")
                second_trigger = kernel.ingest_trade(second_trade)
                second = persist_indexed_kernel_trigger_as_market_episode_v0(
                    acquisition_run_key="RUN1",
                    source_event_key="EVENT2",
                    source_trade=second_trade,
                    trigger=second_trigger,
                )

        self.assertEqual(first.episode.episode_key, second.episode.episode_key)
        self.assertIsNotNone(first.discovery_handoff)
        self.assertIsNone(second.discovery_handoff)

    def test_late_chain_insert_uses_kernel_chain_anchor_not_source_trade_chain_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chain-anchor.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                kernel = self._kernel()
                self._prime_lifecycle(kernel)
                high = self._trade(chain_time=1100, observed_at=1000, wallet="W1", tx="TX1")
                self.assertIsNotNone(kernel.ingest_trade(high))
                late = self._trade(chain_time=1050, observed_at=1001, wallet="W2", tx="TX2")
                trigger = kernel.ingest_trade(late)
                self.assertIsNotNone(trigger)
                self.assertEqual(trigger.features.chain_as_of, 1100)
                result = persist_indexed_kernel_trigger_as_market_episode_v0(
                    acquisition_run_key="RUN1",
                    source_event_key="EVENT2",
                    source_trade=late,
                    trigger=trigger,
                )

        self.assertEqual(late.chain_time, 1050)
        self.assertEqual(result.episode.first_trigger_chain_time, 1100)
        self.assertEqual(result.discovery_handoff.chain_as_of, 1100)

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                kernel = self._kernel()
                self._prime_lifecycle(kernel)
                trade = self._trade(chain_time=1000, observed_at=1000, wallet="W1", tx="TX1")
                trigger = kernel.ingest_trade(trade)
                kwargs = dict(
                    acquisition_run_key="RUN1",
                    source_event_key="EVENT1",
                    source_trade=trade,
                    trigger=trigger,
                )
                first = persist_indexed_kernel_trigger_as_market_episode_v0(**kwargs)
                second = persist_indexed_kernel_trigger_as_market_episode_v0(**kwargs)

        self.assertEqual(first, second)

    def test_mismatched_local_trigger_clock_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-clock.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                kernel = self._kernel()
                self._prime_lifecycle(kernel)
                trade = self._trade(chain_time=1000, observed_at=1000, wallet="W1", tx="TX1")
                trigger = kernel.ingest_trade(trade)
                bad = replace(trigger, as_of=1001)
                with self.assertRaises(ValueError):
                    persist_indexed_kernel_trigger_as_market_episode_v0(
                        acquisition_run_key="RUN1",
                        source_event_key="EVENT1",
                        source_trade=trade,
                        trigger=bad,
                    )


if __name__ == "__main__":
    unittest.main()
