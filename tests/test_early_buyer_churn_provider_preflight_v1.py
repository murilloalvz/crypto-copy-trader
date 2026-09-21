from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.early_buyer_churn_prospective_v1.provider_preflight import (
    FAIL,
    PASS,
    PUBLIC_DRPC_SOLANA_RPC,
    PUBLIC_SOLANA_RPC,
    _is_helius,
    _rpc_candidates,
    run_provider_preflight,
)
from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    EXPECTED_PROTOCOL_HASH,
)


class EarlyBuyerChurnProviderPreflightV1Tests(unittest.TestCase):
    def test_rpc_candidates_exclude_helius_dedupe_and_keep_public_fallback(self):
        candidates = _rpc_candidates(
            primary="https://mainnet.helius-rpc.com/?api-key=secret",
            fallbacks=(
                "https://rpc.example.test",
                "https://rpc.example.test",
                "https://api.helius.xyz/x",
            ),
        )
        self.assertEqual(candidates[0], "https://rpc.example.test")
        self.assertEqual(candidates[-2], PUBLIC_DRPC_SOLANA_RPC)
        self.assertEqual(candidates[-1], PUBLIC_SOLANA_RPC)
        self.assertEqual(len(candidates), 3)
        self.assertTrue(_is_helius("https://mainnet.helius-rpc.com/?api-key=x"))
        self.assertFalse(_is_helius("https://rpc.example.test"))

    def test_preflight_selects_first_healthy_non_helius_candidate(self):
        parity = {
            "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY",
            "exact_parity": True,
            "mismatch_count": 0,
            "compared_complete_episode_count": 2056,
            "protocol_hash_sha256": EXPECTED_PROTOCOL_HASH,
            "run_ids": ["r0", "r1", "r2", "r3", "r4"],
            "artifact": "parity.json",
        }
        protocol = {
            "protocol_hash_sha256": EXPECTED_PROTOCOL_HASH,
        }
        wss = {
            "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
            "source_provider": "solana_public_standard_wss",
            "endpoint_host": "api.mainnet.solana.com",
            "subscription_ack_count": 3,
            "slot_notification_seen": True,
            "http_hydration_used": False,
            "economic_outcomes_opened": False,
        }
        failed = {
            "classification": "FAIL_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT",
            "gates": {"balance_read_ok": False},
            "balances": None,
            "probes": {},
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
        }
        passed = {
            "classification": "PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT",
            "gates": {"all": True},
            "balances": {
                "input_amount_raw": 25_000_000,
                "sol_lamports": 10_000_000,
            },
            "probes": {
                "known_liquid_control": {
                    "status": "COMPLETED",
                    "transaction_present": True,
                    "error_code": None,
                },
                "representative_burst": {
                    "status": "COMPLETED",
                    "transaction_present": True,
                    "error_code": None,
                },
            },
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
            "taker_public_key_sha256": "abc",
        }

        with patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.read_json",
            return_value=protocol,
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_protocol"
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_parity_report",
            return_value=parity,
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.run_market_ingest_preflight",
            return_value=wss,
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.funded.run_preflight",
            side_effect=[failed, passed],
        ) as funded_mock:
            report, selected_url, control = run_provider_preflight(
                parity_report_path=Path("parity.json"),
                jupiter_api_key="key",
                taker_public_key="taker",
                rpc_url="https://rpc-one.example",
                rpc_fallback_urls=("https://rpc-two.example",),
            )

        self.assertEqual(report["classification"], PASS)
        self.assertEqual(selected_url, "https://rpc-two.example")
        self.assertEqual(report["selected_rpc"]["safe_host"], "rpc-two.example")
        self.assertTrue(report["selected_rpc"]["fallback_used"])
        self.assertFalse(report["selected_rpc"]["helius"])
        self.assertEqual(funded_mock.call_count, 2)
        self.assertEqual(control["owner_public_key_sha256"], "abc")
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["fresh_confirmation_consumed"])
        self.assertFalse(report["transaction_signed"])
        self.assertFalse(report["transaction_submitted"])
        self.assertFalse(report["helius_dependency_active"])

    def test_preflight_fails_closed_when_public_wss_is_unhealthy(self):
        parity = {
            "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY",
            "exact_parity": True,
            "mismatch_count": 0,
            "protocol_hash_sha256": EXPECTED_PROTOCOL_HASH,
            "run_ids": ["r0", "r1", "r2", "r3", "r4"],
        }
        protocol = {"protocol_hash_sha256": EXPECTED_PROTOCOL_HASH}
        funded_pass = {
            "classification": "PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT",
            "gates": {"ok": True},
            "balances": {
                "input_amount_raw": 25_000_000,
                "sol_lamports": 10_000_000,
            },
            "probes": {
                "known_liquid_control": {
                    "status": "COMPLETED",
                    "transaction_present": True,
                },
                "representative_burst": {
                    "status": "COMPLETED",
                    "transaction_present": True,
                },
            },
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
            "taker_public_key_sha256": "abc",
        }

        with patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.read_json",
            return_value=protocol,
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_protocol"
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_parity_report",
            return_value=parity,
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.run_market_ingest_preflight",
            side_effect=RuntimeError("wss unavailable"),
        ), patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.funded.run_preflight",
            return_value=funded_pass,
        ):
            report, selected_url, control = run_provider_preflight(
                parity_report_path=Path("parity.json"),
                jupiter_api_key="key",
                taker_public_key="taker",
                rpc_url="https://rpc.example",
                rpc_fallback_urls=(),
            )

        self.assertEqual(report["classification"], FAIL)
        self.assertEqual(selected_url, "https://rpc.example")
        self.assertIsNotNone(control)
        self.assertFalse(report["gates"]["public_standard_wss_usable"])
        self.assertFalse(report["fresh_confirmation_consumed"])


if __name__ == "__main__":
    unittest.main()
