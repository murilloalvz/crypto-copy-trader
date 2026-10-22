from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import unified_market_route_research_smoke_tailfix_v9 as v9


class TailfixV9WrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_v9_enables_demoted_audit_split_on_v8(self):
        runner = AsyncMock()
        with patch.object(v9.tailfix_v8, "run_smoke_tailfix_v8", runner):
            await v9.run_smoke_tailfix_v9(run_key="test")

        runner.assert_awaited_once()
        self.assertTrue(runner.await_args.kwargs["pumpswap_demoted_audit_split"])
        self.assertEqual(runner.await_args.kwargs["run_key"], "test")


if __name__ == "__main__":
    unittest.main()
