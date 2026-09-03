import base64
import json
import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.market_observation_store import load_market_trades
from src.pump_bonding_stream import (
    PUMP_PROGRAM_ID,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
    build_logs_subscribe_request,
    decode_pump_trade_event_payload,
    parse_logs_notification,
    persist_pump_notification,
    rpc_http_to_ws_url,
)


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + _B58.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * zeros + raw


def payload(*, mint: str, user: str, is_buy: bool = True, timestamp: int = 1000, sol_amount: int = 2_000_000_000, token_amount: int = 50_000_000) -> bytes:
    return b"".join(
        [
            PUMP_TRADE_EVENT_DISCRIMINATOR,
            b58decode(mint).rjust(32, b"\x00"),
            struct.pack("<Q", sol_amount),
            struct.pack("<Q", token_amount),
            bytes([1 if is_buy else 0]),
            b58decode(user).rjust(32, b"\x00"),
            struct.pack("<q", timestamp),
            b"ignored-tail",
        ]
    )


class PumpBondingStreamTests(unittest.TestCase):
    MINT = "11111111111111111111111111111111"
    USER = "4Nd1mYjK3uAq8J6X9pKf5mYjDqvVb7zY4wH1xT6nQ2sE"

    def test_rpc_url_conversion_preserves_path_and_query(self):
        self.assertEqual(
            rpc_http_to_ws_url("https://rpc.example/path?x=1"),
            "wss://rpc.example/path?x=1",
        )

    def test_subscription_is_exact_program_mention(self):
        request = build_logs_subscribe_request(commitment="confirmed")
        self.assertEqual(request["method"], "logsSubscribe")
        self.assertEqual(request["params"][0], {"mentions": [PUMP_PROGRAM_ID]})
        self.assertEqual(request["params"][1]["commitment"], "confirmed")

    def test_decodes_stable_trade_event_prefix(self):
        item = decode_pump_trade_event_payload(
            payload(mint=self.MINT, user=self.USER, is_buy=False, timestamp=1234)
        )
        self.assertIsNotNone(item)
        self.assertEqual(item.mint, self.MINT)
        self.assertEqual(item.user, self.USER)
        self.assertFalse(item.is_buy)
        self.assertEqual(item.timestamp, 1234)
        self.assertEqual(item.sol_amount, 2_000_000_000)

    def test_other_anchor_event_is_ignored(self):
        self.assertIsNone(decode_pump_trade_event_payload(b"12345678" + b"x" * 100))

    def test_truncated_trade_event_rejected(self):
        with self.assertRaises(ValueError):
            decode_pump_trade_event_payload(PUMP_TRADE_EVENT_DISCRIMINATOR + b"x")

    def test_failed_transaction_is_not_observation(self):
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 5},
                    "value": {"signature": "sig", "err": {"InstructionError": [0, "x"]}, "logs": []},
                }
            },
        }
        self.assertIsNone(parse_logs_notification(message, observed_at=1100))

    def test_parses_and_persists_trade_causally(self):
        raw = payload(mint=self.MINT, user=self.USER, is_buy=True, timestamp=1000)
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 99},
                    "value": {
                        "signature": "signature-1",
                        "err": None,
                        "logs": ["Program log: Instruction: Buy", "Program data: " + base64.b64encode(raw).decode()],
                    },
                }
            },
        }
        notification = parse_logs_notification(message, observed_at=1005)
        self.assertIsNotNone(notification)
        self.assertEqual(len(notification.events), 1)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "copytrader.db"
            with patch("src.database.settings.database_path", db):
                self.assertEqual(
                    persist_pump_notification(notification, acquisition_run_key="run-1"),
                    1,
                )
                self.assertEqual(
                    persist_pump_notification(notification, acquisition_run_key="run-1"),
                    0,
                )
                rows = load_market_trades(
                    acquisition_run_key="run-1", token_mint=self.MINT, as_of=1005
                )
                self.assertEqual(len(rows), 1)
                obs = rows[0].observation
                self.assertEqual(obs.side, "buy")
                self.assertEqual(obs.wallet_address, self.USER)
                self.assertEqual(obs.chain_time, 1000)
                self.assertEqual(obs.observed_at, 1005)
                self.assertEqual(obs.venue, "pump_bonding_curve")
                self.assertIsNone(obs.notional_usd)
                self.assertIsNone(obs.price_usd)

    def test_future_event_relative_to_observation_is_rejected(self):
        raw = payload(mint=self.MINT, user=self.USER, timestamp=1001)
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 1},
                    "value": {
                        "signature": "sig",
                        "err": None,
                        "logs": ["Program data: " + base64.b64encode(raw).decode()],
                    },
                }
            },
        }
        with self.assertRaises(ValueError):
            parse_logs_notification(message, observed_at=1000)

    def test_non_sol_quote_event_is_not_persisted_by_v1_adapter(self):
        raw = payload(
            mint=self.MINT,
            user=self.USER,
            timestamp=1000,
            sol_amount=0,
            token_amount=1,
        )
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 1},
                    "value": {
                        "signature": "stable-pair",
                        "err": None,
                        "logs": ["Program data: " + base64.b64encode(raw).decode()],
                    },
                }
            },
        }
        notification = parse_logs_notification(message, observed_at=1001)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "copytrader.db"
            with patch("src.database.settings.database_path", db):
                self.assertEqual(
                    persist_pump_notification(notification, acquisition_run_key="run-1"),
                    0,
                )


if __name__ == "__main__":
    unittest.main()
