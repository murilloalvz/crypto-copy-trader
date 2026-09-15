import unittest

from benchmarks.robinhood_sequencer_shadow_v0.provider_method_surface_preflight import (
    run_method_surface_preflight_v0,
)


class FakeRpc:
    def __init__(self, rows):
        self.rows = list(rows)

    def call(self, method, params):
        expected_method, result, check = self.rows.pop(0)
        assert method == expected_method
        return result, dict(check)


def ok(method):
    return {"ok": True, "method": method, "http_status": 200, "stage": "complete", "error": None}


class RobinhoodProviderMethodSurfacePreflightV0Tests(unittest.TestCase):
    def test_pass_requires_all_required_methods(self):
        rpc = FakeRpc([
            ("eth_chainId", "0x1237", ok("eth_chainId")),
            ("eth_blockNumber", "0x100", ok("eth_blockNumber")),
            ("web3_sha3", "0x" + "11" * 32, ok("web3_sha3")),
            ("eth_getCode", "0x6000", ok("eth_getCode")),
            ("eth_getLogs", [], ok("eth_getLogs")),
            ("eth_getBlockByNumber", {"hash": "0x" + "22" * 32}, ok("eth_getBlockByNumber")),
        ])
        report = run_method_surface_preflight_v0(
            rpc_url="https://provider.example/v2/SECRET",
            factory_address="0x" + "33" * 20,
            client=rpc,
        )
        self.assertEqual(report["classification"], "PASS_ROBINHOOD_RPC_METHOD_SURFACE_V0")
        self.assertTrue(report["factory_code_present"])
        self.assertEqual(report["recent_factory_log_count"], 0)
        self.assertTrue(report["rpc_endpoint"]["path_redacted"])
        self.assertNotIn("SECRET", str(report))

    def test_403_on_get_logs_is_access_denied_not_pass(self):
        denied = {"ok": False, "method": "eth_getLogs", "http_status": 403, "stage": "http", "error": "HTTPError:403:Forbidden"}
        rpc = FakeRpc([
            ("eth_chainId", "0x1237", ok("eth_chainId")),
            ("eth_blockNumber", "0x100", ok("eth_blockNumber")),
            ("web3_sha3", "0x" + "11" * 32, ok("web3_sha3")),
            ("eth_getCode", "0x6000", ok("eth_getCode")),
            ("eth_getLogs", None, denied),
            ("eth_getBlockByNumber", {"hash": "0x" + "22" * 32}, ok("eth_getBlockByNumber")),
        ])
        report = run_method_surface_preflight_v0(
            rpc_url="https://provider.example",
            factory_address="0x" + "33" * 20,
            client=rpc,
        )
        self.assertEqual(
            report["classification"],
            "FAIL_ROBINHOOD_RPC_METHOD_SURFACE_ACCESS_DENIED_V0",
        )

    def test_429_is_inconclusive_rate_limit(self):
        limited = {"ok": False, "method": "eth_getBlockByNumber", "http_status": 429, "stage": "http", "error": "HTTPError:429:Too Many Requests"}
        rpc = FakeRpc([
            ("eth_chainId", "0x1237", ok("eth_chainId")),
            ("eth_blockNumber", "0x100", ok("eth_blockNumber")),
            ("web3_sha3", "0x" + "11" * 32, ok("web3_sha3")),
            ("eth_getCode", "0x6000", ok("eth_getCode")),
            ("eth_getLogs", [], ok("eth_getLogs")),
            ("eth_getBlockByNumber", None, limited),
        ])
        report = run_method_surface_preflight_v0(
            rpc_url="https://provider.example",
            factory_address="0x" + "33" * 20,
            client=rpc,
        )
        self.assertEqual(
            report["classification"],
            "INCONCLUSIVE_ROBINHOOD_RPC_METHOD_SURFACE_RATE_LIMITED_V0",
        )


if __name__ == "__main__":
    unittest.main()
