from __future__ import annotations

import asyncio
from collections import Counter
import json
import time
import unittest
from unittest.mock import patch

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    AsyncPumpSwapIdentityPlane,
    INGRESS_QUEUE_SIZE,
    SURFACE_IDLE_TIMEOUT_SECONDS,
    VERSION,
    _surface_reader_v2,
)


class RustSignalPlaneLiveShadowV2Tests(unittest.TestCase):
    def test_v3_transport_contract_is_frozen(self):
        self.assertEqual(
            VERSION,
            "rust_signal_plane_live_shadow_v3_server_heartbeat",
        )
        self.assertEqual(INGRESS_QUEUE_SIZE, 8192)
        self.assertEqual(SURFACE_IDLE_TIMEOUT_SECONDS, 30.0)


    def test_reader_disables_client_originated_keepalive_ping(self):
        captured = {}

        class FakeWebSocket:
            def __init__(self):
                self.recv_count = 0

            async def send(self, payload):
                captured["sent"] = json.loads(payload)

            async def recv(self):
                self.recv_count += 1
                if self.recv_count == 1:
                    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": 77})
                await asyncio.sleep(1.0)
                return ""

        class FakeConnectContext:
            def __init__(self, **kwargs):
                captured["connect_kwargs"] = kwargs
                self.ws = FakeWebSocket()

            async def __aenter__(self):
                return self.ws

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def fake_connect(endpoint, **kwargs):
            captured["endpoint"] = endpoint
            return FakeConnectContext(**kwargs)

        async def run():
            queue = asyncio.Queue(maxsize=8)
            counters = Counter()
            ready = asyncio.Event()
            errors = []
            with patch("websockets.asyncio.client.connect", new=fake_connect):
                await _surface_reader_v2(
                    endpoint="wss://example.invalid/v2/test",
                    label="pump_logs",
                    request={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [],
                    },
                    deadline=time.monotonic() + 0.02,
                    ingress_queue=queue,
                    counters=counters,
                    ready_event=ready,
                    transport_errors=errors,
                )
            return counters, errors

        counters, errors = asyncio.run(run())
        self.assertEqual(errors, [])
        self.assertEqual(counters["pump_logs_ack"], 1)
        self.assertIsNone(captured["connect_kwargs"]["ping_interval"])
        self.assertIsNone(captured["connect_kwargs"]["ping_timeout"])

    def test_identity_plane_uses_only_primary_rpc(self):
        plane = AsyncPumpSwapIdentityPlane(
            identities_by_pool={},
            rpc_url="https://solana-mainnet.g.alchemy.com/v2/test",
        )
        self.assertEqual(
            plane.client.rpc_urls,
            ["https://solana-mainnet.g.alchemy.com/v2/test"],
        )

    def test_identity_queue_overflow_is_explicit_and_retryable(self):
        plane = AsyncPumpSwapIdentityPlane(
            identities_by_pool={},
            rpc_url="https://example.invalid",
            queue_size=1,
        )
        self.assertTrue(plane.enqueue("POOL_A"))
        self.assertFalse(plane.enqueue("POOL_B"))
        self.assertEqual(plane.counters["queue_full"], 1)
        self.assertNotIn("POOL_B", plane.attempted_pools)


if __name__ == "__main__":
    unittest.main()
