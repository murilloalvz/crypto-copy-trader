import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src.assets import USDC_MINT
from src.prices import (
    GeckoTerminalPriceProvider,
    PermanentPriceProviderError,
    TemporaryPriceProviderError,
)


class PriceTests(unittest.TestCase):
    def test_stablecoin_price_does_not_require_network(self):
        provider = GeckoTerminalPriceProvider()

        self.assertEqual(provider.price_at(USDC_MINT, 1_700_000_000), 1.0)

    @patch("src.prices.urlopen")
    def test_non_retryable_http_error_stops_immediately(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 404, "Not Found", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)

        with self.assertRaises(PermanentPriceProviderError) as raised:
            provider._get("/missing")

        self.assertEqual(raised.exception.code, "http_404")
        self.assertEqual(mocked_urlopen.call_count, 1)

    @patch("src.prices.time.sleep")
    @patch("src.prices.urlopen")
    def test_rate_limit_is_retried_then_classified_temporary(
        self, mocked_urlopen, _mocked_sleep
    ):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 429, "Too Many Requests", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)

        with self.assertRaises(TemporaryPriceProviderError):
            provider._get("/limited")

        self.assertEqual(mocked_urlopen.call_count, 3)
