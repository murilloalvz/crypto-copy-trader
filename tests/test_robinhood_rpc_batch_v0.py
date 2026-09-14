import json
import unittest
from unittest.mock import patch

from benchmarks.robinhood_launch_burst_v0.live import JsonRpcError
from benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0 import BatchRpcClientV0


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class RobinhoodRpcBatchV0Tests(unittest.TestCase):
    def test_reversed_provider_response_is_reassembled_by_json_rpc_id(self):
        client = BatchRpcClientV0("https://rpc.invalid")

        def fake_urlopen(request, timeout):
            sent = json.loads(request.data.decode())
            self.assertEqual([item["id"] for item in sent], [1, 2])
            return FakeHttpResponse([
                {"jsonrpc": "2.0", "id": 2, "result": "second"},
                {"jsonrpc": "2.0", "id": 1, "result": "first"},
            ])

        with patch(
            "benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = client.batch_call([
                ("method_a", [1]),
                ("method_b", [2]),
            ])

        self.assertEqual(result, ["first", "second"])
        self.assertTrue(client.last_batch_report["response_reordered"])
        self.assertEqual(client.last_batch_report["request_count"], 2)

    def test_duplicate_response_id_fails_batch(self):
        client = BatchRpcClientV0("https://rpc.invalid")
        response = FakeHttpResponse([
            {"jsonrpc": "2.0", "id": 1, "result": "first"},
            {"jsonrpc": "2.0", "id": 1, "result": "duplicate"},
        ])
        with patch(
            "benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "duplicate id"):
                client.batch_call([("a", []), ("b", [])])

    def test_missing_or_unexpected_response_id_fails_batch(self):
        client = BatchRpcClientV0("https://rpc.invalid")
        response = FakeHttpResponse([
            {"jsonrpc": "2.0", "id": 1, "result": "first"},
            {"jsonrpc": "2.0", "id": 99, "result": "wrong"},
        ])
        with patch(
            "benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "batch id mismatch"):
                client.batch_call([("a", []), ("b", [])])

    def test_per_item_rpc_error_fails_whole_state_batch(self):
        client = BatchRpcClientV0("https://rpc.invalid")
        response = FakeHttpResponse([
            {"jsonrpc": "2.0", "id": 1, "result": "ok"},
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32000, "message": "revert"}},
        ])
        with patch(
            "benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(JsonRpcError, "batch\[1\].*rpc error"):
                client.batch_call([("a", []), ("b", [])])


if __name__ == "__main__":
    unittest.main()
