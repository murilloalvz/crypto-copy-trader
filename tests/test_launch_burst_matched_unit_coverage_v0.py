import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.launch_burst_matched_unit_coverage_v0.run import (
    run_matched_unit_coverage_audit,
)


class LaunchBurstMatchedUnitCoverageV0Tests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _bootstrap(self, root: Path, *, discovery_start_ns: int) -> Path:
        directory = root / "bootstrap"
        directory.mkdir(parents=True)
        identities = directory / "pool-identities.jsonl"
        self._write_jsonl(
            identities,
            [
                {
                    "type": "pumpswap_pool_identity_observation",
                    "pool": "UNRELATED",
                    "base_mint": "BASE",
                    "quote_mint": "QUOTE",
                    "observed_wall_ns": discovery_start_ns - 100,
                    "observed_slot": 1,
                    "evidence_key": "bootstrap:unrelated",
                    "source": "test",
                }
            ],
        )
        report = directory / "report.json"
        report.write_text(
            json.dumps(
                {
                    "run_id": "bootstrap-run",
                    "classification": "PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0",
                    "valid_bootstrap": True,
                    "chain_complete_coverage_claimed": False,
                    "artifacts": {"identities": str(identities)},
                    "identity": {
                        "decoded_identity_count": 1,
                        "unresolved_pool_count": 0,
                        "observed_pool_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return report

    def _live_report(
        self,
        root: Path,
        *,
        processed: Path,
        bootstrap_report: Path,
        discovery_start_ns: int,
        discovery_close_ns: int,
        ended_ns: int,
    ) -> Path:
        report = root / "live-report.json"
        report.write_text(
            json.dumps(
                {
                    "run": {
                        "acquisition_run_key": "live-run",
                        "status": "CLOSED",
                    },
                    "bootstrap_validated": True,
                    "discovery_start_wall_ns": discovery_start_ns,
                    "discovery_close_wall_ns": discovery_close_ns,
                    "acquisition": {"ended_wall_ns": ended_ns},
                    "bootstrap": {"report_path": str(bootstrap_report)},
                    "artifacts": {"processed_chunks": str(processed)},
                }
            ),
            encoding="utf-8",
        )
        return report

    def test_pump_launch_has_matched_unit_coverage_without_exposing_amount_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = 1_900_000_000_000
            close = 3_000_000_000_000
            processed = root / "processed"
            chunk = processed / "chunk-0000"
            canonical = [
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_type": "pump_create",
                    "event_key": "create",
                    "mint": "TOKEN",
                    "timestamp": 1000,
                },
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_type": "pump_trade",
                    "event_key": "trade",
                    "mint": "TOKEN",
                    "side": "buy",
                    "quote_mint": "SOL",
                    "timestamp": 1005,
                    "quote_amount_raw": 123456,
                    "virtual_quote_reserves_raw": 999999,
                },
            ]
            manifests = [
                {"event_key": "create", "first_received_wall_ns": 2_000_000_000_000},
                {"event_key": "trade", "first_received_wall_ns": 2_005_000_000_000},
            ]
            self._write_jsonl(chunk / "carbon-canonical.jsonl", canonical)
            self._write_jsonl(chunk / "target-manifest.jsonl", manifests)
            bootstrap_report = self._bootstrap(root, discovery_start_ns=start)
            live_report = self._live_report(
                root,
                processed=processed,
                bootstrap_report=bootstrap_report,
                discovery_start_ns=start,
                discovery_close_ns=close,
                ended_ns=3_200_000_000_000,
            )

            result = run_matched_unit_coverage_audit(
                live_report_path=live_report,
                window_seconds=30,
            )

        self.assertEqual(result["trade_adaptation"]["decoded_trade_count"], 1)
        self.assertEqual(result["trade_adaptation"]["adapted_count"], 1)
        self.assertEqual(result["launch_sample"]["complete_anchor_count"], 1)
        pump = result["strata"]["pump_launch"]
        self.assertEqual(pump["complete_launch_count"], 1)
        self.assertEqual(pump["launches_with_matched_unit_evidence"], 1)
        self.assertEqual(pump["launch_coverage_pct"], 100.0)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("123456", serialized)
        self.assertNotIn("999999", serialized)
        self.assertNotIn("signed_quote_over_first_reserve_pct", serialized)
        self.assertFalse(result["scientific_lock"]["raw_quote_amount_values_reported"])
        self.assertFalse(result["scientific_lock"]["flow_over_reserve_values_reported"])

    def test_dynamic_identity_after_chunk_never_backfills_earlier_pumpswap_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = 1_900_000_000_000
            close = 4_000_000_000_000
            processed = root / "processed"

            chunk0 = processed / "chunk-0000"
            self._write_jsonl(
                chunk0 / "carbon-canonical.jsonl",
                [
                    {
                        "type": "carbon_canonical_event",
                        "status": "decoded",
                        "event_type": "pumpswap_buy",
                        "event_key": "early-trade",
                        "pool": "POOL",
                        "side": "buy",
                        "timestamp": 1000,
                        "quote_amount_raw": 10,
                        "pool_quote_token_reserves_raw": 1000,
                    }
                ],
            )
            self._write_jsonl(
                chunk0 / "target-manifest.jsonl",
                [
                    {
                        "event_key": "early-trade",
                        "first_received_wall_ns": 2_000_000_000_000,
                    }
                ],
            )
            self._write_jsonl(
                chunk0 / "pool-account-output.jsonl",
                [
                    {
                        "type": "pumpswap_pool_identity_decode",
                        "status": "ADAPTED",
                        "pool": "POOL",
                        "base_mint": "TOKEN",
                        "quote_mint": "SOL",
                        "observed_wall_ns": 2_100_000_000_000,
                        "observed_slot": 10,
                        "evidence_key": "rpc:POOL",
                        "source": "test-rpc",
                    }
                ],
            )

            chunk1 = processed / "chunk-0001"
            self._write_jsonl(
                chunk1 / "carbon-canonical.jsonl",
                [
                    {
                        "type": "carbon_canonical_event",
                        "status": "decoded",
                        "event_type": "pumpswap_buy",
                        "event_key": "later-trade",
                        "pool": "POOL",
                        "side": "buy",
                        "timestamp": 1001,
                        "quote_amount_raw": 11,
                        "pool_quote_token_reserves_raw": 1001,
                    }
                ],
            )
            self._write_jsonl(
                chunk1 / "target-manifest.jsonl",
                [
                    {
                        "event_key": "later-trade",
                        "first_received_wall_ns": 2_200_000_000_000,
                    }
                ],
            )

            bootstrap_report = self._bootstrap(root, discovery_start_ns=start)
            live_report = self._live_report(
                root,
                processed=processed,
                bootstrap_report=bootstrap_report,
                discovery_start_ns=start,
                discovery_close_ns=close,
                ended_ns=4_200_000_000_000,
            )
            result = run_matched_unit_coverage_audit(
                live_report_path=live_report,
                window_seconds=30,
            )

        self.assertEqual(result["trade_adaptation"]["decoded_trade_count"], 2)
        self.assertEqual(result["trade_adaptation"]["adapted_count"], 1)
        self.assertEqual(result["trade_adaptation"]["statuses"].get("MISSING_CONTEXT"), 1)
        self.assertEqual(result["trade_adaptation"]["statuses"].get("ADAPTED"), 1)
        self.assertEqual(result["source_integrity"]["dynamic_identity_count"], 1)

    def test_open_live_run_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed"
            processed.mkdir()
            bootstrap_report = self._bootstrap(root, discovery_start_ns=1_000)
            report = root / "live-report.json"
            report.write_text(
                json.dumps(
                    {
                        "run": {"acquisition_run_key": "run", "status": "OPEN"},
                        "bootstrap_validated": True,
                        "discovery_start_wall_ns": 1_000,
                        "discovery_close_wall_ns": 2_000,
                        "acquisition": {"ended_wall_ns": 3_000},
                        "bootstrap": {"report_path": str(bootstrap_report)},
                        "artifacts": {"processed_chunks": str(processed)},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                run_matched_unit_coverage_audit(live_report_path=report)


if __name__ == "__main__":
    unittest.main()
