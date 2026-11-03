from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from benchmarks.early_buyer_churn_prospective_v1.provider_preflight import (
    FAIL,
    PASS,
    PUBLIC_MAGICBLOCK_SOLANA_RPC,
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
    def test_rpc_candidates_exclude_helius_dedupe_and_keep_public_fallbacks(self):
        candidates = _rpc_candidates(
            primary="https://mainnet.helius-rpc.com/?api-key=secret",
            fallbacks=(
                "https://rpc.example.test",
                "https://rpc.example.test",
                "https://api.helius.xyz/x",
            ),
        )
        self.assertEqual(candidates[0], "https://rpc.example.test")
        self.assertEqual(candidates[-3], PUBLIC_MAGICBLOCK_SOLANA_RPC)
        self.assertEqual(candidates[-2], PUBLIC_DRPC_SOLANA_RPC)
        self.assertEqual(candidates[-1], PUBLIC_SOLANA_RPC)
        self.assertEqual(len(candidates), 4)
        self.assertTrue(_is_helius("https://mainnet.helius-rpc.com/?api-key=x"))
        self.assertFalse(_is_helius("https://rpc.example.test"))

    def _base_patches(self, *, wss):
        protocol = {"protocol_hash_sha256": EXPECTED_PROTOCOL_HASH}
        parity = {
            "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY",
            "exact_parity": True,
            "mismatch_count": 0,
            "compared_complete_episode_count": 2056,
            "protocol_hash_sha256": EXPECTED_PROTOCOL_HASH,
            "run_ids": ["r0", "r1", "r2", "r3", "r4"],
            "artifact": "parity.json",
        }
        fixture = {
            "fixture_hash_sha256": "fixture",
            "input_mint": "USDC",
            "minimum_input_amount_raw": 25_000_000,
            "minimum_sol_lamports": 5_000_000,
            "slippage_bps": 100,
            "control_output_mint": "WSOL",
            "representative_burst_output_mint": "BURST",
        }
        contract = {"contract_hash_sha256": "contract"}
        return (
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.read_json",
                return_value=protocol,
            ),
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_protocol"
            ),
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.validate_parity_report",
                return_value=parity,
            ),
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.funded._read_json",
                side_effect=[fixture, contract],
            ),
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.funded._validate_fixture",
                return_value={"frozen": True},
            ),
            patch(
                "benchmarks.early_buyer_churn_prospective_v1.provider_preflight.run_market_ingest_preflight",
                side_effect=wss if isinstance(wss, Exception) else None,
                return_value=None if isinstance(wss, Exception) else wss,
            ),
        )

    def test_preflight_selects_first_healthy_public_control_candidate(self):
        wss = {
            "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
            "source_provider": "solana_public_standard_wss",
            "endpoint_host": "api.mainnet.solana.com",
            "subscription_ack_count": 3,
            "slot_notification_seen": True,
            "http_hydration_used": False,
            "economic_outcomes_opened": False,
        }
        failed = (
            {
                "classification": "FAIL_PUBLIC_CONTROL_DISCOVERY",
                "safe_host": "rpc-one.example",
                "public_control": None,
                "known_liquid_control": {"status": "NOT_RUN"},
                "representative_burst": {"status": "NOT_RUN"},
                "economic_outcomes_opened": False,
                "provider_execute_called": False,
            },
            None,
            None,
        )
        passed = (
            {
                "classification": "PASS_PUBLIC_CONTROL_AND_JUPITER_ASSEMBLY",
                "safe_host": "rpc-two.example",
                "public_control": {
                    "owner_public_key_sha256": "abc",
                    "token_account_amount_raw": 30_000_000,
                    "sol_lamports": 10_000_000,
                    "address_redacted": True,
                },
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
                "economic_outcomes_opened": False,
                "provider_execute_called": False,
            },
            "CONTROL_PUBLIC_KEY",
            {
                "owner_public_key_sha256": "abc",
                "token_account_amount_raw": 30_000_000,
                "sol_lamports": 10_000_000,
                "provider_preflight": PASS,
                "rpc_safe_host": "rpc-two.example",
                "candidates_checked": 2,
            },
        )

        patches = self._base_patches(wss=wss)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight._candidate_public_control_probe",
            side_effect=[failed, passed],
        ) as probe:
            report, selected_url, control_taker, control_meta = run_provider_preflight(
                parity_report_path=Path("parity.json"),
                jupiter_api_key="key",
                rpc_url="https://rpc-one.example",
                rpc_fallback_urls=("https://rpc-two.example",),
            )

        self.assertEqual(report["classification"], PASS)
        self.assertEqual(selected_url, "https://rpc-two.example")
        self.assertEqual(control_taker, "CONTROL_PUBLIC_KEY")
        self.assertEqual(control_meta["owner_public_key_sha256"], "abc")
        self.assertEqual(report["selected_rpc"]["safe_host"], "rpc-two.example")
        self.assertTrue(report["selected_rpc"]["fallback_used"])
        self.assertFalse(report["selected_rpc"]["helius"])
        self.assertTrue(report["gates"]["public_funded_control_discovered"])
        self.assertTrue(report["control"]["address_redacted"])
        self.assertNotIn("CONTROL_PUBLIC_KEY", str(report))
        self.assertEqual(probe.call_count, 2)
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["fresh_confirmation_consumed"])
        self.assertFalse(report["transaction_signed"])
        self.assertFalse(report["transaction_submitted"])
        self.assertFalse(report["helius_dependency_active"])

    def test_preflight_fails_closed_when_public_wss_is_unhealthy(self):
        selected = (
            {
                "classification": "PASS_PUBLIC_CONTROL_AND_JUPITER_ASSEMBLY",
                "safe_host": "rpc.example",
                "public_control": {
                    "owner_public_key_sha256": "abc",
                    "token_account_amount_raw": 30_000_000,
                    "sol_lamports": 10_000_000,
                    "address_redacted": True,
                },
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
                "economic_outcomes_opened": False,
                "provider_execute_called": False,
            },
            "CONTROL_PUBLIC_KEY",
            {
                "owner_public_key_sha256": "abc",
                "token_account_amount_raw": 30_000_000,
                "sol_lamports": 10_000_000,
                "provider_preflight": PASS,
                "rpc_safe_host": "rpc.example",
                "candidates_checked": 1,
            },
        )

        patches = self._base_patches(wss=RuntimeError("wss unavailable"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
            "benchmarks.early_buyer_churn_prospective_v1.provider_preflight._candidate_public_control_probe",
            return_value=selected,
        ):
            report, selected_url, control_taker, control_meta = run_provider_preflight(
                parity_report_path=Path("parity.json"),
                jupiter_api_key="key",
                rpc_url="https://rpc.example",
                rpc_fallback_urls=(),
            )

        self.assertEqual(report["classification"], FAIL)
        self.assertEqual(selected_url, "https://rpc.example")
        self.assertEqual(control_taker, "CONTROL_PUBLIC_KEY")
        self.assertIsNotNone(control_meta)
        self.assertFalse(report["gates"]["public_standard_wss_usable"])
        self.assertFalse(report["fresh_confirmation_consumed"])


if __name__ == "__main__":
    unittest.main()
