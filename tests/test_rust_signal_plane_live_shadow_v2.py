from __future__ import annotations

import unittest

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    AsyncPumpSwapIdentityPlane,
    INGRESS_QUEUE_SIZE,
    VERSION,
)


class RustSignalPlaneLiveShadowV2Tests(unittest.TestCase):
    def test_v2_transport_contract_is_frozen(self):
        self.assertEqual(
            VERSION,
            "rust_signal_plane_live_shadow_v2_transport_isolated",
        )
        self.assertEqual(INGRESS_QUEUE_SIZE, 8192)

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
