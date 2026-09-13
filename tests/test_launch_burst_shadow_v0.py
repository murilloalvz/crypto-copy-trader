import ast
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_shadow_v0.run import (
    PASS_CLASSIFICATION,
    _assert_output_isolated,
    run_shadow_v0,
)


class LaunchBurstShadowV0Tests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def _fixture(self, root: Path) -> Path:
        processed = root / "processed"
        chunk = processed / "chunk-000001"
        chunk.mkdir(parents=True)

        canonical = [
            {
                "type": "carbon_canonical_event",
                "status": "decoded",
                "event_type": "pump_create",
                "event_key": "create:1",
                "mint": "MINT_A",
                "timestamp": 1000,
            },
            {
                "type": "carbon_canonical_event",
                "status": "decoded",
                "event_type": "pump_trade",
                "event_key": "trade:1",
                "mint": "MINT_A",
                "side": "buy",
                "timestamp": 1004,
                "quote_mint": "SOL",
                "quote_amount_raw": 10,
                "virtual_quote_reserves_raw": 100,
            },
            {
                "type": "carbon_canonical_event",
                "status": "decoded",
                "event_type": "pump_trade",
                "event_key": "trade:2",
                "mint": "MINT_A",
                "side": "sell",
                "timestamp": 1007,
                "quote_mint": "SOL",
                "quote_amount_raw": 4,
                "virtual_quote_reserves_raw": 104,
            },
        ]
        manifest = [
            {"event_key": "create:1", "first_received_wall_ns": 110_000_000_000},
            {"event_key": "trade:1", "first_received_wall_ns": 114_000_000_000},
            {"event_key": "trade:2", "first_received_wall_ns": 117_000_000_000},
        ]
        self._write_jsonl(chunk / "carbon-canonical.jsonl", canonical)
        self._write_jsonl(chunk / "target-manifest.jsonl", manifest)

        identities = root / "bootstrap-identities.jsonl"
        self._write_jsonl(
            identities,
            [
                {
                    "type": "pumpswap_pool_identity_observation",
                    "pool": "POOL_BOOTSTRAP",
                    "base_mint": "BOOT_BASE",
                    "quote_mint": "BOOT_QUOTE",
                    "observed_wall_ns": 90_000_000_000,
                    "observed_slot": 1,
                    "evidence_key": "bootstrap:1",
                    "source": "fixture",
                }
            ],
        )
        bootstrap = root / "bootstrap-report.json"
        self._write_json(
            bootstrap,
            {
                "classification": "PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0",
                "valid_bootstrap": True,
                "chain_complete_coverage_claimed": False,
                "run_id": "bootstrap-fixture",
                "artifacts": {"identities": str(identities)},
                "identity": {
                    "decoded_identity_count": 1,
                    "unresolved_pool_count": 0,
                    "observed_pool_count": 1,
                },
            },
        )

        live = root / "live-report.json"
        self._write_json(
            live,
            {
                "run": {"status": "CLOSED", "acquisition_run_key": "run-fixture"},
                "valid_live_discovery": True,
                "bootstrap_validated": True,
                "discovery_start_wall_ns": 100_000_000_000,
                "discovery_close_wall_ns": 200_000_000_000,
                "acquisition": {"ended_wall_ns": 220_000_000_000},
                "artifacts": {"processed_chunks": str(processed)},
                "bootstrap": {"report_path": str(bootstrap)},
            },
        )
        return live

    def test_horizons_are_causal_and_do_not_leak_future_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            live = self._fixture(Path(directory))
            report = run_shadow_v0(
                live_report_path=live,
                horizons_seconds=(5, 10),
            )
        self.assertEqual(report["classification"], PASS_CLASSIFICATION)
        self.assertEqual(report["safety"]["database_reads"], 0)
        self.assertEqual(report["safety"]["database_writes"], 0)
        self.assertEqual(report["safety"]["network_calls"], 0)
        launch = report["launches"][0]
        self.assertEqual(launch["stratum"], "pump_launch")
        self.assertEqual(launch["horizons"]["5"]["features"]["event_count"], 1)
        self.assertEqual(launch["horizons"]["10"]["features"]["event_count"], 2)
        self.assertAlmostEqual(
            launch["horizons"]["5"]["features"]["signed_flow_over_event_reserve"],
            0.1,
        )

    def test_source_module_has_no_database_or_network_imports(self):
        source_path = Path(__file__).parents[1] / "benchmarks" / "launch_burst_shadow_v0" / "run.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden_prefixes = (
            "src.database",
            "sqlite3",
            "requests",
            "urllib",
            "httpx",
            "aiohttp",
            "socket",
        )
        self.assertFalse(
            any(module.startswith(prefix) for module in imported for prefix in forbidden_prefixes),
            imported,
        )

    def test_output_cannot_overlap_processed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "processed"
            source.mkdir()
            with self.assertRaises(ValueError):
                _assert_output_isolated(source / "report.json", [source])
            _assert_output_isolated(Path(directory) / "separate" / "report.json", [source])

    def test_active_live_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            live = self._fixture(Path(directory))
            payload = json.loads(live.read_text(encoding="utf-8"))
            payload["run"]["status"] = "ACTIVE"
            live.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "run.status=CLOSED"):
                run_shadow_v0(live_report_path=live, horizons_seconds=(5,))


if __name__ == "__main__":
    unittest.main()
