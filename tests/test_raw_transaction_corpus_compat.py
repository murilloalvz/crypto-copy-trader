import asyncio
import json
import unittest

from benchmarks.raw_transaction_corpus_v1.capture_compat import _subscribe_one
from src.pump_bonding_stream import PUMP_PROGRAM_ID


class _FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        if not self.messages:
            raise RuntimeError("no messages left")
        return json.dumps(self.messages.pop(0))


class RawTransactionCorpusCompatTests(unittest.TestCase):
    def test_subscribe_ignores_interleaved_notification_before_ack(self):
        websocket = _FakeWebSocket(
            [
                {
                    "method": "logsNotification",
                    "params": {"subscription": 77, "result": {}},
                },
                {"jsonrpc": "2.0", "id": 2, "result": 88},
            ]
        )
        subscription_id, mapping = asyncio.run(
            _subscribe_one(
                websocket,
                request_id=2,
                venue="pump",
                program_id=PUMP_PROGRAM_ID,
                commitment="confirmed",
            )
        )
        self.assertEqual(subscription_id, 88)
        self.assertEqual(mapping, ("pump", PUMP_PROGRAM_ID))
        self.assertEqual(websocket.sent[0]["id"], 2)

    def test_subscribe_surfaces_rpc_error_with_context(self):
        websocket = _FakeWebSocket(
            [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}}]
        )
        with self.assertRaisesRegex(RuntimeError, "logsSubscribe failed"):
            asyncio.run(
                _subscribe_one(
                    websocket,
                    request_id=1,
                    venue="pump",
                    program_id=PUMP_PROGRAM_ID,
                    commitment="confirmed",
                )
            )


if __name__ == "__main__":
    unittest.main()
