import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_replay_v0.run import run_replay
from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class LaunchBurstReplayV0Tests(unittest.TestCase):
    def test_replay_uses_first_causally_observed_anchor_and_keeps_strata_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launch.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pump-anchor",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 1000, 2000, "pump"),
                )
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="swap-anchor",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 1100, 2100, "pumpswap"),
                )
                # Later evidence claims an earlier chain start for the Pump stratum. It is
                # audit-visible but must not retroactively mutate the candidate anchor.
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pump-late-earlier",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 990, 2040, "pump"),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="trade-pump",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "buy", 1005, 2005, "W1", 10.0, 1.0, "pump", "TX1"
                    ),
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="trade-swap",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TOKEN", "buy", 1105, 2105, "W2", 20.0, 2.0, "pumpswap", "TX2"
                    ),
                )
                # Extend local evidence coverage beyond both 30s decision cutoffs.
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="coverage-tail",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        "TAIL", "buy", 2200, 2200, "WT", 1.0, 1.0, "pumpswap", "TXT"
                    ),
                )
                report = run_replay(acquisition_run_key="run", window_seconds=30)

        self.assertEqual(report["snapshot_count"], 2)
        self.assertEqual(report["unsupported_venue_count"], 0)
        self.assertEqual(report["strata"], {"pump_launch": 1, "pumpswap_liquidity_launch": 1})
        pump = next(item for item in report["snapshots"] if item["stratum"] == "pump_launch")
        self.assertEqual(pump["anchor_event_key"], "pump-anchor")
        self.assertEqual(pump["chain_t0"], 1000)
        self.assertEqual(pump["event_count"], 1)
        self.assertEqual(report["late_earlier_lifecycle_audit_count"], 1)
        self.assertTrue(
            report["late_earlier_lifecycle_audit"][0]["candidate_snapshot_not_mutated"]
        )
        self.assertFalse(
            report["scientific_scope"]["same_token_cross_venue_trade_mixing_allowed"]
        )

    def test_right_censored_anchor_is_not_emitted_as_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launch.db"
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
                        "TOKEN", "buy", 1005, 2010, "W", 10.0, 1.0, "pump", "TX"
                    ),
                )
                report = run_replay(acquisition_run_key="run", window_seconds=30)

        self.assertEqual(report["snapshot_count"], 0)
        self.assertEqual(report["right_censored_count"], 1)
        self.assertTrue(
            report["scientific_scope"]["future_outcomes_used_for_candidate_selection"] is False
        )


if __name__ == "__main__":
    unittest.main()
