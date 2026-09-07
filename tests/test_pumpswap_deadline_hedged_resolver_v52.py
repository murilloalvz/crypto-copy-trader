from __future__ import annotations

from concurrent.futures import Future
import threading
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
    def _resolver(self, *, timeout: float = 0.05, batch_workers: int = 8):
        return DeadlineBoundedParallelHedgedResolverV52(
            acquisition_run_key="run-v52",
            commitment="confirmed",
            client=_BootstrapClient(timeout=timeout),
            max_network_hydrations=100,
            max_concurrent_resolutions=18,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=5,
            hedge_endpoints=2,
            hydration_batch_workers=batch_workers,
        )

    def test_inherits_single_attempt_endpoint_call_primitive(self):
        self.assertIs(
            DeadlineBoundedParallelHedgedResolverV52._one_endpoint_batch,
            HedgedBatchedBoundedResolverV33._one_endpoint_batch,
        )

    def test_fast_valid_winner_is_published_before_slow_peer_cleanup(self):
        resolver = self._resolver(timeout=0.10)
        account = PumpSwapPoolAccount(base_mint="base", quote_mint="quote")
        slow_started = threading.Event()
        release_slow = threading.Event()

        def endpoint(endpoint: str, pools: list[str]):
            if "first" in endpoint:
                self.assertTrue(slow_started.wait(timeout=0.20))
                return endpoint, [account for _ in pools]
            slow_started.set()
            self.assertTrue(release_slow.wait(timeout=1.0))
            return endpoint, [account for _ in pools]

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        worker = threading.Thread(
            target=resolver._fetch_batch,
            args=([("pool-a", item_future)],),
            daemon=True,
        )
        started = time.monotonic()
        worker.start()

        self.assertEqual(item_future.result(timeout=0.20), account)
        decision_elapsed = time.monotonic() - started
        self.assertLess(decision_elapsed, 0.10)
        self.assertTrue(worker.is_alive(), "batch slot must remain held during loser cleanup")

        release_slow.set()
        worker.join(timeout=0.50)
        self.assertFalse(worker.is_alive())
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 0)
        self.assertEqual(resolver.network_batch_calls, 1)
        self.assertEqual(len(snapshot.cleanup_seconds), 1)
        self.assertGreater(snapshot.cleanup_seconds[0], 0.0)
        resolver.shutdown_parallel_batches(wait=True)

    def test_deadline_publishes_error_while_running_transport_keeps_parallel_slot(self):
        resolver = self._resolver(timeout=0.05, batch_workers=1)
        account = PumpSwapPoolAccount(base_mint="base", quote_mint="quote")
        slow_started = threading.Event()
        release_slow = threading.Event()
        second_batch_started = threading.Event()

        def endpoint(endpoint: str, pools: list[str]):
            if pools[0] == "pool-a":
                if "first" in endpoint:
                    self.assertTrue(slow_started.wait(timeout=0.20))
                    raise SolanaRPCError("first failed")
                slow_started.set()
                self.assertTrue(release_slow.wait(timeout=1.0))
                return endpoint, [account for _ in pools]
            second_batch_started.set()
            return endpoint, [account for _ in pools]

        resolver._one_endpoint_batch = endpoint
        first_future: Future = Future()
        started = time.monotonic()
        resolver._batch_queue.put(("pool-a", first_future))

        with self.assertRaises(SolanaRPCError):
            first_future.result(timeout=0.20)
        decision_elapsed = time.monotonic() - started
        self.assertGreaterEqual(decision_elapsed, 0.035)
        self.assertLess(decision_elapsed, 0.15)

        second_future: Future = Future()
        resolver._batch_queue.put(("pool-b", second_future))
        self.assertFalse(
            second_batch_started.wait(timeout=0.05),
            "a timed-out orphan transport must not silently free the only v41 batch slot",
        )

        release_slow.set()
        self.assertTrue(second_batch_started.wait(timeout=0.30))
        self.assertEqual(second_future.result(timeout=0.30), account)
        resolver._batch_queue.join()

        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 1)
        self.assertEqual(resolver.hedged_all_failed, 1)
        self.assertEqual(resolver.network_batch_calls, 1)
        self.assertGreater(snapshot.cleanup_seconds[0], 0.04)
        parallel = resolver.parallel_batch_snapshot()
        self.assertEqual(parallel.inflight_high_water, 1)
        resolver.shutdown_parallel_batches(wait=True)

    def test_timeout_marks_every_item_explicitly_unresolved(self):
        resolver = self._resolver(timeout=0.05)
        release = threading.Event()

        def endpoint(_endpoint: str, pools: list[str]):
            self.assertTrue(release.wait(timeout=1.0))
            return "late", [PumpSwapPoolAccount("base", "quote") for _ in pools]

        resolver._one_endpoint_batch = endpoint
        first: Future = Future()
        second: Future = Future()
        worker = threading.Thread(
            target=resolver._fetch_batch,
            args=([("pool-a", first), ("pool-b", second)],),
            daemon=True,
        )
        worker.start()

        with self.assertRaises(SolanaRPCError):
            first.result(timeout=0.20)
        with self.assertRaises(SolanaRPCError):
            second.result(timeout=0.02)
        self.assertTrue(worker.is_alive())

        release.set()
        worker.join(timeout=0.50)
        self.assertFalse(worker.is_alive())
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 1)
        self.assertEqual(resolver.network_batch_calls, 0)
        resolver.shutdown_parallel_batches(wait=True)

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
        resolver.shutdown_parallel_batches(wait=True)

    def test_all_fast_failures_remain_explicit_without_deadline_expiration(self):
        resolver = self._resolver(timeout=0.10)

        def endpoint(endpoint: str, _pools: list[str]):
            raise SolanaRPCError(endpoint)

        resolver._one_endpoint_batch = endpoint
        item_future: Future = Future()
        resolver._fetch_batch([("pool-a", item_future)])

        with self.assertRaises(SolanaRPCError):
            item_future.result(timeout=0.01)
        snapshot = resolver.hedge_deadline_snapshot_v52()
        self.assertEqual(snapshot.deadline_expirations, 0)
        self.assertEqual(resolver.hedged_all_failed, 1)
        resolver.shutdown_parallel_batches(wait=True)


if __name__ == "__main__":
    unittest.main()
