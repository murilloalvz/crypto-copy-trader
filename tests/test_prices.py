from src.assets import USDC_MINT
from src.prices import GeckoTerminalPriceProvider


def test_stablecoin_price_does_not_require_network():
    provider = GeckoTerminalPriceProvider()
    assert provider.price_at(USDC_MINT, 1_700_000_000) == 1.0

