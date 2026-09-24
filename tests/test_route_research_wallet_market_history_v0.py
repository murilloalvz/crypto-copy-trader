from __future__ import annotations

from types import SimpleNamespace
import unittest

from src.route_research_wallet_market_history_v0 import VERSION


class RouteResearchWalletMarketHistoryV0Tests(unittest.TestCase):
    def test_version_is_native_route_research(self):
        self.assertEqual(
            VERSION,
            "route_research_wallet_market_history_v0",
        )


if __name__ == "__main__":
    unittest.main()
