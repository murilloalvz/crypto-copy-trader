import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_run_inventory_v0.run import (
    UNKNOWN_COMPLETION,
    build_run_inventory,
    select_latest_closed_launch_run_key,
)
from src import database
from src.market_activity_discovery_run_v0 import (
    MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
    interrupt_market_activity_discovery_run_v0,
)
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class LaunchBurstRunInventoryV0Tests(unittest.TestCase):
    def _life(self, run_key: str, token: str, observed: int, venue: str = "pump") -> None:
        record_market_lifecycle(
            acquisition_run_key=run_key,
            event_key=f"{run_key}-life",
            source_provider="native",
            observation=MarketLifecycleObservation(token, observed - 10, observed, venue),
        )

    def test_only_authoritative_closed_run_is_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                start_closed = 1000
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="closed-run",
                    cohort_key="closed-cohort",
                    started_at=start_closed,
                )
                self._life("closed-run", "A", 1100)
                close_market_activity_discovery_run_v0(
                    acquisition_run_key="closed-run",
                    observed_at=start_closed
                    + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
                )

                start_open = 2000
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="newer-open-run",
                    cohort_key="open-cohort",
                    started_at=start_open,
                )
                self._life("newer-open-run", "B", 2100, "pumpswap")

                start_interrupted = 3000
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="newest-interrupted-run",
                    cohort_key="interrupted-cohort",
                    started_at=start_interrupted,
                )
                self._life("newest-interrupted-run", "C", 3100)
                interrupt_market_activity_discovery_run_v0(
                    acquisition_run_key="newest-interrupted-run",
                    observed_at=start_interrupted + 100,
                    reason="synthetic interruption",
                )

                report = build_run_inventory()
                selected = select_latest_closed_launch_run_key()

        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["eligible_closed_run_count"], 1)
        self.assertEqual(report["latest_eligible_closed_run_key"], "closed-run")
        self.assertEqual(selected, "closed-run")
        by_key = {item["acquisition_run_key"]: item for item in report["runs"]}
        self.assertTrue(by_key["closed-run"]["eligible_for_auto_select"])
        self.assertEqual(by_key["closed-run"]["completion_status"], "CLOSED")
        self.assertFalse(by_key["newer-open-run"]["eligible_for_auto_select"])
        self.assertEqual(by_key["newer-open-run"]["completion_status"], "OPEN")
        self.assertFalse(by_key["newest-interrupted-run"]["eligible_for_auto_select"])
        self.assertEqual(
            by_key["newest-interrupted-run"]["completion_status"], "INTERRUPTED"
        )

    def test_observation_run_without_registry_row_stays_unknown_and_ineligible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._life("orphan-run", "TOKEN", 100)
                report = build_run_inventory()
                with self.assertRaises(RuntimeError):
                    select_latest_closed_launch_run_key()

        item = report["runs"][0]
        self.assertEqual(item["completion_status"], UNKNOWN_COMPLETION)
        self.assertFalse(item["completion_status_authoritative"])
        self.assertFalse(item["eligible_for_auto_select"])

    def test_closed_registry_without_lifecycle_is_not_launch_burst_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                start = 500
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="closed-no-life",
                    cohort_key="closed-no-life-cohort",
                    started_at=start,
                )
                record_market_trade(
                    acquisition_run_key="closed-no-life",
                    event_key="trade",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "buy", 501, 510, "W", None, None, "pump", "TX"
                    ),
                )
                close_market_activity_discovery_run_v0(
                    acquisition_run_key="closed-no-life",
                    observed_at=start + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
                )
                report = build_run_inventory()

        item = report["runs"][0]
        self.assertEqual(item["completion_status"], "CLOSED")
        self.assertFalse(item["has_launch_lifecycle"])
        self.assertFalse(item["eligible_for_auto_select"])


if __name__ == "__main__":
    unittest.main()
