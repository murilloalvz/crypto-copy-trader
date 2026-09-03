import base64
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_latest_market_lifecycle, load_market_trades
from src.pumpswap_stream import (
    PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
    PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR,
    PUMPSWAP_POOL_ACCOUNT_DISCRIMINATOR,
    PUMPSWAP_PROGRAM_ID,
    PUMPSWAP_SELL_EVENT_DISCRIMINATOR,
    PumpSwapPoolResolver,
    build_logs_subscribe_request,
    decode_pumpswap_buy_event_payload,
    decode_pumpswap_create_pool_event_payload,
    decode_pumpswap_pool_account,
    decode_pumpswap_sell_event_payload,
    parse_logs_notification,
    persist_pumpswap_notification,
)


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    zeros = len(raw) - len(raw.lstrip(b"\x00"))
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _B58[remainder] + encoded
    return "1" * zeros + encoded


def pubkey(seed: int) -> tuple[bytes, str]:
    raw = bytes([seed]) * 32
    return raw, b58encode(raw)


def trade_payload(*, side: str, pool_raw: bytes, user_raw: bytes, timestamp: int = 1000) -> bytes:
    discriminator = (
        PUMPSWAP_BUY_EVENT_DISCRIMINATOR
        if side == "buy"
        else PUMPSWAP_SELL_EVENT_DISCRIMINATOR
    )
    amounts = [100, 200, 300, 400, 500, 600, 700, 8, 9, 10, 11, 1200, 1300]
    return b"".join(
        [
            discriminator,
            struct.pack("<q", timestamp),
            struct.pack("<13Q", *amounts),
            pool_raw,
            user_raw,
            b"ignored-tail",
        ]
    )


def create_pool_payload(
    *,
    pool_raw: bytes,
    creator_raw: bytes,
    base_raw: bytes,
    quote_raw: bytes,
    timestamp: int = 1000,
) -> bytes:
    return b"".join(
        [
            PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR,
            struct.pack("<q", timestamp),
            struct.pack("<H", 7),
            creator_raw,
            base_raw,
            quote_raw,
            bytes([6, 9]),
            struct.pack("<7Q", 1, 2, 3, 4, 5, 6, 7),
            bytes([255]),
            pool_raw,
            b"ignored-tail",
        ]
    )


def pool_account_payload(*, creator_raw: bytes, base_raw: bytes, quote_raw: bytes) -> bytes:
    return b"".join(
        [
            PUMPSWAP_POOL_ACCOUNT_DISCRIMINATOR,
            bytes([1]),
            struct.pack("<H", 3),
            creator_raw,
            base_raw,
            quote_raw,
            b"ignored-tail",
        ]
    )


def message(signature: str, raw_events: list[bytes], *, err=None) -> dict:
    return {
        "method": "logsNotification",
        "params": {
            "result": {
                "context": {"slot": 99},
                "value": {
                    "signature": signature,
                    "err": err,
                    "logs": ["Program data: " + base64.b64encode(item).decode() for item in raw_events],
                },
            }
        },
    }


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def call(self, method, params):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class PumpSwapStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pool_raw, self.pool = pubkey(1)
        self.user_raw, self.user = pubkey(2)
        self.creator_raw, self.creator = pubkey(3)
        self.base_raw, self.base = pubkey(4)
        self.quote_raw, self.quote = pubkey(5)

    def test_subscription_targets_exact_program(self):
        request = build_logs_subscribe_request(commitment="confirmed")
        self.assertEqual(request["method"], "logsSubscribe")
        self.assertEqual(request["params"][0], {"mentions": [PUMPSWAP_PROGRAM_ID]})
        self.assertEqual(request["params"][1]["commitment"], "confirmed")

    def test_buy_and_sell_stable_prefixes_decode(self):
        buy = decode_pumpswap_buy_event_payload(
            trade_payload(side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw)
        )
        sell = decode_pumpswap_sell_event_payload(
            trade_payload(side="sell", pool_raw=self.pool_raw, user_raw=self.user_raw)
        )
        self.assertIsNotNone(buy)
        self.assertIsNotNone(sell)
        assert buy is not None and sell is not None
        self.assertEqual((buy.side, buy.pool, buy.user), ("buy", self.pool, self.user))
        self.assertEqual((sell.side, sell.pool, sell.user), ("sell", self.pool, self.user))
        self.assertEqual(buy.base_amount_raw, 100)
        self.assertEqual(buy.quote_amount_raw, 700)

    def test_create_pool_and_pool_account_decode_identity(self):
        create = decode_pumpswap_create_pool_event_payload(
            create_pool_payload(
                pool_raw=self.pool_raw,
                creator_raw=self.creator_raw,
                base_raw=self.base_raw,
                quote_raw=self.quote_raw,
            )
        )
        account = decode_pumpswap_pool_account(
            pool_account_payload(
                creator_raw=self.creator_raw,
                base_raw=self.base_raw,
                quote_raw=self.quote_raw,
            )
        )
        self.assertIsNotNone(create)
        assert create is not None
        self.assertEqual(create.pool, self.pool)
        self.assertEqual(create.base_mint, self.base)
        self.assertEqual(create.quote_mint, self.quote)
        self.assertEqual(create.base_mint_decimals, 6)
        self.assertEqual(create.quote_mint_decimals, 9)
        self.assertEqual(account.base_mint, self.base)
        self.assertEqual(account.quote_mint, self.quote)

    def test_failed_transaction_and_impossible_clock_are_rejected(self):
        raw = trade_payload(side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw, timestamp=1000)
        self.assertIsNone(parse_logs_notification(message("failed", [raw], err={"x": 1}), observed_at=1005))
        with self.assertRaises(ValueError):
            parse_logs_notification(message("future", [raw]), observed_at=999)

    async def test_create_event_resolves_trade_without_rpc_and_persists_transaction_identity(self):
        create = create_pool_payload(
            pool_raw=self.pool_raw,
            creator_raw=self.creator_raw,
            base_raw=self.base_raw,
            quote_raw=self.quote_raw,
            timestamp=1000,
        )
        buy = trade_payload(
            side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw, timestamp=1000
        )
        notification = parse_logs_notification(message("sig-create-buy", [create, buy]), observed_at=1005)
        self.assertIsNotNone(notification)
        assert notification is not None
        fake = FakeClient(AssertionError("RPC must not be called when CreatePoolEvent resolves pool"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = PumpSwapPoolResolver(
                    acquisition_run_key="run", commitment="confirmed", client=fake
                )
                result = await persist_pumpswap_notification(
                    notification, acquisition_run_key="run", resolver=resolver
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint=self.base)
                lifecycle = load_latest_market_lifecycle(
                    acquisition_run_key="run", token_mint=self.base
                )

        self.assertEqual(result.newly_persisted_trades, 1)
        self.assertEqual(result.newly_persisted_lifecycle, 1)
        self.assertEqual(fake.calls, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].observation.transaction_key, "sig-create-buy")
        self.assertEqual(rows[0].observation.observed_at, 1005)
        self.assertEqual(rows[0].observation.venue, "pumpswap")
        self.assertIsNotNone(lifecycle)

    async def test_hydration_delays_effective_trade_observed_at_and_cache_is_reused(self):
        raw_account = pool_account_payload(
            creator_raw=self.creator_raw,
            base_raw=self.base_raw,
            quote_raw=self.quote_raw,
        )
        rpc_result = {
            "value": {
                "owner": PUMPSWAP_PROGRAM_ID,
                "data": [base64.b64encode(raw_account).decode(), "base64"],
            }
        }
        fake = FakeClient(rpc_result)
        first = parse_logs_notification(
            message(
                "sig-hydrate-1",
                [trade_payload(side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw)],
            ),
            observed_at=1005,
        )
        second = parse_logs_notification(
            message(
                "sig-hydrate-2",
                [trade_payload(side="sell", pool_raw=self.pool_raw, user_raw=self.user_raw, timestamp=1001)],
            ),
            observed_at=1011,
        )
        assert first is not None and second is not None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = PumpSwapPoolResolver(
                    acquisition_run_key="run", commitment="confirmed", client=fake
                )
                with patch("src.pumpswap_stream.time.time", return_value=1010):
                    result1 = await persist_pumpswap_notification(
                        first, acquisition_run_key="run", resolver=resolver
                    )
                result2 = await persist_pumpswap_notification(
                    second, acquisition_run_key="run", resolver=resolver
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint=self.base)

        self.assertEqual(result1.newly_persisted_trades, 1)
        self.assertEqual(result2.newly_persisted_trades, 1)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(resolver.hydration_attempts, 1)
        self.assertEqual(resolver.hydration_successes, 1)
        self.assertGreaterEqual(resolver.cache_hits, 1)
        self.assertEqual([item.observation.observed_at for item in rows], [1010, 1011])

    async def test_unresolved_pool_never_invents_token_trade(self):
        notification = parse_logs_notification(
            message(
                "sig-unresolved",
                [trade_payload(side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw)],
            ),
            observed_at=1005,
        )
        assert notification is not None
        fake = FakeClient({"value": None})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = PumpSwapPoolResolver(
                    acquisition_run_key="run", commitment="confirmed", client=fake
                )
                result = await persist_pumpswap_notification(
                    notification, acquisition_run_key="run", resolver=resolver
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint=self.base)
        self.assertEqual(result.unresolved_trades, 1)
        self.assertEqual(result.newly_persisted_trades, 0)
        self.assertEqual(len(rows), 0)
        self.assertEqual(resolver.hydration_failures, 1)

    async def test_replayed_trade_with_later_websocket_clock_is_idempotent(self):
        create = create_pool_payload(
            pool_raw=self.pool_raw,
            creator_raw=self.creator_raw,
            base_raw=self.base_raw,
            quote_raw=self.quote_raw,
        )
        buy = trade_payload(side="buy", pool_raw=self.pool_raw, user_raw=self.user_raw)
        first = parse_logs_notification(message("same-sig", [create, buy]), observed_at=1005)
        replay = parse_logs_notification(message("same-sig", [create, buy]), observed_at=1010)
        assert first is not None and replay is not None
        fake = FakeClient(AssertionError("RPC must not be called"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = PumpSwapPoolResolver(
                    acquisition_run_key="run", commitment="confirmed", client=fake
                )
                result1 = await persist_pumpswap_notification(
                    first, acquisition_run_key="run", resolver=resolver
                )
                result2 = await persist_pumpswap_notification(
                    replay, acquisition_run_key="run", resolver=resolver
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint=self.base)

        self.assertEqual(result1.newly_persisted_trades, 1)
        self.assertEqual(result2.duplicate_or_replayed_trades, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].observation.observed_at, 1005)


if __name__ == "__main__":
    unittest.main()
