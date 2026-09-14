import unittest

from benchmarks.robinhood_launch_burst_v0.direct_quote_state import PASS_SNIPE
from benchmarks.robinhood_launch_burst_v0.direct_quote_transport_bench import (
    FAIL,
    PASS,
    run_transport_bench_v0,
)


def word(value):
    return f"{int(value):064x}"


class FakeTransportClient:
    def __init__(self, *, mismatch_batch=False):
        self.mismatch_batch = mismatch_batch
        self.selectors = {
            "feeBps()": "0x11111111",
            "creatorTaxBps()": "0x22222222",
            "getReserves()": "0x33333333",
            "sellableTokens()": "0x44444444",
            "readyToGraduate()": "0x55555555",
            "currentSnipeTaxBps(address)": "0x66666666",
            "graduated()": "0x77777777",
        }
        self.last_batch_report = None
        self.batch_count = 0
        self.block_requests = []

    def block_number(self):
        return 1234

    def sha3_text(self, text):
        return self.selectors[text] + "00" * 28

    def _eth_result(self, params, *, batch=False):
        self.block_requests.append(params[1])
        selector = params[0]["data"][:10]
        if selector == "0x11111111":
            return "0x" + word(101 if batch and self.mismatch_batch else 100)
        if selector == "0x22222222":
            return "0x" + word(50)
        if selector == "0x33333333":
            return "0x" + word(1_000_000) + word(2_000_000)
        if selector == "0x44444444":
            return "0x" + word(1_500_000)
        if selector == "0x55555555":
            return "0x" + word(0)
        if selector == "0x77777777":
            return "0x" + word(0)
        if selector == "0x66666666":
            return "0x" + word(5_000)
        raise AssertionError(selector)

    def call(self, method, params):
        if method == "eth_getBlockByNumber":
            return {
                "number": params[0],
                "hash": "0x" + "aa" * 32,
                "timestamp": "0x64",
            }
        if method == "eth_getCode":
            return "0x60006000"
        if method == "eth_call":
            return self._eth_result(params, batch=False)
        raise AssertionError(method)

    def batch_call(self, calls):
        self.batch_count += 1
        results = []
        for method, params in calls:
            self.assert_method(method)
            results.append(self._eth_result(params, batch=True))
        count = len(calls)
        self.last_batch_report = {
            "contract_version": "robinhood_rpc_batch_v0",
            "request_count": count,
            "service_ms": 1.0,
            "response_reordered": True,
            "request_ids": list(range(1, count + 1)),
            "response_ids": list(reversed(range(1, count + 1))),
        }
        return results

    @staticmethod
    def assert_method(method):
        if method != "eth_call":
            raise AssertionError(method)


def capabilities():
    return {
        "classification": PASS_SNIPE,
        "generation_key": f"pons_v2:0x{'aa' * 20}:snipe_view",
        "factory": "0x" + "aa" * 20,
    }


class PonsDirectQuoteTransportBenchV0Tests(unittest.TestCase):
    def test_pass_requires_exact_same_block_state_parity(self):
        client = FakeTransportClient()
        result = run_transport_bench_v0(
            batch_client=client,
            curve="0x" + "11" * 20,
            recipient="0x" + "22" * 20,
            capability_report=capabilities(),
            iterations=4,
        )
        self.assertEqual(result["classification"], PASS)
        self.assertEqual(result["valid_pairs"], 4)
        self.assertEqual(result["parity_mismatches"], 0)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(client.batch_count, 4)
        self.assertEqual(result["pairs"][0]["execution_order"], ["sequential", "batch"])
        self.assertEqual(result["pairs"][1]["execution_order"], ["batch", "sequential"])
        self.assertTrue(all(pair["block_number"] == 1234 for pair in result["pairs"]))
        self.assertTrue(all(tag == "0x4d2" for tag in client.block_requests))
        self.assertFalse(result["economic_outcomes_opened"])
        self.assertFalse(result["trade_returns_computed"])
        self.assertFalse(result["selector_modified"])

    def test_state_mismatch_fails_and_is_excluded_from_latency_stats(self):
        client = FakeTransportClient(mismatch_batch=True)
        result = run_transport_bench_v0(
            batch_client=client,
            curve="0x" + "11" * 20,
            recipient="0x" + "22" * 20,
            capability_report=capabilities(),
            iterations=2,
        )
        self.assertEqual(result["classification"], FAIL)
        self.assertEqual(result["valid_pairs"], 0)
        self.assertEqual(result["parity_mismatches"], 2)
        self.assertEqual(result["sequential_total_ms"]["n"], 0)
        self.assertEqual(result["batch_total_ms"]["n"], 0)

    def test_iterations_must_be_positive(self):
        with self.assertRaises(ValueError):
            run_transport_bench_v0(
                batch_client=FakeTransportClient(),
                curve="0x" + "11" * 20,
                recipient="0x" + "22" * 20,
                capability_report=capabilities(),
                iterations=0,
            )


if __name__ == "__main__":
    unittest.main()
