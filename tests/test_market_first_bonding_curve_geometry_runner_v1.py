from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest

from benchmarks.market_first_bonding_curve_geometry_v1.run import run_geometry_v1
from src.market_first_bonding_curve_geometry_v1 import (
    SOL_QUOTE_MINT,
    decode_create_geometry_payload_v1,
)
from src.pump_bonding_stream import (
    PUMP_CREATE_EVENT_DISCRIMINATOR,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _s(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("<I", len(raw)) + raw


def _create_payload() -> bytes:
    return b"".join(
        [
            PUMP_CREATE_EVENT_DISCRIMINATOR,
            _s("n"), _s("s"), _s("u"),
            bytes([1]) * 32,
            bytes([2]) * 32,
            bytes([3]) * 32,
            bytes([4]) * 32,
            struct.pack("<q", 1000),
            struct.pack("<Q", 1_073_000_000_000_000),
            struct.pack("<Q", 30_000_000_000),
            struct.pack("<Q", 793_100_000_000_000),
            struct.pack("<Q", 1_000_000_000_000_000),
        ]
    )


def _trade_payload() -> bytes:
    return b"".join(
        [
            PUMP_TRADE_EVENT_DISCRIMINATOR,
            bytes([1]) * 32,
            struct.pack("<Q", 1_000_000_000),
            struct.pack("<Q", 30_000_000_000_000),
            b"\x01",
            bytes([5]) * 32,
            struct.pack("<q", 1002),
            struct.pack("<Q", 33_000_000_000),
            struct.pack("<Q", 975_000_000_000_000),
            struct.pack("<Q", 3_000_000_000),
            struct.pack("<Q", 695_100_000_000_000),
        ]
    )


class MarketFirstBondingCurveGeometryRunnerV1Tests(unittest.TestCase):
    def test_runner_reconstructs_preserved_payloads_with_exact_identity_parity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)
            chunk = run / "processed-chunks" / "chunk-000001"
            create_payload = _create_payload()
            trade_payload = _trade_payload()
            create_decoded = decode_create_geometry_payload_v1(create_payload)
            assert create_decoded is not None
            mint = create_decoded["mint"]
            create_key = "sig-create:1:pump_create"
            trade_key = "sig-trade:2:pump_trade"
            t0 = 1_000_000_000_000
            trade_wall = t0 + 2_000_000_000

            inputs = [
                {
                    "type": "carbon_decoder_input",
                    "event_key": create_key,
                    "signature": "sig-create",
                    "slot": 1,
                    "log_index": 1,
                    "program_id": "pump",
                    "event_type": "pump_create",
                    "payload_base64": base64.b64encode(create_payload).decode(),
                },
                {
                    "type": "carbon_decoder_input",
                    "event_key": trade_key,
                    "signature": "sig-trade",
                    "slot": 2,
                    "log_index": 2,
                    "program_id": "pump",
                    "event_type": "pump_trade",
                    "payload_base64": base64.b64encode(trade_payload).decode(),
                },
            ]
            manifests = [
                {"event_key": create_key, "first_received_wall_ns": t0},
                {"event_key": trade_key, "first_received_wall_ns": trade_wall},
            ]
            canonical = [
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_key": create_key,
                    "event_type": "pump_create",
                    "mint": mint,
                    "timestamp": 1000,
                },
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_key": trade_key,
                    "event_type": "pump_trade",
                    "mint": mint,
                    "timestamp": 1002,
                    "side": "buy",
                    "quote_mint": SOL_QUOTE_MINT,
                },
            ]
            _write_jsonl(chunk / "carbon-input.jsonl", inputs)
            _write_jsonl(chunk / "target-manifest.jsonl", manifests)
            _write_jsonl(chunk / "carbon-canonical.jsonl", canonical)

            episode_key = "episode-1"
            _write_json(
                run / "route-input-v2.json",
                {
                    "feature_snapshot_frozen_before_provider_quotes": True,
                    "contract_hash_sha256": "contract",
                    "episodes": [
                        {
                            "episode_key": episode_key,
                            "token_mint": mint,
                            "feature_snapshot": {
                                "complete": True,
                                "observed_t0_wall_ns": t0,
                                "decision_cutoff_wall_ns": t0 + 5_000_000_000,
                                "features": {"event_count": 1},
                            },
                            "collection": {},
                        }
                    ],
                },
            )
            _write_json(
                run / "route-result-v2.json",
                {
                    "contract_hash_sha256": "contract",
                    "decisions": [
                        {
                            "episode_key": episode_key,
                            "admitted": True,
                            "status": "ROUTE_CLOSED",
                            "entry_quote": {"provider_price_impact_pct_points": 1.0},
                        }
                    ],
                },
            )
            _write_json(
                run / "sniper-comparison-v1.json",
                {
                    "primary_selector_diagnostics": {
                        "rows": [{"episode_key": episode_key, "selected": True}]
                    }
                },
            )

            report = run_geometry_v1(run_dir=run)

        self.assertEqual(report["classification"], "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1")
        self.assertEqual(report["source_integrity"]["stored_event_count_parity"], True)
        self.assertEqual(report["cohorts"]["baseline_sol_quote"]["count"], 1)
        self.assertEqual(report["cohorts"]["sniper_sol_quote"]["count"], 1)
        self.assertEqual(
            report["rows"][0]["geometry_status"],
            "AVAILABLE_CAUSAL_SOL_BONDING_CURVE_GEOMETRY",
        )
        self.assertIsNotNone(report["rows"][0]["features"]["mf_curve_progress_pct"])


if __name__ == "__main__":
    unittest.main()
