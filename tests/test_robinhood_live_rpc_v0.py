import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.robinhood_launch_burst_v0.live import (
    JsonRpcError,
    RpcClient,
    run,
)


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class RobinhoodLiveRpcV0Tests(unittest.TestCase):
    def test_single_call_accepts_matching_id_and_result(self):
        client = RpcClient("https://rpc.invalid")
        response = FakeHttpResponse(
            {"jsonrpc": "2.0", "id": 1, "result": "0x123"}
        )
        with patch(
            "benchmarks.robinhood_launch_burst_v0.live.urllib.request.urlopen",
            return_value=response,
        ):
            self.assertEqual(client.call("eth_test", []), "0x123")

    def test_single_call_wrong_id_fails_closed(self):
        client = RpcClient("https://rpc.invalid")
        response = FakeHttpResponse(
            {"jsonrpc": "2.0", "id": 999, "result": "0x123"}
        )
        with patch(
            "benchmarks.robinhood_launch_burst_v0.live.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "response id mismatch"):
                client.call("eth_test", [])

    def test_single_call_missing_result_fails_closed(self):
        client = RpcClient("https://rpc.invalid")
        response = FakeHttpResponse({"jsonrpc": "2.0", "id": 1})
        with patch(
            "benchmarks.robinhood_launch_burst_v0.live.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "response missing result"):
                client.call("eth_test", [])

    def test_single_call_non_object_response_fails_closed(self):
        client = RpcClient("https://rpc.invalid")
        response = FakeHttpResponse([{"jsonrpc": "2.0", "id": 1, "result": "0x123"}])
        with patch(
            "benchmarks.robinhood_launch_burst_v0.live.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "response must be a JSON object"):
                client.call("eth_test", [])

    def test_invalid_chain_id_is_named_not_raw_value_error(self):
        client = RpcClient("https://rpc.invalid")
        response = FakeHttpResponse({"jsonrpc": "2.0", "id": 1, "result": None})
        with patch(
            "benchmarks.robinhood_launch_burst_v0.live.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "invalid eth_chainId response"):
                client.chain_id()

    def test_preflight_failure_artifact_names_chain_id_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                duration_seconds=1,
                poll_ms=350,
                max_block_span=20,
                max_transport_errors=5,
                rpc_timeout_seconds=1,
                rpc_url="https://rpc.invalid",
                factory_address=None,
                factory_lookback_blocks=5_000,
                artifacts_root=directory,
            )
            with patch(
                "benchmarks.robinhood_launch_burst_v0.live.load_dotenv",
                return_value=True,
            ), patch.object(
                RpcClient,
                "chain_id",
                side_effect=JsonRpcError("synthetic chain failure"),
            ):
                report = run(args)

            self.assertEqual(
                report["classification"],
                "FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0",
            )
            self.assertFalse(report["preflight_completed"])
            self.assertEqual(report["failure_stage"], "preflight_chain_id")
            self.assertIn("synthetic chain failure", report["error"])
            report_paths = list(Path(directory).glob("*/report.json"))
            self.assertEqual(len(report_paths), 1)
            persisted = json.loads(report_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(persisted["failure_stage"], "preflight_chain_id")


if __name__ == "__main__":
    unittest.main()
