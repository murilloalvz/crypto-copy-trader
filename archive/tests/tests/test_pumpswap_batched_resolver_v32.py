import base64
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from src.pumpswap_batched_resolver_v32 import BatchedBoundedConcurrentResolverV32
from src.pumpswap_stream import PUMPSWAP_PROGRAM_ID, PumpSwapPoolAccount
from src.solana import SolanaRPCError


class _FakeBatchClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if self.fail:
            raise SolanaRPCError("batch failed")
        pools = params[0]
        return {
            "value": [
                {"owner": PUMPSWAP_PROGRAM_ID, "data": [base64.b64encode(b"x").decode(), "base64"]}
                for _ in pools
            ]
        }


class PumpSwapBatchedResolverV32Tests(unittest.TestCase):
    def _resolver(self, client, **kwargs):
        return BatchedBoundedConcurrentResolverV32(
            acquisition_run_key="run",
            commitment="confirmed",
            client=client,
            max_network_hydrations=100,
            max_concurrent_resolutions=18,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=25,
            **kwargs,
        )

    def test_concurrent_unknown_pools_share_one_get_multiple_accounts_call(self):
        client = _FakeBatchClient()
        resolver = self._resolver(client)
        pools = [f"pool-{index}" for index in range(8)]

        with patch(
            "src.pumpswap_batched_resolver_v32.decode_pumpswap_pool_account",
            return_value=PumpSwapPoolAccount(base_mint="base", quote_mint="quote"),
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(resolver._load_pool_account, pools))

        self.assertEqual(len(results), 8)
        self.assertTrue(all(item == PumpSwapPoolAccount("base", "quote") for item in results))
        self.assertEqual(resolver.network_hydration_calls, 8)
        self.assertEqual(resolver.hydration_budget_skips, 0)
        self.assertEqual(resolver.network_batch_calls, 1)
        self.assertEqual(resolver.network_batch_sizes, [8])
        self.assertEqual(len(client.calls), 1)
        method, params = client.calls[0]
        self.assertEqual(method, "getMultipleAccounts")
        self.assertEqual(params[0], pools)

    def test_batch_failure_propagates_to_each_pool_and_populates_negative_cache(self):
        client = _FakeBatchClient(fail=True)
        resolver = self._resolver(client)
        pools = ["pool-a", "pool-b", "pool-c"]

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(resolver._load_pool_account, pool) for pool in pools]
            errors = []
            for future in futures:
                with self.assertRaises(SolanaRPCError) as ctx:
                    future.result()
                errors.append(str(ctx.exception))

        self.assertEqual(errors, ["batch failed"] * 3)
        self.assertEqual(resolver.network_hydration_calls, 3)
        self.assertEqual(resolver.network_batch_calls, 0)
        self.assertEqual(set(resolver._failed_until), set(pools))

    def test_hydration_budget_remains_per_pool_not_per_batch(self):
        client = _FakeBatchClient()
        resolver = BatchedBoundedConcurrentResolverV32(
            acquisition_run_key="run",
            commitment="confirmed",
            client=client,
            max_network_hydrations=2,
            max_concurrent_resolutions=18,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=20,
        )

        with patch(
            "src.pumpswap_batched_resolver_v32.decode_pumpswap_pool_account",
            return_value=PumpSwapPoolAccount(base_mint="base", quote_mint="quote"),
        ):
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(resolver._load_pool_account, f"pool-{i}") for i in range(3)]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except ValueError as exc:
                        outcomes.append(str(exc))

        self.assertEqual(resolver.network_hydration_calls, 2)
        self.assertEqual(resolver.hydration_budget_skips, 1)
        self.assertEqual(sum(isinstance(item, PumpSwapPoolAccount) for item in outcomes), 2)
        self.assertIn("hydration budget exhausted", outcomes)


if __name__ == "__main__":
    unittest.main()
