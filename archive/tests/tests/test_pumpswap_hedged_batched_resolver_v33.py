import base64
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.pumpswap_hedged_batched_resolver_v33 import HedgedBatchedBoundedResolverV33
from src.pumpswap_stream import PUMPSWAP_PROGRAM_ID, PumpSwapPoolAccount
from src.solana import SolanaRPCError


def _value():
    return {"owner": PUMPSWAP_PROGRAM_ID, "data": [base64.b64encode(b"x").decode(), "base64"]}


class _BootstrapClient:
    def __init__(self):
        self.timeout = 3
        self.rpc_urls = ["https://slow.invalid", "https://fast.invalid"]


class _EndpointClient:
    calls = []

    def __init__(self, *, rpc_url, timeout, fallback_urls):
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.fallback_urls = fallback_urls

    def call(self, method, params, max_attempts=2):
        type(self).calls.append((self.rpc_url, method, max_attempts))
        if "slow" in self.rpc_url:
            time.sleep(0.05)
            raise SolanaRPCError("slow failed")
        return {"value": [_value() for _ in params[0]]}


class HedgedBatchedResolverV33Tests(unittest.TestCase):
    def setUp(self):
        _EndpointClient.calls = []

    def _resolver(self):
        return HedgedBatchedBoundedResolverV33(
            acquisition_run_key="run",
            commitment="confirmed",
            client=_BootstrapClient(),
            max_network_hydrations=100,
            max_concurrent_resolutions=18,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=5,
            hedge_endpoints=2,
        )

    def test_fast_hedge_wins_without_waiting_for_slow_endpoint_retry_chain(self):
        resolver = self._resolver()
        items = [("pool-a", SimpleNamespace(done=lambda: False, set_result=lambda value: setattr(self, "result_a", value), set_exception=lambda exc: setattr(self, "error_a", exc))),
                 ("pool-b", SimpleNamespace(done=lambda: False, set_result=lambda value: setattr(self, "result_b", value), set_exception=lambda exc: setattr(self, "error_b", exc)))]
        with patch("src.pumpswap_hedged_batched_resolver_v33.SolanaClient", _EndpointClient), patch(
            "src.pumpswap_batched_resolver_v32.decode_pumpswap_pool_account",
            return_value=PumpSwapPoolAccount(base_mint="base", quote_mint="quote"),
        ):
            started = time.monotonic()
            resolver._fetch_batch(items)
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.05)
        self.assertEqual(self.result_a, PumpSwapPoolAccount("base", "quote"))
        self.assertEqual(self.result_b, PumpSwapPoolAccount("base", "quote"))
        self.assertEqual(resolver.hedged_batch_calls, 1)
        self.assertEqual(resolver.hedged_endpoint_requests, 2)
        self.assertEqual(resolver.network_batch_calls, 1)
        self.assertTrue(all(call[2] == 1 for call in _EndpointClient.calls))

    def test_all_hedges_failed_is_explicit(self):
        class _FailClient(_EndpointClient):
            def call(self, method, params, max_attempts=2):
                raise SolanaRPCError(self.rpc_url)

        resolver = self._resolver()
        captured = {}
        future = SimpleNamespace(
            done=lambda: False,
            set_result=lambda value: captured.setdefault("result", value),
            set_exception=lambda exc: captured.setdefault("error", exc),
        )
        with patch("src.pumpswap_hedged_batched_resolver_v33.SolanaClient", _FailClient):
            resolver._fetch_batch([("pool-a", future)])

        self.assertNotIn("result", captured)
        self.assertIsInstance(captured["error"], SolanaRPCError)
        self.assertEqual(resolver.hedged_all_failed, 1)
        self.assertEqual(resolver.network_batch_calls, 0)


if __name__ == "__main__":
    unittest.main()
