import unittest
from unittest.mock import AsyncMock, patch

import unified_market_latency_smoke_v26 as v26


class UnifiedMarketLatencyV26Tests(unittest.IsolatedAsyncioTestCase):
    async def test_v26_enables_stateful_only_finalize_without_rewriting_other_kwargs(self):
        with patch.object(v26.v24, "run_smoke_v24", new=AsyncMock(return_value="ok")) as run:
            result = await v26.run_smoke_v26(
                run_key="run",
                duration_seconds=120,
                pump_prepare_workers=4,
            )

        self.assertEqual(result, "ok")
        run.assert_awaited_once_with(
            run_key="run",
            duration_seconds=120,
            pump_prepare_workers=4,
            stateful_only_finalize=True,
        )


if __name__ == "__main__":
    unittest.main()
