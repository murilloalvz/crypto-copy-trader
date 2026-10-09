from __future__ import annotations

from unittest.mock import patch
import unittest

from benchmarks.launch_burst_control_taker_sim_v0 import run_helius_holders as holders


class LaunchBurstHeliusHolderDiscoveryV1Tests(unittest.TestCase):
    def fixture(self) -> dict:
        return {
            "input_mint": "USDC_MINT",
            "minimum_input_amount_raw": 25_000_000,
            "minimum_sol_lamports": 10_000_000,
        }

    def test_discovery_batches_owner_sol_balance_reads(self):
        calls: list[tuple[str, str, object]] = []

        def rpc(url, method, params):
            calls.append((url, method, params))
            if method == "getTokenAccounts":
                return {
                    "token_accounts": [
                        {"owner": "OwnerA", "amount": 100_000_000},
                        {"owner": "OwnerB", "amount": 90_000_000},
                        {"owner": "OwnerC", "amount": 80_000_000},
                    ]
                }
            if method == "getMultipleAccounts":
                return {
                    "value": [
                        {"lamports": 1_000_000},
                        {"lamports": 20_000_000},
                        {"lamports": 30_000_000},
                    ]
                }
            raise AssertionError(f"unexpected method {method}")

        with patch.object(holders, "_helius_url", return_value="helius-rpc"), patch.object(
            holders.ft, "_rpc_call", side_effect=rpc
        ):
            owner, meta = holders._discover_control_via_helius_holders(
                fixture=self.fixture(),
                rpc_url="primary-rpc",
            )

        self.assertEqual(owner, "OwnerB")
        self.assertEqual(meta["balance_batches"], 1)
        self.assertEqual(meta["candidates_checked"], 3)
        methods = [method for _, method, _ in calls]
        self.assertEqual(methods.count("getTokenAccounts"), 1)
        self.assertEqual(methods.count("getMultipleAccounts"), 1)
        self.assertNotIn("getBalance", methods)

    def test_owner_balance_batch_falls_back_to_helius(self):
        calls: list[tuple[str, str]] = []

        def rpc(url, method, params):
            del params
            calls.append((url, method))
            if url == "primary-rpc":
                raise RuntimeError("primary unavailable")
            return {"value": [{"lamports": 12_000_000}]}

        with patch.object(holders.ft, "_rpc_call", side_effect=rpc):
            result = holders._batched_sol_balances(
                primary_rpc_url="primary-rpc",
                fallback_rpc_url="helius-rpc",
                owners=["OwnerA"],
            )

        self.assertEqual(result, {"OwnerA": 12_000_000})
        self.assertEqual(
            calls,
            [
                ("primary-rpc", "getMultipleAccounts"),
                ("helius-rpc", "getMultipleAccounts"),
            ],
        )

    def test_balance_batches_are_bounded_to_100_owners(self):
        batch_sizes: list[int] = []

        def rpc(url, method, params):
            del url
            self.assertEqual(method, "getMultipleAccounts")
            owners = params[0]
            batch_sizes.append(len(owners))
            return {"value": [{"lamports": 1} for _ in owners]}

        owners = [f"Owner{i:03d}" for i in range(205)]
        with patch.object(holders.ft, "_rpc_call", side_effect=rpc):
            balances = holders._batched_sol_balances(
                primary_rpc_url="primary-rpc",
                fallback_rpc_url="helius-rpc",
                owners=owners,
            )

        self.assertEqual(batch_sizes, [100, 100, 5])
        self.assertEqual(len(balances), 205)


if __name__ == "__main__":
    unittest.main()
