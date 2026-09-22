from __future__ import annotations

import asyncio
from collections import Counter
import json
import time
import unittest
from unittest.mock import patch

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    AsyncPumpSwapIdentityPlane,
    INGRESS_MICROBATCH_MAX_NOTIFICATIONS,
    INGRESS_QUEUE_SIZE,
    SUBSCRIPTION_ACK_TIMEOUT_SECONDS,
    SURFACE_IDLE_TIMEOUT_SECONDS,
    VERSION,
    WS_OPEN_BARRIER_TIMEOUT_SECONDS,
    WS_OPEN_TIMEOUT_SECONDS,
    _surface_reader_v2,
    _take_ready_ingress_batch,
)


class RustSignalPlaneLiveShadowV2Tests(unittest.TestCase):
    def test_v4_1_startup_contract_is_frozen(self):
        self.assertEqual(
            VERSION,
            "rust_signal_plane_live_shadow_v4_1_startup_barrier",
        )
        self.assertEqual(INGRESS_QUEUE_SIZE, 8192)
        self.assertEqual(SURFACE_IDLE_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(INGRESS_MICROBATCH_MAX_NOTIFICATIONS, 32)
        self.assertEqual(WS_OPEN_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(WS_OPEN_BARRIER_TIMEOUT_SECONDS, 35.0)
        self.assertEqual(SUBSCRIPTION_ACK_TIMEOUT_SECONDS, 20.0)


    def test_ready_microbatch_drains_only_items_already_available(self):
        queue = asyncio.Queue(maxsize=8)
        first = {"id": 1}
        queue.put_nowait({"id": 2})
        queue.put_nowait({"id": 3})

        batch = _take_ready_ingress_batch(
            queue,
            first,
            max_notifications=32,
        )

        self.assertEqual([item["id"] for item in batch], [1, 2, 3])
        self.assertTrue(queue.empty())

    def test_ready_microbatch_respects_frozen_cap(self):
        queue = asyncio.Queue(maxsize=64)
        first = {"id": 0}
        for value in range(1, 40):
            queue.put_nowait({"id": value})

        batch = _take_ready_ingress_batch(
            queue,
            first,
            max_notifications=INGRESS_MICROBATCH_MAX_NOTIFICATIONS,
        )

        self.assertEqual(len(batch), 32)
        self.assertEqual(queue.qsize(), 8)

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
            opened = asyncio.Event()
            subscribe = asyncio.Event()
            ready = asyncio.Event()
            acquisition = asyncio.Event()
            errors = []
            deadline_ref = {"deadline": time.monotonic() + 0.02}
            subscribe.set()
            acquisition.set()
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
                    ingress_queue=queue,
                    counters=counters,
                    opened_event=opened,
                    subscribe_event=subscribe,
                    ready_event=ready,
                    acquisition_event=acquisition,
                    deadline_ref=deadline_ref,
                    transport_errors=errors,
                )
            return counters, errors, opened

        counters, errors, opened = asyncio.run(run())
        self.assertEqual(errors, [])
        self.assertTrue(opened.is_set())
        self.assertEqual(counters["pump_logs_socket_opened"], 1)
        self.assertEqual(counters["pump_logs_ack"], 1)
        self.assertEqual(counters["pump_logs_acquisition_started"], 1)
        self.assertEqual(
            captured["connect_kwargs"]["open_timeout"],
            WS_OPEN_TIMEOUT_SECONDS,
        )
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
