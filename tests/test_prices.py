import unittest

from src.assets import USDC_MINT
from src.prices import GeckoTerminalPriceProvider


class PriceTests(unittest.TestCase):
    def test_stablecoin_price_does_not_require_network(self):
        provider = GeckoTerminalPriceProvider()

        self.assertEqual(provider.price_at(USDC_MINT, 1_700_000_000), 1.0)
