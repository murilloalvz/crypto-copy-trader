import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_episode_store import load_market_opportunity_episode_triggers
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_radar_bridge import evaluate_market_token


class MarketRadarBridgeTests(unittest.TestCase):
    def _seed_fresh_market(self, *, transaction_keys: list[str]) -> None:
        record_market_lifecycle(
            acquisition_run_key="run",
            event_key="create",
            source_provider="native",
            observation=MarketLifecycleObservation("T", 930, 935, "pump_bonding_curve"),
        )
        for i in range(6):
            record_market_trade(
                acquisition_run_key="run",
                event_key=f"trade-{i}",
                source_provider="native",
                observation=MarketTradeObservation(
                    token_mint="T",
                    side="buy",
                    chain_time=975 + i * 4,
                    observed_at=976 + i * 4,
                    wallet_address=f"W{i}",
                    venue="pump_bonding_curve",
                    transaction_key=transaction_keys[i],
                ),
            )

    def test_bridge_opens_episode_without_freezing_decision_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_fresh_market(transaction_keys=["a", "a", "b", "c", "d", "d"])
                hit = evaluate_market_token(
                    acquisition_run_key="run",
                    token_mint="T",
                    as_of=1000,
                    trigger_key="trigger-1",
                    trigger_chain_time=995,
                    venue="pump_bonding_curve",
                )
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.trigger.trigger_kind, "fresh_market_burst")
                self.assertIsNone(hit.episode.decision_as_of)
                triggers = load_market_opportunity_episode_triggers(hit.episode.episode_key)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].trigger_key, "trigger-1")

    def test_bridge_is_idempotent_for_same_market_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_fresh_market(transaction_keys=["a", "a", "b", "c", "d", "d"])
                first = evaluate_market_token(
                    acquisition_run_key="run",
                    token_mint="T",
                    as_of=1000,
                    trigger_key="trigger-1",
                    trigger_chain_time=995,
                    venue="pump_bonding_curve",
                )
                second = evaluate_market_token(
                    acquisition_run_key="run",
                    token_mint="T",
                    as_of=1000,
                    trigger_key="trigger-1",
                    trigger_chain_time=995,
                    venue="pump_bonding_curve",
                )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.episode.episode_key, second.episode.episode_key)

    def test_one_transaction_with_many_events_does_not_open_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_fresh_market(transaction_keys=["one"] * 6)
                hit = evaluate_market_token(
                    acquisition_run_key="run",
                    token_mint="T",
                    as_of=1000,
                    trigger_key="trigger-1",
                    trigger_chain_time=995,
                    venue="pump_bonding_curve",
                )
        self.assertIsNone(hit)


if __name__ == "__main__":
    unittest.main()
