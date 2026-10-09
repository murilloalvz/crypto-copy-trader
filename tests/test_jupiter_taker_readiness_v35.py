from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import jupiter_taker_readiness_v35 as readiness


class JupiterTakerReadinessV35Tests(unittest.TestCase):
    def _settings(self, taker="Taker1111111111111111111111111111111111"):
        return SimpleNamespace(
            jupiter_taker_public_key=taker,
            rpc_url="https://rpc.invalid",
            rpc_fallback_urls=(),
        )

    def test_empty_taker_is_config_missing_without_rpc(self):
        with patch.object(readiness, "settings", self._settings(taker="")), patch.object(
            readiness, "SolanaClient"
        ) as client_cls:
            output = io.StringIO()
            with redirect_stdout(output):
                code = readiness.inspect_taker_readiness(
                    notional_usd=25.0, min_sol=0.01, timeout_seconds=3
                )
        self.assertEqual(code, 2)
        self.assertIn("classification=CONFIG_MISSING", output.getvalue())
        client_cls.assert_not_called()

    def test_zero_balances_are_explicitly_not_ready(self):
        client = Mock()
        client.call.side_effect = [
            {"value": 0},
            {"value": []},
        ]
        with patch.object(readiness, "settings", self._settings()), patch.object(
            readiness, "SolanaClient", return_value=client
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = readiness.inspect_taker_readiness(
                    notional_usd=25.0, min_sol=0.01, timeout_seconds=3
                )
        text = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("USDC_DEFICIT=25.000000", text)
        self.assertIn("classification=INSUFFICIENT_USDC_AND_SOL", text)

    def test_ready_sums_multiple_usdc_accounts(self):
        client = Mock()
        client.call.side_effect = [
            {"value": 20_000_000},
            {
                "value": [
                    {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": "10000000"}}}}}},
                    {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": "16000000"}}}}}},
                ]
            },
        ]
        with patch.object(readiness, "settings", self._settings()), patch.object(
            readiness, "SolanaClient", return_value=client
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = readiness.inspect_taker_readiness(
                    notional_usd=25.0, min_sol=0.01, timeout_seconds=3
                )
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("USDC=26.000000", text)
        self.assertIn("HAS_SOL=True", text)
        self.assertIn("classification=READY", text)

    def test_rpc_error_is_explicit(self):
        client = Mock()
        client.call.side_effect = readiness.SolanaRPCError("rpc down")
        with patch.object(readiness, "settings", self._settings()), patch.object(
            readiness, "SolanaClient", return_value=client
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = readiness.inspect_taker_readiness(
                    notional_usd=25.0, min_sol=0.01, timeout_seconds=3
                )
        self.assertEqual(code, 3)
        self.assertIn("classification=RPC_ERROR", output.getvalue())


if __name__ == "__main__":
    unittest.main()
