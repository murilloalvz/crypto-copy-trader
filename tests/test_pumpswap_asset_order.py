import asyncio
import unittest

from src.pumpswap_asset_order import AssetOrderGate


class PumpSwapAssetOrderGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_asset_waits_for_prior_reservation(self):
        gate = AssetOrderGate()
        first = gate.reserve(("TOKEN",))
        second = gate.reserve(("TOKEN",))

        await gate.wait_turn(first)
        waiter = asyncio.create_task(gate.wait_turn(second))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())

        await gate.complete(first)
        await asyncio.wait_for(waiter, timeout=0.1)
        await gate.complete(second)

    async def test_disjoint_assets_can_run_concurrently(self):
        gate = AssetOrderGate()
        left = gate.reserve(("A",))
        right = gate.reserve(("B",))

        await asyncio.wait_for(
            asyncio.gather(gate.wait_turn(left), gate.wait_turn(right)),
            timeout=0.1,
        )
        await gate.complete(left)
        await gate.complete(right)

    async def test_multi_asset_reservation_preserves_global_ticket_partial_order(self):
        gate = AssetOrderGate()
        y_first = gate.reserve(("Y",))
        xy = gate.reserve(("X", "Y"))
        x_later = gate.reserve(("X",))

        await gate.wait_turn(y_first)
        xy_waiter = asyncio.create_task(gate.wait_turn(xy))
        x_waiter = asyncio.create_task(gate.wait_turn(x_later))
        await asyncio.sleep(0)
        self.assertFalse(xy_waiter.done())
        self.assertFalse(x_waiter.done())

        await gate.complete(y_first)
        await asyncio.wait_for(xy_waiter, timeout=0.1)
        self.assertFalse(x_waiter.done())
        await gate.complete(xy)
        await asyncio.wait_for(x_waiter, timeout=0.1)
        await gate.complete(x_later)

    async def test_empty_asset_set_never_blocks(self):
        gate = AssetOrderGate()
        reservation = gate.reserve(())
        await asyncio.wait_for(gate.wait_turn(reservation), timeout=0.1)
        await gate.complete(reservation)


if __name__ == "__main__":
    unittest.main()
