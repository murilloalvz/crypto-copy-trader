import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_run_inventory_v0.run import (
    UNKNOWN_COMPLETION,
    build_run_inventory,
)
from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class LaunchBurstRunInventoryV0Tests(unittest.TestCase):
    def test_inventory_never_promotes_recent_run_to_complete_without_authoritative_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="older-run",
                    event_key="older-life",
                    source_provider="native",
                    observation=MarketLifecycleObservation("A", 100, 110, "pump"),
                )
                record_market_trade(
                    acquisition_run_key="older-run",
                    event_key="older-trade",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "A", "buy", 101, 111, "W1", None, None, "pump", "TX1"
                    ),
                )
                # The newer run is intentionally partial: recency must not imply completion.
                record_market_lifecycle(
                    acquisition_run_key="newer-partial-run",
                    event_key="new-life",
                    source_provider="native",
                    observation=MarketLifecycleObservation("B", 200, 210, "pumpswap"),
                )
                report = build_run_inventory()

        self.assertEqual(report["run_count"], 2)
        self.assertFalse(report["auto_selection_performed"])
        self.assertEqual(report["runs"][0]["acquisition_run_key"], "newer-partial-run")
        for item in report["runs"]:
            self.assertEqual(item["completion_status"], UNKNOWN_COMPLETION)
            self.assertFalse(item["eligible_for_auto_select"])

    def test_inventory_reports_run_scoped_counts_and_venues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="life",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 100, 110, "pump"),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="trade-1",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "buy", 101, 111, "W1", None, None, "pump", "TX1"
                    ),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="trade-2",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "sell", 102, 112, "W2", None, None, "pumpswap", "TX2"
                    ),
                )
                report = build_run_inventory()

        item = report["runs"][0]
        self.assertEqual(item["trade_rows"], 2)
        self.assertEqual(item["trade_tokens"], 1)
        self.assertEqual(item["lifecycle_rows"], 1)
        self.assertEqual(item["lifecycle_tokens"], 1)
        self.assertEqual(item["venues"], ["pump", "pumpswap"])
        self.assertTrue(item["has_launch_lifecycle"])


if __name__ == "__main__":
    unittest.main()
