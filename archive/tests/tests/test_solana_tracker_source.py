import json
import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError

from src.discovery.solana_tracker import (
    SolanaTrackerClient,
    SolanaTrackerConfigurationError,
    SolanaTrackerError,
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

        wallets = self.client().top_traders(
            2,
            sort_by="roi",
            direction="asc",
            min_invested_usd=500,
            min_trading_days=10,
            max_single_token_pct=30,
        )

        self.assertEqual([item.address for item in wallets], [WALLET_A, WALLET_B])
        self.assertEqual(wallets[0].profitable_days, 12)
        self.assertEqual(wallets[0].closed_tokens, 18)
        self.assertEqual(wallets[0].buys, 55)
        first_request = mocked_urlopen.call_args_list[0].args[0]
        self.assertIn("excludeArbitrage=true", first_request.full_url)
        self.assertIn("sort=roi", first_request.full_url)
        self.assertIn("direction=asc", first_request.full_url)
        self.assertIn("pnlMode=strict", first_request.full_url)
        self.assertIn("maxSingleTokenPct=30", first_request.full_url)
        self.assertIn("minInvested=500", first_request.full_url)
        self.assertIn("minDays=10", first_request.full_url)
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

    @patch("src.discovery.solana_tracker.urlopen")
    def test_wallet_positions_maps_documented_liquidity_fields(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse(
            {
                "wallet": WALLET_A,
                "positions": [
                    {
                        "token": token,
                        "pnl": {"realized": 1_250},
                        "invested": 2_500,
                        "roi": 50,
                        "averages": {"buy": 125},
                        "counts": {"total": 20},
                        "timing": {"lastTrade": 1_770_000_000_000, "holdTimeSecs": 3_600},
                        "meta": {
                            "symbol": "TEST",
                            "liquidity": 175_000,
                            "marketCap": 2_000_000,
                            "primaryMarket": "pumpfun-amm",
                        },
                    }
                ],
                "pagination": {"total": 18, "pnlMode": "strict"},
            }
        )

        result = self.client().wallet_positions(WALLET_A, period="30d", limit=25)

        self.assertEqual(result.address, WALLET_A)
        self.assertEqual(result.total_available, 18)
        self.assertEqual(result.pnl_mode, "strict")
        self.assertEqual(result.positions[0].token, token)
        self.assertEqual(result.positions[0].liquidity_usd, 175_000)
        self.assertEqual(result.positions[0].average_buy_usd, 125)
        request_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("period=30d", request_url)
        self.assertIn("sort=last_trade", request_url)
        self.assertIn("pnlMode=strict", request_url)
        self.assertIn("limit=25", request_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_liquid_market_search_applies_minimums(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse(
            {
                "data": [
                    {
                        "mint": token,
                        "symbol": "TEST",
                        "liquidityUsd": 500_000,
                        "volume_24h": 250_000,
                        "poolAddress": "pool-address",
                    }
                ]
            }
        )

        markets = self.client().liquid_markets(10)

        self.assertEqual(markets[0].token, token)
        self.assertEqual(markets[0].liquidity_usd, 500_000)
        request_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("sortBy=volume_24h", request_url)
        self.assertIn("minLiquidity=250000", request_url)
        self.assertIn("minVolume=100000", request_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_wave_tokens_maps_current_market_and_risk_fields(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse(
            {
                "data": [
                    {
                        "mint": token,
                        "name": "Wave Test",
                        "symbol": "WAVE",
                        "priceUsd": 0.001,
                        "liquidityUsd": 150_000,
                        "marketCapUsd": 900_000,
                        "createdAt": 1_800_000_000,
                        "holders": 850,
                        "buys": 420,
                        "sells": 210,
                        "totalTransactions": 630,
                        "volume_5m": 25_000,
                        "volume_1h": 100_000,
                        "volume_24h": 800_000,
                        "top10": 25,
                        "dev": 3,
                        "insiders": 4,
                        "snipers": 5,
                        "riskScore": 2,
                        "lpBurn": 100,
                        "mintAuthority": None,
                        "freezeAuthority": None,
                        "market": "pumpfun-amm",
                        "poolAddress": "pool-address",
                    }
                ]
            }
        )

        client = self.client()
        result = client.wave_tokens(25)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].token, token)
        self.assertEqual(result[0].volume_5m_usd, 25_000)
        self.assertEqual(result[0].risk_score, 2)
        self.assertEqual(result[0].created_at_ms, 1_800_000_000_000)
        self.assertEqual(
            client.last_wave_diagnostics,
            {
                "requested_limit": 25,
                "source_item_count": 1,
                "source_invalid_count": 0,
                "source_duplicate_count": 0,
                "returned_count": 1,
                "cache_used": False,
            },
        )
        request_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("sortBy=volume_5m", request_url)
        self.assertIn("volumeTimeframe=5m", request_url)
        self.assertIn("minLiquidity=50000", request_url)
        self.assertIn("minVolume=5000", request_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_wave_tokens_treats_zero_holders_as_unavailable(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse(
            {
                "data": [
                    {
                        "mint": token,
                        "priceUsd": 0.001,
                        "liquidityUsd": 150_000,
                        "holders": 0,
                        "totalTransactions": 500,
                        "volume_5m": 25_000,
                        "volume_1h": 100_000,
                        "riskScore": 2,
                        "poolAddress": "pool-address",
                    }
                ]
            }
        )

        result = self.client().wave_tokens(25)

        self.assertIsNone(result[0].holders)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_token_traders_excludes_developer_wallets(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse(
            {
                "traders": [
                    {"wallet": WALLET_A, "identity": {"type": "trader"}},
                    {"wallet": WALLET_B, "identity": {"type": "developer"}},
                ]
            }
        )

        seeds = self.client().token_traders(token, limit=10)

        self.assertEqual([item.address for item in seeds], [WALLET_A])
        request_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("excludeArbitrage=true", request_url)
        self.assertIn("activeOnly=false", request_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_token_traders_accepts_documented_diversity_sorts(self, mocked_urlopen):
        token = "38PgzpJYu2HkiYvV8qePFakB8tuobPdGm2FFEn7Dpump"
        mocked_urlopen.return_value = FakeResponse({"traders": []})

        self.client().token_traders(
            token,
            limit=5,
            sort_by="last_trade",
            direction="desc",
            active_only=False,
        )

        request_url = mocked_urlopen.call_args.args[0].full_url
        self.assertIn("sort=last_trade", request_url)
        self.assertIn("direction=desc", request_url)
        self.assertIn("activeOnly=false", request_url)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_windows_connection_reset_retries_with_tls12(self, mocked_urlopen):
        reset = ConnectionResetError(10054, "connection reset")
        reset.winerror = 10054
        mocked_urlopen.side_effect = [URLError(reset), FakeResponse({"traders": [], "pagination": {}})]

        result = self.client().top_traders(1)

        self.assertEqual(result, [])
        self.assertEqual(mocked_urlopen.call_count, 2)
        context = mocked_urlopen.call_args_list[1].kwargs["context"]
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_2)

    @patch("src.discovery.solana_tracker.urlopen")
    def test_timeout_has_bounded_attempts(self, mocked_urlopen):
        mocked_urlopen.side_effect = TimeoutError("slow source")
        client = SolanaTrackerClient(
            api_key="test-key",
            timeout=2,
            max_attempts=2,
            request_interval_seconds=0,
            sleeper=lambda _seconds: None,
        )

        with self.assertRaisesRegex(SolanaTrackerError, "após 2 tentativas"):
            client.top_traders(1)

        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertTrue(
            all(call.kwargs["timeout"] == 2 for call in mocked_urlopen.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
