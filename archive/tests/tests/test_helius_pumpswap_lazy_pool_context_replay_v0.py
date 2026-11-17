import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.lazy_pool_context_replay import (
    run_replay,
    simulate_delay,
)
from src.carbon_protocol_adapter import PUMPSWAP_PROGRAM_ID


class HeliusPumpSwapLazyPoolContextReplayV0Tests(unittest.TestCase):
    def test_first_miss_is_not_backfilled_and_later_trade_can_hit(self):
        trades = [
            (1_000_000_000, "e1", "POOL"),
            (1_050_000_000, "e2", "POOL"),
            (1_200_000_000, "e3", "POOL"),
        ]
        result = simulate_delay(
            trades,
            initial_pool_availability={},
            lookup_delay_ms=100,
        )
        self.assertEqual(result["lookup_requests"], 1)
        self.assertEqual(result["missing_context_events"], 2)
        self.assertEqual(result["deduped_inflight_misses"], 1)
        self.assertEqual(result["lazy_hit_events"], 1)
        self.assertTrue(result["first_trade_is_never_retroactively_recovered"])

    def test_causal_initial_cache_hits_without_lookup(self):
        trades = [
            (2_000_000_000, "e1", "POOL"),
            (2_100_000_000, "e2", "POOL"),
        ]
        result = simulate_delay(
            trades,
            initial_pool_availability={"POOL": 1_900_000_000},
            lookup_delay_ms=500,
        )
        self.assertEqual(result["initial_cache_hit_events"], 2)
        self.assertEqual(result["lookup_requests"], 0)
        self.assertEqual(result["missing_context_events"], 0)
        self.assertEqual(result["context_coverage_pct"], 100.0)

    def test_future_initial_cache_is_not_backfilled(self):
        trades = [
            (2_000_000_000, "e1", "POOL"),
            (2_100_000_000, "e2", "POOL"),
        ]
        result = simulate_delay(
            trades,
            initial_pool_availability={"POOL": 3_000_000_000},
            lookup_delay_ms=50,
        )
        self.assertEqual(result["initial_cache_hit_events"], 0)
        self.assertEqual(result["lookup_requests"], 1)
        self.assertEqual(result["missing_context_events"], 1)
        self.assertEqual(result["lazy_hit_events"], 1)

    def test_run_replay_uses_actual_carbon_pool_decoder_fields(self):
        manifests = [
            {
                "type": "wss_target_event_manifest",
                "event_key": "e1",
                "transaction_succeeded": True,
                "accepted_for_market_research": True,
                "first_received_wall_ns": 1_000_000_000,
            },
            {
                "type": "wss_target_event_manifest",
                "event_key": "e2",
                "transaction_succeeded": True,
                "accepted_for_market_research": True,
                "first_received_wall_ns": 1_300_000_000,
            },
        ]
        carbon = [
            {
                "type": "carbon_canonical_event",
                "event_key": "e1",
                "status": "decoded",
                "event_type": "pumpswap_buy",
                "pool": "POOL",
            },
            {
                "type": "carbon_canonical_event",
                "event_key": "e2",
                "status": "decoded",
                "event_type": "pumpswap_sell",
                "pool": "POOL",
            },
        ]
        identities = [
            {
                "type": "carbon_pumpswap_pool_account",
                "status": "decoded",
                "pool": "POOL",
                "owner": PUMPSWAP_PROGRAM_ID,
                "rpc_context_slot": 123,
                "received_wall_ns": 900_000_000,
                "base_mint": "BASE",
                "quote_mint": "QUOTE",
                "carbon_decoder_version": "2.0.0",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            carbon_path = root / "carbon.jsonl"
            identities_path = root / "identities.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row) + "\n" for row in manifests), encoding="utf-8"
            )
            carbon_path.write_text(
                "".join(json.dumps(row) + "\n" for row in carbon), encoding="utf-8"
            )
            identities_path.write_text(
                "".join(json.dumps(row) + "\n" for row in identities), encoding="utf-8"
            )
            report = run_replay(
                manifest_path=manifest_path,
                carbon_output_path=carbon_path,
                pool_identities_path=identities_path,
                delays_ms=(100,),
            )
        self.assertTrue(report["valid_replay"])
        self.assertEqual(report["decoded_identity_rows"], 1)
        self.assertEqual(report["initial_identity_rows"], 1)
        self.assertEqual(report["invalid_identity_rows"], 0)
        scenario = report["scenarios"][0]
        self.assertEqual(scenario["pumpswap_trade_events"], 2)
        self.assertEqual(scenario["initial_cache_hit_events"], 2)
        self.assertEqual(scenario["lookup_requests"], 0)
        self.assertEqual(scenario["missing_context_events"], 0)

    def test_run_replay_joins_only_accepted_pumpswap_events(self):
        manifests = [
            {
                "type": "wss_target_event_manifest",
                "event_key": "e1",
                "transaction_succeeded": True,
                "accepted_for_market_research": True,
                "first_received_wall_ns": 1_000_000_000,
            },
            {
                "type": "wss_target_event_manifest",
                "event_key": "e2",
                "transaction_succeeded": True,
                "accepted_for_market_research": True,
                "first_received_wall_ns": 1_300_000_000,
            },
        ]
        carbon = [
            {
                "type": "carbon_canonical_event",
                "event_key": "e1",
                "status": "decoded",
                "event_type": "pumpswap_buy",
                "pool": "POOL",
            },
            {
                "type": "carbon_canonical_event",
                "event_key": "e2",
                "status": "decoded",
                "event_type": "pumpswap_sell",
                "pool": "POOL",
            },
        ]
        identities = [
            {
                "type": "carbon_pumpswap_pool_account",
                "status": "decoded",
                "pool": "OTHER",
                "owner": PUMPSWAP_PROGRAM_ID,
                "rpc_context_slot": 122,
                "received_wall_ns": 900_000_000,
                "base_mint": "BASE_OTHER",
                "quote_mint": "QUOTE_OTHER",
                "carbon_decoder_version": "2.0.0",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            carbon_path = root / "carbon.jsonl"
            identities_path = root / "identities.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row) + "\n" for row in manifests), encoding="utf-8"
            )
            carbon_path.write_text(
                "".join(json.dumps(row) + "\n" for row in carbon), encoding="utf-8"
            )
            identities_path.write_text(
                "".join(json.dumps(row) + "\n" for row in identities), encoding="utf-8"
            )
            report = run_replay(
                manifest_path=manifest_path,
                carbon_output_path=carbon_path,
                pool_identities_path=identities_path,
                delays_ms=(100,),
            )
        self.assertTrue(report["valid_replay"])
        self.assertTrue(report["counterfactual_not_live_measured"])
        scenario = report["scenarios"][0]
        self.assertEqual(scenario["pumpswap_trade_events"], 2)
        self.assertEqual(scenario["missing_context_events"], 1)
        self.assertEqual(scenario["lazy_hit_events"], 1)


if __name__ == "__main__":
    unittest.main()
