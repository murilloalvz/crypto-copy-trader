from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from benchmarks.launch_burst_sniper_v1 import run_transport_amended_v0 as transport


class SniperV1StandardWssTransportAmendmentTests(
    unittest.IsolatedAsyncioTestCase
):
    def test_http_to_ws_preserves_host_path_and_query(self):
        self.assertEqual(
            transport._http_to_ws(
                "https://example.invalid/v2/key?x=1"
            ),
            "wss://example.invalid/v2/key?x=1",
        )
        self.assertEqual(
            transport._http_to_ws(
                "http://localhost:8899"
            ),
            "ws://localhost:8899",
        )

    def test_candidate_order_prefers_rpc_before_helius_last_resort(self):
        rows = transport._candidate_urls(
            explicit_wss_url="",
            rpc_url="https://primary.invalid/v2/key",
            rpc_fallback_urls=(
                "https://fallback.invalid/token",
            ),
            helius_api_key="abc",
        )
        self.assertEqual(
            [item[0] for item in rows],
            [
                "solana_rpc_primary",
                "solana_rpc_fallback_1",
                "helius_direct_last_resort",
            ],
        )
        self.assertEqual(
            transport._host(rows[0][1]),
            "primary.invalid",
        )

    async def test_resolver_skips_failed_primary_and_selects_fallback(self):
        async def fake_probe(url: str):
            if "primary.invalid" in url:
                raise RuntimeError("quota exhausted")
            return {
                "subscription_acks": 3,
                "labels": [
                    "pump_logs",
                    "pumpswap_logs",
                    "slot",
                ],
                "all_required_acks": True,
            }

        with patch.object(
            transport,
            "_probe",
            new=AsyncMock(side_effect=fake_probe),
        ):
            report, selected = await transport.resolve_transport(
                explicit_wss_url="",
                rpc_url="https://primary.invalid/v2/key",
                rpc_fallback_urls=(
                    "https://fallback.invalid/token",
                ),
                helius_api_key="",
            )

        self.assertEqual(
            report["classification"],
            transport.PASS,
        )
        self.assertEqual(
            report["selected_candidate"],
            "solana_rpc_fallback_1",
        )
        self.assertEqual(
            report["selected_host"],
            "fallback.invalid",
        )
        self.assertEqual(
            selected,
            "wss://fallback.invalid/token",
        )
        self.assertFalse(
            report["economic_outcomes_opened"]
        )
        self.assertFalse(report["selector_changed"])
        self.assertFalse(report["thresholds_changed"])
        self.assertFalse(report["benchmark_changed"])

    def test_wrapper_only_arg_is_not_forwarded_to_frozen_runner(self):
        self.assertEqual(
            transport._strip_wrapper_only_args(
                [
                    "--duration-seconds",
                    "900",
                    "--transport-preflight-only",
                    "--env-file",
                    "x.env",
                ]
            ),
            [
                "--duration-seconds",
                "900",
                "--env-file",
                "x.env",
            ],
        )


if __name__ == "__main__":
    unittest.main()
