from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.market_first_live_discovery_v0.contracts import (
    DISCOVERY_DURATION_SECONDS,
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    classify_live_discovery_v0,
    event_is_inside_discovery_window_v0,
    load_bootstrap_evidence_v0,
    validate_bootstrap_before_discovery_start_v0,
)
from benchmarks.market_first_live_discovery_v0.run import (
    ACQUISITION_DURATION_SECONDS,
    ACQUISITION_PADDING_SECONDS,
    _parser,
)
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0
from benchmarks.pumpswap_identity_bootstrap_v0.bootstrap import PASS_CLASSIFICATION as BOOTSTRAP_PASS


class MarketFirstLiveDiscoveryV0Tests(unittest.TestCase):
    def _bootstrap_report(self, directory: Path, *, identity_wall_ns: int = 100) -> Path:
        identities = directory / "pool-identities.jsonl"
        identities.write_text(
            json.dumps(
                {
                    "type": "pumpswap_pool_identity_observation",
                    "bootstrap_version": "pumpswap_identity_bootstrap_v0",
                    "pool": "POOL_A",
                    "base_mint": "BASE_A",
                    "quote_mint": "QUOTE_A",
                    "observed_wall_ns": identity_wall_ns,
                    "observed_slot": 7,
                    "evidence_key": "rpc:7:POOL_A",
                    "source": "helius_getMultipleAccounts_carbon_pool_v0",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        report = directory / "report.json"
        report.write_text(
            json.dumps(
                {
                    "classification": BOOTSTRAP_PASS,
                    "valid_bootstrap": True,
                    "chain_complete_coverage_claimed": False,
                    "run_id": "BOOTSTRAP1",
                    "artifacts": {"identities": str(identities)},
                    "identity": {
                        "observed_pool_count": 1,
                        "decoded_identity_count": 1,
                        "unresolved_pool_count": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        return report

    def test_six_hour_protocol_is_frozen_and_acquisition_has_only_operational_padding(self) -> None:
        self.assertEqual(DISCOVERY_DURATION_SECONDS, 6 * 60 * 60)
        self.assertEqual(ACQUISITION_PADDING_SECONDS, 120)
        self.assertEqual(
            ACQUISITION_DURATION_SECONDS,
            DISCOVERY_DURATION_SECONDS + ACQUISITION_PADDING_SECONDS,
        )
        args = _parser().parse_args(["--bootstrap-report", "bootstrap.json"])
        self.assertFalse(hasattr(args, "duration_seconds"))

    def test_discovery_window_is_half_open_in_wall_clock(self) -> None:
        self.assertFalse(
            event_is_inside_discovery_window_v0(
                999, discovery_start_wall_ns=1000, discovery_close_wall_ns=2000
            )
        )
        self.assertTrue(
            event_is_inside_discovery_window_v0(
                1000, discovery_start_wall_ns=1000, discovery_close_wall_ns=2000
            )
        )
        self.assertTrue(
            event_is_inside_discovery_window_v0(
                1999, discovery_start_wall_ns=1000, discovery_close_wall_ns=2000
            )
        )
        self.assertFalse(
            event_is_inside_discovery_window_v0(
                2000, discovery_start_wall_ns=1000, discovery_close_wall_ns=2000
            )
        )

    def test_bootstrap_identity_must_exist_before_official_discovery_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = self._bootstrap_report(Path(directory), identity_wall_ns=100)
            evidence = load_bootstrap_evidence_v0(report)
            validate_bootstrap_before_discovery_start_v0(
                evidence, discovery_start_wall_ns=101
            )
            with self.assertRaisesRegex(ValueError, "not available before"):
                validate_bootstrap_before_discovery_start_v0(
                    evidence, discovery_start_wall_ns=100
                )

    def test_bootstrap_fail_is_rejected_before_long_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = self._bootstrap_report(Path(directory))
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["classification"] = "FAIL_PUMPSWAP_IDENTITY_BOOTSTRAP_V0"
            payload["valid_bootstrap"] = False
            report.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "real PASS"):
                load_bootstrap_evidence_v0(report)

    def test_live_discovery_classification_requires_every_gate(self) -> None:
        self.assertEqual(
            classify_live_discovery_v0({"one": True, "two": True}),
            PASS_CLASSIFICATION,
        )
        self.assertEqual(
            classify_live_discovery_v0({"one": True, "two": False}),
            FAIL_CLASSIFICATION,
        )
        self.assertEqual(classify_live_discovery_v0({}), FAIL_CLASSIFICATION)

    def test_rotating_trace_chunks_have_one_header_and_footer(self) -> None:
        async def scenario() -> list[Path]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                queue: asyncio.Queue[Path | None] = asyncio.Queue()
                active = asyncio.Event()
                counters = Counters()
                handle = RotatingTraceHandleV0(
                    raw_dir=root,
                    finalized_queue=queue,
                    active_event=active,
                    counters=counters,
                    duration_seconds=123.0,
                    max_bytes=650,
                )
                handle.write(
                    json.dumps(
                        {
                            "type": "transport_session_active",
                            "version": "helius_standard_wss_shadow_trace_v0",
                            "session_key": "session-0001",
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                for index in range(20):
                    handle.write(
                        json.dumps(
                            {
                                "type": "slot_notification",
                                "version": "helius_standard_wss_shadow_trace_v0",
                                "slot": index,
                                "payload": "x" * 80,
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                self.assertTrue(active.is_set())
                handle.close(stop_reason="duration_elapsed")
                paths: list[Path] = []
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    copied = root / f"copy-{len(paths)}.jsonl"
                    copied.write_bytes(item.read_bytes())
                    paths.append(copied)
                snapshots = [path.read_text(encoding="utf-8") for path in paths]
                # Keep contents alive after TemporaryDirectory cleanup.
                result_dir = Path(tempfile.mkdtemp())
                result_paths: list[Path] = []
                for index, text in enumerate(snapshots):
                    out = result_dir / f"chunk-{index}.jsonl"
                    out.write_text(text, encoding="utf-8")
                    result_paths.append(out)
                return result_paths

        paths = asyncio.run(scenario())
        try:
            self.assertGreater(len(paths), 1)
            for path in paths:
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(sum(row.get("type") == "trace_header" for row in rows), 1)
                self.assertEqual(sum(row.get("type") == "trace_footer" for row in rows), 1)
                self.assertFalse(rows[0]["chain_complete_coverage_claimed"])
                self.assertFalse(rows[-1]["chain_complete_coverage_claimed"])
        finally:
            for path in paths:
                path.unlink(missing_ok=True)
            if paths:
                paths[0].parent.rmdir()


if __name__ == "__main__":
    unittest.main()
