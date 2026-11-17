import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.adapt import audit_adapters


PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"


class HeliusStandardWssShadowAdapterAuditV0Tests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows):
        path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _manifest(self, event_key, event_type, received_second, *, log_index=1, received_ns=None):
        return {
            "type": "wss_target_event_manifest",
            "event_key": event_key,
            "event_type": event_type,
            "signature": f"SIG_{event_key}",
            "slot": 123,
            "log_index": log_index,
            "first_received_wall_ns": (
                received_ns if received_ns is not None else received_second * 1_000_000_000
            ),
            "transaction_succeeded": True,
            "accepted_for_market_research": True,
            "transaction_log_complete": True,
        }

    def _footer(self, count):
        return {
            "type": "carbon_decoder_footer",
            "carbon_decoder_version": "2.0.0",
            "carbon_release_commit": "e901103c93833c9c79407cb4321561e30796ad51",
            "input_events": count,
            "output_events": count,
            "decode_failures": 0,
        }

    def _pump_trade(self, event_key="pump:1", timestamp=100):
        return {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": event_key,
            "event_type": "pump_trade",
            "signature": f"SIG_{event_key}",
            "slot": 123,
            "log_index": 1,
            "program_id": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
            "mint": "MINT_A",
            "side": "buy",
            "timestamp": timestamp,
            "quote_mint": "SOL_MINT",
            "quote_amount_raw": 10,
            "virtual_quote_reserves_raw": 100,
        }

    def _pumpswap_trade(self, event_key="swap:1", timestamp=100):
        return {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": event_key,
            "event_type": "pumpswap_buy",
            "signature": f"SIG_{event_key}",
            "slot": 123,
            "log_index": 2,
            "program_id": PUMPSWAP_PROGRAM_ID,
            "pool": "POOL_A",
            "user": "USER_A",
            "side": "buy",
            "timestamp": timestamp,
            "quote_amount_raw": 10,
            "pool_quote_token_reserves_raw": 200,
        }

    def _create_pool(self, event_key="pool:1", timestamp=99):
        return {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": event_key,
            "event_type": "pumpswap_create_pool",
            "signature": f"SIG_{event_key}",
            "slot": 122,
            "log_index": 1,
            "program_id": PUMPSWAP_PROGRAM_ID,
            "pool": "POOL_A",
            "creator": "CREATOR_A",
            "base_mint": "MINT_A",
            "quote_mint": "USDC_MINT",
            "base_mint_decimals": 6,
            "quote_mint_decimals": 6,
            "timestamp": timestamp,
        }

    def _pool_identity(self, *, received_wall_ns):
        return {
            "type": "carbon_pumpswap_pool_account",
            "status": "decoded",
            "pool": "POOL_A",
            "owner": PUMPSWAP_PROGRAM_ID,
            "rpc_context_slot": 120,
            "received_wall_ns": received_wall_ns,
            "base_mint": "MINT_A",
            "quote_mint": "USDC_MINT",
            "carbon_decoder_version": "2.0.0",
        }

    def _run(self, manifests, events, *, pool_identities=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            carbon_path = root / "carbon.jsonl"
            output_path = root / "adapted.jsonl"
            identity_path = root / "pool-identities.jsonl"
            self._write_jsonl(manifest_path, manifests)
            self._write_jsonl(carbon_path, [*events, self._footer(len(events))])
            if pool_identities is not None:
                self._write_jsonl(identity_path, pool_identities)
            report = audit_adapters(
                manifest_path=manifest_path,
                carbon_output_path=carbon_path,
                output_path=output_path,
                pool_identities_path=(identity_path if pool_identities is not None else None),
            )
            output_rows = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return report, output_rows

    def test_pump_adapts_while_pumpswap_without_pool_context_stays_missing(self):
        pump = self._pump_trade()
        swap = self._pumpswap_trade()
        report, rows = self._run(
            [
                self._manifest("pump:1", "pump_trade", 101, log_index=1),
                self._manifest("swap:1", "pumpswap_buy", 102, log_index=2),
            ],
            [pump, swap],
        )

        self.assertTrue(report["carbon_footer_valid"])
        self.assertTrue(report["valid_adapter_audit"])
        self.assertEqual(report["matched_unit_adapted_events"], 1)
        self.assertEqual(report["matched_unit_missing_context_events"], 1)
        self.assertEqual(report["pumpswap_context_coverage_pct"], 0.0)
        self.assertEqual(len(rows), 2)

    def test_causal_create_pool_enables_exact_pumpswap_quote_context(self):
        create_pool = self._create_pool()
        swap = self._pumpswap_trade()
        report, rows = self._run(
            [
                self._manifest("pool:1", "pumpswap_create_pool", 100, log_index=1),
                self._manifest("swap:1", "pumpswap_buy", 101, log_index=2),
            ],
            [create_pool, swap],
        )

        self.assertTrue(report["valid_adapter_audit"])
        self.assertEqual(report["pool_context_observations"], 1)
        self.assertEqual(report["protocol_status_counts"], {"ADAPTED": 1})
        self.assertEqual(report["matched_unit_adapted_events"], 1)
        self.assertEqual(report["pumpswap_context_coverage_pct"], 100.0)
        self.assertEqual(report["matched_unit_context_source_counts"], {"create_pool_event": 1})
        matched = next(row for row in rows if row["stage"] == "matched_unit_flow")
        self.assertEqual(matched["observation"]["quote_asset_key"], "USDC_MINT")
        self.assertEqual(matched["observation"]["token_mint"], "MINT_A")

    def test_future_create_pool_is_not_backfilled_into_earlier_trade(self):
        swap = self._pumpswap_trade()
        create_pool = self._create_pool(timestamp=99)
        report, _rows = self._run(
            [
                self._manifest("swap:1", "pumpswap_buy", 101, log_index=2),
                self._manifest("pool:1", "pumpswap_create_pool", 102, log_index=1),
            ],
            [swap, create_pool],
        )

        self.assertTrue(report["valid_adapter_audit"])
        self.assertEqual(report["pool_context_observations"], 1)
        self.assertEqual(report["matched_unit_adapted_events"], 0)
        self.assertEqual(report["matched_unit_missing_context_events"], 1)
        self.assertEqual(report["pumpswap_context_coverage_pct"], 0.0)

    def test_pool_identity_observed_after_trade_does_not_backfill_source_shadow(self):
        swap = self._pumpswap_trade()
        trade_ns = 101_100_000_000
        identity_ns = 101_900_000_000
        report, _rows = self._run(
            [self._manifest("swap:1", "pumpswap_buy", 101, log_index=2, received_ns=trade_ns)],
            [swap],
            pool_identities=[self._pool_identity(received_wall_ns=identity_ns)],
        )
        self.assertTrue(report["valid_adapter_audit"])
        self.assertEqual(report["pool_identity_observations"], 1)
        self.assertEqual(report["pumpswap_matched_unit_adapted_events"], 0)
        self.assertEqual(report["matched_unit_missing_context_events"], 1)
        self.assertEqual(report["pumpswap_context_coverage_pct"], 0.0)

    def test_pool_identity_available_before_trade_enables_future_shadow_causally(self):
        swap = self._pumpswap_trade()
        identity_ns = 100_500_000_000
        trade_ns = 101_100_000_000
        report, rows = self._run(
            [self._manifest("swap:1", "pumpswap_buy", 101, log_index=2, received_ns=trade_ns)],
            [swap],
            pool_identities=[self._pool_identity(received_wall_ns=identity_ns)],
        )
        self.assertTrue(report["valid_adapter_audit"])
        self.assertEqual(report["pool_identity_rows"], 1)
        self.assertEqual(report["pool_identity_observations"], 1)
        self.assertEqual(report["pool_identity_invalid"], 0)
        self.assertEqual(report["pumpswap_matched_unit_adapted_events"], 1)
        self.assertEqual(report["pumpswap_context_coverage_pct"], 100.0)
        self.assertEqual(report["matched_unit_context_source_counts"], {"pool_account_cache": 1})
        matched = rows[0]
        self.assertEqual(matched["observation"]["quote_asset_key"], "USDC_MINT")

    def test_missing_manifest_fails_closed(self):
        report, _rows = self._run([], [self._pump_trade()])
        self.assertEqual(report["missing_manifest_events"], 1)
        self.assertFalse(report["valid_adapter_audit"])


if __name__ == "__main__":
    unittest.main()
