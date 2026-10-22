import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.launch_burst_prospective_route_live_v3.live import (
    DEFAULT_CONTRACT,
    EXPECTED_ROUTE_CONTRACT_HASH,
    OnlinePumpFeatureState,
    _build_decoder,
    _decoder_binary_path,
    _dispatch_snapshot,
    _read_json,
    _run_decoder_binary,
    _systems_summary,
)
from src.launch_burst_route_paper_v2 import selection_decision


class LaunchBurstProspectiveRouteLiveV3Tests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def _selected_snapshot(self) -> dict:
        return {
            "stratum": "pump_launch",
            "complete": True,
            "observed_t0": 110,
            "observed_t0_wall_ns": 110_000_000_000,
            "evidence_window_seconds": 5,
            "decision_as_of": 115,
            "decision_cutoff_wall_ns": 115_000_000_000,
            "features": {"signed_flow_over_event_reserve": 0.10},
        }

    def test_decoder_build_is_one_preflight_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "decoder-build"
            binary = _decoder_binary_path(target.resolve())
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"fixture")
            completed = subprocess.CompletedProcess(
                args=["cargo"], returncode=0, stdout="", stderr=""
            )
            with patch(
                "benchmarks.launch_burst_prospective_route_live_v3.live.subprocess.run",
                return_value=completed,
            ) as run:
                report = _build_decoder(cargo="cargo", target_dir=target)

        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[0:3], ["cargo", "build", "--release"])
        self.assertNotIn("run", command)
        self.assertEqual(report["invocations"], 1)
        self.assertTrue(report["binary_exists"])

    def test_hot_path_executes_direct_binary_without_cargo_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / ("decoder.exe" if os.name == "nt" else "decoder")
            binary.write_bytes(b"fixture")
            input_path = root / "input.jsonl"
            output_path = root / "output.jsonl"
            self._write_jsonl(
                input_path,
                [{"type": "carbon_decoder_input", "event_key": "e1"}],
            )
            self._write_jsonl(
                output_path,
                [
                    {
                        "type": "carbon_decoder_footer",
                        "input_events": 1,
                        "output_events": 1,
                        "decode_failures": 0,
                    }
                ],
            )
            completed = subprocess.CompletedProcess(
                args=[str(binary)], returncode=0, stdout="", stderr=""
            )
            with patch(
                "benchmarks.launch_burst_prospective_route_live_v3.live.subprocess.run",
                return_value=completed,
            ) as run:
                report = _run_decoder_binary(
                    binary=binary,
                    carbon_input_path=input_path,
                    carbon_output_path=output_path,
                )

        command = run.call_args.args[0]
        self.assertEqual(command[0], str(binary))
        self.assertNotIn("cargo", " ".join(command).lower())
        self.assertTrue(report["direct_binary"])
        self.assertFalse(report["cargo_run_used"])
        self.assertTrue(report["footer_accounting_valid"])

    def test_online_snapshot_keeps_frozen_5s_feature_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            chunk = Path(directory) / "chunk-000001"
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
                    "event_key": "trade:future",
                    "mint": "MINT_A",
                    "side": "sell",
                    "timestamp": 1007,
                    "quote_mint": "SOL",
                    "quote_amount_raw": 50,
                    "virtual_quote_reserves_raw": 100,
                },
            ]
            manifest = [
                {"event_key": "create:1", "first_received_wall_ns": 110_250_000_000},
                {"event_key": "trade:1", "first_received_wall_ns": 114_000_000_000},
                {"event_key": "trade:future", "first_received_wall_ns": 117_000_000_000},
            ]
            self._write_jsonl(chunk / "carbon-canonical.jsonl", canonical)
            self._write_jsonl(chunk / "target-manifest.jsonl", manifest)

            state = OnlinePumpFeatureState()
            state.ingest_processed_chunk(chunk)
            self.assertEqual(
                state.ready_snapshots(coverage_through_wall_ns=115_249_999_999), []
            )
            ready = state.ready_snapshots(
                coverage_through_wall_ns=115_250_000_000
            )

        self.assertEqual(len(ready), 1)
        token, snapshot = ready[0]
        self.assertEqual(token, "MINT_A")
        self.assertEqual(snapshot["decision_cutoff_wall_ns"], 115_250_000_000)
        self.assertEqual(snapshot["features"]["event_count"], 1)
        self.assertAlmostEqual(
            snapshot["features"]["signed_flow_over_event_reserve"], 0.1
        )

    def test_systems_only_never_invokes_provider_factory_or_opens_outcome(self):
        contract = _read_json(DEFAULT_CONTRACT)

        def forbidden_provider(**_kwargs):
            raise AssertionError("provider must not be called in systems-only mode")

        async def scenario():
            with patch(
                "benchmarks.launch_burst_prospective_route_live_v3.live.time.time_ns",
                return_value=116_000_000_000,
            ):
                return await _dispatch_snapshot(
                    episode_key="pump:MINT:110000000000",
                    token_mint="MINT",
                    snapshot=self._selected_snapshot(),
                    contract=contract,
                    systems_only=True,
                    provider_factory=forbidden_provider,
                    provider_kwargs={"should_not": "matter"},
                )

        immediate, task = asyncio.run(scenario())
        self.assertIsNone(task)
        self.assertIsNotNone(immediate)
        self.assertTrue(immediate["selected"])
        self.assertFalse(immediate["provider_calls_enabled"])
        self.assertFalse(immediate["economic_outcome_opened"])
        self.assertNotIn("quotes", immediate)
        self.assertNotIn("net_route_return_pct", immediate)

    def test_systems_summary_counts_deadline_miss(self):
        summary = _systems_summary(
            [
                {
                    "selected": True,
                    "decision_cutoff_wall_ns": 100,
                    "snapshot_dispatch_lag_ms": 1.0,
                    "would_meet_entry_ready": False,
                    "would_meet_entry_deadline": False,
                },
                {
                    "selected": True,
                    "decision_cutoff_wall_ns": 200,
                    "snapshot_dispatch_lag_ms": 2.0,
                    "would_meet_entry_ready": True,
                    "would_meet_entry_deadline": True,
                },
            ]
        )
        self.assertEqual(summary["selected_count"], 2)
        self.assertEqual(summary["selected_before_entry_ready"], 1)
        self.assertEqual(summary["selected_before_deadline"], 1)
        self.assertEqual(summary["selected_missed_deadline"], 1)

    def test_contract_hash_threshold_and_pumpswap_hold_remain_frozen(self):
        contract = _read_json(DEFAULT_CONTRACT)
        self.assertEqual(
            contract["contract_hash_sha256"], EXPECTED_ROUTE_CONTRACT_HASH
        )
        predicate = contract["selection_rule"]["predicates"][0]
        self.assertEqual(predicate["feature"], "signed_flow_over_event_reserve")
        self.assertEqual(predicate["op"], ">=")
        self.assertEqual(predicate["value"], 0.08)
        self.assertEqual(contract["primary_evidence"]["window_seconds"], 5)
        self.assertEqual(contract["entry"]["latency_seconds"], 2)
        self.assertEqual(contract["exit"]["horizon_seconds"], 60)

        pumpswap = dict(self._selected_snapshot())
        pumpswap["stratum"] = "pumpswap_liquidity_launch"
        admitted, reason = selection_decision(pumpswap, contract)
        self.assertFalse(admitted)
        self.assertEqual(reason, "STRATUM_HOLD")


if __name__ == "__main__":
    unittest.main()
