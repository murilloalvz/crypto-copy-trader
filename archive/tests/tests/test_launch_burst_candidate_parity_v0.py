import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_candidate_parity_v0.run import (
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    run_candidate_parity_v0,
)
from src import database
from src.market_observation_store import record_market_lifecycle
from src.market_opportunity_radar import MarketLifecycleObservation


class LaunchBurstCandidateParityV0Tests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _live_report(
        self,
        root: Path,
        *,
        run_key: str,
        canonical: list[dict],
        manifests: list[dict],
    ) -> Path:
        processed = root / "processed"
        chunk = processed / "chunk-0000"
        self._write_jsonl(chunk / "carbon-canonical.jsonl", canonical)
        self._write_jsonl(chunk / "target-manifest.jsonl", manifests)
        report = root / "report.json"
        report.write_text(
            json.dumps(
                {
                    "run": {"acquisition_run_key": run_key, "status": "CLOSED"},
                    "valid_live_discovery": True,
                    "discovery_start_wall_ns": 1_000_000_000_000,
                    "discovery_close_wall_ns": 3_000_000_000_000,
                    "artifacts": {"processed_chunks": str(processed)},
                }
            ),
            encoding="utf-8",
        )
        return report

    def test_exact_db_and_processed_anchor_identity_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "parity.db"
            run_key = "run-pass"
            with patch.object(database, "settings", SimpleNamespace(database_path=db_path)):
                record_market_lifecycle(
                    acquisition_run_key=run_key,
                    event_key="create-1",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 1000, 2000, "pump"),
                )
                report = self._live_report(
                    root,
                    run_key=run_key,
                    canonical=[
                        {
                            "type": "carbon_canonical_event",
                            "status": "decoded",
                            "event_type": "pump_create",
                            "event_key": "create-1",
                            "mint": "TOKEN",
                            "timestamp": 1000,
                        }
                    ],
                    manifests=[
                        {
                            "event_key": "create-1",
                            "first_received_wall_ns": 2_000_100_000_000,
                        }
                    ],
                )
                result = run_candidate_parity_v0(
                    acquisition_run_key=run_key,
                    live_report_path=report,
                )

        self.assertEqual(result["classification"], PASS_CLASSIFICATION)
        self.assertTrue(result["exact_match"])
        self.assertEqual(result["exact_match_count"], 1)
        self.assertEqual(result["diagnostics"]["same_second_multi_candidate_count"], 0)

    def test_same_second_receive_order_collision_fails_when_sqlite_selects_different_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "collision.db"
            run_key = "run-collision"
            with patch.object(database, "settings", SimpleNamespace(database_path=db_path)):
                # Both rows persist at observed_at=2000. SQLite orders ties by chain time,
                # while processed evidence preserves the true nanosecond receive order.
                record_market_lifecycle(
                    acquisition_run_key=run_key,
                    event_key="received-first",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 200, 2000, "pump"),
                )
                record_market_lifecycle(
                    acquisition_run_key=run_key,
                    event_key="received-second-earlier-chain",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 100, 2000, "pump"),
                )
                report = self._live_report(
                    root,
                    run_key=run_key,
                    canonical=[
                        {
                            "type": "carbon_canonical_event",
                            "status": "decoded",
                            "event_type": "pump_create",
                            "event_key": "received-first",
                            "mint": "TOKEN",
                            "timestamp": 200,
                        },
                        {
                            "type": "carbon_canonical_event",
                            "status": "decoded",
                            "event_type": "pump_create",
                            "event_key": "received-second-earlier-chain",
                            "mint": "TOKEN",
                            "timestamp": 100,
                        },
                    ],
                    manifests=[
                        {
                            "event_key": "received-first",
                            "first_received_wall_ns": 2_000_100_000_000,
                        },
                        {
                            "event_key": "received-second-earlier-chain",
                            "first_received_wall_ns": 2_000_900_000_000,
                        },
                    ],
                )
                result = run_candidate_parity_v0(
                    acquisition_run_key=run_key,
                    live_report_path=report,
                )

        self.assertEqual(result["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(result["exact_match"])
        self.assertEqual(result["mismatch_count"], 1)
        self.assertEqual(result["diagnostics"]["same_second_multi_candidate_count"], 1)
        mismatch = result["mismatches"][0]
        self.assertEqual(mismatch["processed_anchor"]["event_key"], "received-first")
        self.assertEqual(
            mismatch["db_anchor"]["event_key"],
            "received-second-earlier-chain",
        )

    def test_candidate_missing_from_processed_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "missing.db"
            run_key = "run-missing"
            with patch.object(database, "settings", SimpleNamespace(database_path=db_path)):
                record_market_lifecycle(
                    acquisition_run_key=run_key,
                    event_key="db-only",
                    source_provider="native",
                    observation=MarketLifecycleObservation("TOKEN", 1000, 2000, "pump"),
                )
                report = self._live_report(root, run_key=run_key, canonical=[], manifests=[])
                result = run_candidate_parity_v0(
                    acquisition_run_key=run_key,
                    live_report_path=report,
                )

        self.assertEqual(result["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(result["exact_match"])
        self.assertEqual(result["missing_in_processed_count"], 1)


if __name__ == "__main__":
    unittest.main()
