import json
import unittest
from unittest.mock import patch

from src.discovery.birdeye import (
    BirdeyeClient,
    BirdeyeConfigurationError,
    is_solana_address,
)

WALLET_A = "FciNKwZAvSzepKH1nFEGeejzbP4k87dJiP9BAzGt2Sm3"
WALLET_B = "Habp5bncMSsBC3vkChyebepym5dcTNRYeg2LVG464E96"


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def success(data):
    return FakeResponse({"success": True, "data": data})


class BirdeyeSourceTests(unittest.TestCase):
    def client(self):
        return BirdeyeClient(api_key="test-key", request_interval_seconds=0)

    def test_requires_api_key_without_exposing_a_secret(self):
        with self.assertRaisesRegex(BirdeyeConfigurationError, "BIRDEYE_API_KEY"):
            BirdeyeClient(api_key="", request_interval_seconds=0).trader_leaderboard(1)

    def test_solana_address_validation(self):
        self.assertTrue(is_solana_address(WALLET_A))
        self.assertFalse(is_solana_address("not-a-wallet"))

    @patch("src.discovery.birdeye.urlopen")
    def test_leaderboard_maps_documented_fields_and_paginates(self, mocked_urlopen):
        first_page = [
            {
                "network": "solana",
                "address": WALLET_A,
                "pnl": "675542.13",
                "trade_count": "741",
                "volume": 1_372_626.71,
            }
        ] * 100
        # Duplicate addresses are ignored, so use the documented second address on page 2.
        mocked_urlopen.side_effect = [
            success({"items": first_page}),
            success(
                {
                    "items": [
                        {
                            "network": "solana",
                            "address": WALLET_B,
                            "pnl": 175_542.13,
                            "trade_count": 20,
                            "volume": 400_000,
                        }
                    ]
                }
            ),
        ]

        wallets = self.client().trader_leaderboard(2)

        self.assertEqual([item.address for item in wallets], [WALLET_A, WALLET_B])
        self.assertEqual(wallets[0].trade_count, 741)
        self.assertEqual(wallets[0].pnl_usd, 675_542.13)
        self.assertEqual(mocked_urlopen.call_count, 2)
        second_url = mocked_urlopen.call_args_list[1].args[0].full_url
        self.assertIn("offset=100", second_url)

    @patch("src.discovery.birdeye.urlopen")
    def test_wallet_pnl_maps_only_documented_summary_metrics(self, mocked_urlopen):
        mocked_urlopen.return_value = success(
            {
                "summary": {
                    "unique_tokens": 12,
                    "counts": {
                        "total_buy": 55,
                        "total_sell": 45,
                        "total_trade": 100,
                        "total_win": 29,
                        "total_loss": 21,
                        "win_rate": 58,
                    },
                    "cashflow_usd": {
                        "total_invested": 50_000,
                        "total_sold": 69_100,
                        "current_value": 2_000,
                    },
                    "pnl": {
                        "realized_profit_usd": 19_100,
                        "realized_profit_percent": 38.2,
                        "unrealized_usd": -500,
                        "total_usd": 18_600,
                        "avg_profit_per_trade_usd": 191,
                    },
                }
            }
        )

        metrics = self.client().wallet_pnl(WALLET_A, "30d")

        self.assertEqual(metrics.total_trade, 100)
        self.assertEqual(metrics.realized_outcomes, 50)
        self.assertEqual(metrics.win_rate_pct, 58)
        self.assertEqual(metrics.roi_pct, 38.2)
        self.assertEqual(metrics.unique_tokens, 12)


if __name__ == "__main__":
    unittest.main()
