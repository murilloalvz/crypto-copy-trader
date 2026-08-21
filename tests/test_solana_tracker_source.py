import json
import unittest
from unittest.mock import patch

from src.discovery.solana_tracker import (
    SolanaTrackerClient,
    SolanaTrackerConfigurationError,
)

WALLET_A = "HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf"
WALLET_B = "ApAKzJEqfnP7F74Za5xdTQxZMK4nD8dFTVBQ9bksTtGM"


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def trader(address, pnl=30_000):
    return {
        "wallet": address,
        "period": {
            "realized": pnl,
            "volume": 120_000,
            "tradingDays": 18,
            "roi": 42.5,
            "days": {"profitable": 12, "losing": 6, "maxSinglePnl": 8_000},
        },
        "invested": 60_000,
        "proceeds": 90_000,
        "counts": {"buys": 55, "sells": 65, "trades": 120, "tokensTraded": 18},
        "tokens": {"profitable": 11, "losing": 7, "closed": 18},
        "winRate": 61.11,
        "timing": {"firstTrade": 1_700_000_000_000, "lastTrade": 1_770_000_000_000},
    }


class SolanaTrackerSourceTests(unittest.TestCase):
    def client(self):
        return SolanaTrackerClient(api_key="test-key", request_interval_seconds=0)

    def test_requires_environment_key(self):
        with self.assertRaisesRegex(SolanaTrackerConfigurationError, "SOLANA_TRACKER_API_KEY"):
            SolanaTrackerClient(api_key="", request_interval_seconds=0).top_traders(1)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_leaderboard_uses_safety_filters_and_cursor_pagination(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            FakeResponse(
                {
                    "traders": [trader(WALLET_A)],
                    "pagination": {"hasMore": True, "nextCursor": "next-page", "pnlMode": "strict"},
                }
            ),
            FakeResponse(
                {
                    "traders": [trader(WALLET_B, 20_000)],
                    "pagination": {"hasMore": False, "nextCursor": None, "pnlMode": "strict"},
                }
            ),
        ]

        wallets = self.client().top_traders(2)

        self.assertEqual([item.address for item in wallets], [WALLET_A, WALLET_B])
        self.assertEqual(wallets[0].profitable_days, 12)
        self.assertEqual(wallets[0].closed_tokens, 18)
        self.assertEqual(wallets[0].buys, 55)
        first_request = mocked_urlopen.call_args_list[0].args[0]
        self.assertIn("excludeArbitrage=true", first_request.full_url)
        self.assertIn("pnlMode=strict", first_request.full_url)
        self.assertIn("maxSingleTokenPct=50", first_request.full_url)
        self.assertNotIn("test-key", first_request.full_url)
        second_url = mocked_urlopen.call_args_list[1].args[0].full_url
        self.assertIn("cursor=next-page", second_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_wallet_history_maps_daily_activity(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(
            {
                "wallet": WALLET_A,
                "days": [
                    {
                        "date": "2026-08-20",
                        "activity": {
                            "pnl": {"realized": 750},
                            "counts": {"buys": 4, "sells": 3},
                            "volume": {"costUsd": 2_000, "total": 4_750},
                            "averages": {"holdTimeSecs": 3600},
                        },
                    }
                ],
            }
        )

        history = self.client().wallet_history(WALLET_A)

        self.assertEqual(history.address, WALLET_A)
        self.assertEqual(history.days[0].trades, 7)
        self.assertEqual(history.days[0].realized_pnl_usd, 750)
        self.assertEqual(history.days[0].avg_hold_seconds, 3600)


if __name__ == "__main__":
    unittest.main()
