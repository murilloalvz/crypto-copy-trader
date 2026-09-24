from __future__ import annotations

import unittest

from src.route_research_forward_collection_900_v0 import (
    TARGET_HORIZONS,
)


class RouteResearchForwardCollection900V0Tests(unittest.TestCase):
    def test_target_horizons_are_frozen(self):
        self.assertEqual(TARGET_HORIZONS, (300, 900))


if __name__ == "__main__":
    unittest.main()
