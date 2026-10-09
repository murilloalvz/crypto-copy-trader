import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_coverage_audit_v0.run import run_coverage_audit
from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class LaunchBurstCoverageAuditV0Tests(unittest.TestCase):
    def test_audit_reports_availability_without_return_or_magnitude_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pump-anchor",
                    source_provider="native",
                    observation=MarketLifecycleObservation("PUMP", 1000, 2000, "pump"),
                )
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="swap-anchor",
                    source_provider="native",
                    observation=MarketLifecycleObservation("SWAP", 1050, 2020, "pumpswap"),
                )
                # Mirrors the current live adapter contract: wallet/transaction are present,
                # while price and USD notional are not inferred.
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="pump-trade-1",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "PUMP", "buy", 1001, 2001, "W1", None, None, "pump", "TX1"
                    ),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="pump-trade-2",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "PUMP", "sell", 1002, 2002, "W2", None, None, "pump", "TX2"
                    ),
                )
                # Extends local evidence coverage beyond both +30s decisions.
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="tail",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TAIL", "buy", 2200, 2200, "WT", None, None, "pumpswap", "TXT"
                    ),
                )
                report = run_coverage_audit(
                    acquisition_run_key="run", window_seconds=30
                )

        self.assertEqual(report["sample"]["complete_snapshot_count"], 2)
        self.assertEqual(report["sample"]["nonempty_snapshot_count"], 1)
        self.assertEqual(report["sample"]["zero_event_snapshot_count"], 1)
        self.assertEqual(
            report["feature_readiness"]["wallet_breadth"],
            "COMPLETE_IN_AUDITED_SAMPLE",
        )
        self.assertEqual(
            report["feature_readiness"]["transaction_breadth"],
            "COMPLETE_IN_AUDITED_SAMPLE",
        )
        self.assertEqual(
            report["feature_readiness"]["notional"], "ABSENT_IN_AUDITED_SAMPLE"
        )
        self.assertEqual(
            report["feature_readiness"]["price"], "ABSENT_IN_AUDITED_SAMPLE"
        )
        self.assertTrue(report["scientific_lock"]["coverage_only"])
        self.assertFalse(report["scientific_lock"]["outcome_horizons_frozen"])
        self.assertFalse(report["scientific_lock"]["future_outcomes_loaded"])

        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("window_return_pct", serialized)
        self.assertNotIn("known_notional_usd", serialized)
        self.assertNotIn("known_notional_buy_share_pct", serialized)
        self.assertNotIn("count_buy_share_pct", serialized)

    def test_right_censoring_is_preserved_from_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="anchor",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 1000, 2000, "pump"),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="short-tail",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "buy", 1005, 2010, "W", None, None, "pump", "TX"
                    ),
                )
                report = run_coverage_audit(
                    acquisition_run_key="run", window_seconds=30
                )

        self.assertEqual(report["sample"]["complete_snapshot_count"], 0)
        self.assertEqual(report["sample"]["right_censored_count"], 1)
        self.assertEqual(report["feature_readiness"]["wallet_breadth"], "NO_NONEMPTY_SAMPLE")


if __name__ == "__main__":
    unittest.main()
