from __future__ import annotations

from concurrent.futures import Future
import time
import unittest

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
)
from src.pumpswap_hedged_batched_resolver_v33 import HedgedBatchedBoundedResolverV33
from src.pumpswap_stream import PumpSwapPoolAccount
from src.solana import SolanaRPCError


class _BootstrapClient:
    def __init__(self, *, timeout: float = 0.05):
        self.timeout = timeout
        self.rpc_urls = ["https://first.invalid", "https://second.invalid"]


class DeadlineBoundedResolverV52Tests(unittest.TestCase):
    def _resolver(self, *, timeout: float = 0.05):
        return DeadlineBoundedParallelHedgedResolverV52(
            acquisition_run_key="run-v52",
            commitment="confirmed",
            client=_BootstrapClient(timeout=timeout),
            max_network_hydrations=100,
            max_concurrent_resolutions=18,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=5,
            hedge_endpoints=2,
            hydration_batch_workers=8,
        )

    def test_inherits_single_attempt_endpoint_call_primitive(self):
        self.assertIs(
            DeadlineBoundedParallelHedgedResolverV52._one_endpoint_batch,
            HedgedBatchedBoundedResolverV33._one_endpoint_batch,
        )

    def test_fast_valid_hedge_wins_without_waiting_for_slow_peer(self):
        resolver = self._resolver(timeout=0.05)
        account = PumpSwapPoolAccount(base_mint="base", quote_mint="quote")

        def endpoint(endpoint: str, pools: list[str]):
            if "first" in endpoint:
                time.sleep(0.20)
            return endpoint, [account for _ in pools]

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        started = time.monotonic()
        resolver._fetch_batch([("pool-a", item_future)])
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.12)
        self.assertEqual(item_future.result(timeout=0.01), account)
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 0)
        self.assertEqual(resolver.network_batch_calls, 1)
        resolver.shutdown_parallel_batches(wait=False)

    def test_fast_failure_plus_hung_peer_stops_at_overall_deadline(self):
        resolver = self._resolver(timeout=0.05)

        def endpoint(endpoint: str, pools: list[str]):
            if "first" in endpoint:
                raise SolanaRPCError("first failed")
            time.sleep(0.25)
            return endpoint, [PumpSwapPoolAccount("base", "quote") for _ in pools]

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        started = time.monotonic()
        resolver._fetch_batch([("pool-a", item_future)])
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.04)
        self.assertLess(elapsed, 0.14)
        with self.assertRaises(SolanaRPCError):
            item_future.result(timeout=0.01)
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 1)
        self.assertEqual(resolver.hedged_all_failed, 1)
        self.assertEqual(resolver.network_batch_calls, 0)
        resolver.shutdown_parallel_batches(wait=False)

    def test_valid_response_inside_deadline_is_accepted_after_peer_failure(self):
        resolver = self._resolver(timeout=0.10)
        account = PumpSwapPoolAccount(base_mint="base", quote_mint="quote")

        def endpoint(endpoint: str, pools: list[str]):
            if "first" in endpoint:
                raise SolanaRPCError("first failed")
            time.sleep(0.02)
            return endpoint, [account for _ in pools]

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        resolver._fetch_batch([("pool-a", item_future)])

        self.assertEqual(item_future.result(timeout=0.01), account)
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 0)
        self.assertEqual(snapshot.wall_deadline_seconds, 0.10)
        self.assertEqual(resolver.network_batch_calls, 1)
        resolver.shutdown_parallel_batches(wait=False)

    def test_all_fast_failures_remain_explicit_without_deadline_expiration(self):
        resolver = self._resolver(timeout=0.10)

        def endpoint(endpoint: str, pools: list[str]):
            raise SolanaRPCError(endpoint)

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        resolver._fetch_batch([("pool-a", item_future)])

        with self.assertRaises(SolanaRPCError):
            item_future.result(timeout=0.01)
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 0)
        self.assertEqual(resolver.hedged_all_failed, 1)
        resolver.shutdown_parallel_batches(wait=False)


if __name__ == "__main__":
    unittest.main()
