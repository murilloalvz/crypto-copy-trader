from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_capacity_harness_v0.shadow_pumpswap_causal import (
    apply_recorded_identity_refresh_v0,
    load_recorded_identity_refresh_v0,
)
from benchmarks.market_first_live_discovery_v0.pipeline import LiveDiscoveryPipelineStateV0


def _write_gzip_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class MarketFirstShadowPumpSwapCausalV0Tests(unittest.TestCase):
    def test_recorded_refresh_preserves_original_identity_clock_and_applies_after_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw" / "chunk-000001.jsonl.gz"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"placeholder")
            chunk_dir = root / "processed" / raw.stem
            _write_gzip_jsonl(
                chunk_dir / "pool-account-input.jsonl.gz",
                [
                    {
                        "type": "pumpswap_pool_account_input",
                        "pool": "POOL1",
                    }
                ],
            )
            _write_gzip_jsonl(
                chunk_dir / "pool-account-output.jsonl.gz",
                [
                    {
                        "type": "pumpswap_pool_identity_decode",
                        "status": "ADAPTED",
                        "pool": "POOL1",
                        "base_mint": "BASE",
                        "quote_mint": "QUOTE",
                        "observed_wall_ns": 123456789,
                        "observed_slot": 42,
                        "evidence_key": "rpc-evidence-1",
                        "source": "recorded-rpc",
                    }
                ],
            )

            refresh = load_recorded_identity_refresh_v0(
                processed_root=root / "processed",
                raw_trace_path=raw,
            )
            self.assertTrue(refresh["evidence_present"])
            self.assertEqual(refresh["attempted_pools"], ("POOL1",))
            self.assertEqual(len(refresh["identities"]), 1)
            self.assertEqual(refresh["identities"][0].observed_wall_ns, 123456789)

            baseline = LiveDiscoveryPipelineStateV0()
            shadow = LiveDiscoveryPipelineStateV0()
            result = apply_recorded_identity_refresh_v0(
                baseline_state=baseline,
                shadow_state=shadow,
                refresh=refresh,
            )
            self.assertEqual(result["identity_count"], 1)
            self.assertEqual(result["identity_evidence_keys"], ["rpc-evidence-1"])
            self.assertIn("POOL1", baseline.account_lookup_attempted_pools)
            self.assertIn("POOL1", shadow.account_lookup_attempted_pools)
            self.assertEqual(baseline.pool_identities["POOL1"][0].observed_wall_ns, 123456789)
            self.assertEqual(shadow.pool_identities["POOL1"][0].evidence_key, "rpc-evidence-1")

    def test_no_recorded_refresh_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "chunk-000002.jsonl.gz"
            raw.write_bytes(b"placeholder")
            refresh = load_recorded_identity_refresh_v0(
                processed_root=root / "processed",
                raw_trace_path=raw,
            )
            self.assertFalse(refresh["evidence_present"])
            self.assertEqual(refresh["attempted_pools"], ())
            self.assertEqual(refresh["identities"], ())

    def test_partial_recorded_refresh_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "chunk-000003.jsonl.gz"
            raw.write_bytes(b"placeholder")
            chunk_dir = root / "processed" / raw.stem
            _write_gzip_jsonl(
                chunk_dir / "pool-account-input.jsonl.gz",
                [{"type": "pumpswap_pool_account_input", "pool": "POOL1"}],
            )
            with self.assertRaises(RuntimeError):
                load_recorded_identity_refresh_v0(
                    processed_root=root / "processed",
                    raw_trace_path=raw,
                )


if __name__ == "__main__":
    unittest.main()
