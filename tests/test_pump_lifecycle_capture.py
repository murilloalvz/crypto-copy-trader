import base64
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_latest_market_lifecycle, load_market_trades
from src.pump_bonding_stream import (
    PUMP_CREATE_EVENT_DISCRIMINATOR,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
    decode_pump_create_event_payload,
    parse_logs_notification,
    persist_pump_notification,
)


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + _B58.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * zeros + raw


def borsh_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def create_payload(*, mint: str, timestamp: int) -> bytes:
    key = b58decode(mint).rjust(32, b"\x00")
    return b"".join(
        [
            PUMP_CREATE_EVENT_DISCRIMINATOR,
            borsh_string("Token"),
            borsh_string("TOK"),
            borsh_string("https://example.invalid/meta.json"),
            key,
            key,
            key,
            key,
            struct.pack("<q", timestamp),
            b"ignored-reserve-tail",
        ]
    )


def trade_payload(*, mint: str, timestamp: int) -> bytes:
    key = b58decode(mint).rjust(32, b"\x00")
    return b"".join(
        [
            PUMP_TRADE_EVENT_DISCRIMINATOR,
            key,
            struct.pack("<Q", 1_000_000_000),
            struct.pack("<Q", 100),
            b"\x01",
            key,
            struct.pack("<q", timestamp),
            b"ignored-tail",
        ]
    )


class PumpLifecycleCaptureTests(unittest.TestCase):
    MINT = "11111111111111111111111111111111"

    def test_create_event_decoder_extracts_causal_identity_prefix(self):
        event = decode_pump_create_event_payload(create_payload(mint=self.MINT, timestamp=1000))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.mint, self.MINT)
        self.assertEqual(event.timestamp, 1000)
        self.assertEqual(event.bonding_curve, self.MINT)

    def test_create_and_trade_in_same_notification_persist_lifecycle_and_transaction_identity(self):
        create = base64.b64encode(create_payload(mint=self.MINT, timestamp=1000)).decode()
        trade = base64.b64encode(trade_payload(mint=self.MINT, timestamp=1001)).decode()
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 9},
                    "value": {
                        "signature": "signature-create-buy",
                        "err": None,
                        "logs": [f"Program data: {create}", f"Program data: {trade}"],
                    },
                }
            },
        }
        notification = parse_logs_notification(message, observed_at=1002)
        self.assertIsNotNone(notification)
        assert notification is not None
        self.assertEqual(len(notification.lifecycle_events), 1)
        self.assertEqual(len(notification.events), 1)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertEqual(
                    persist_pump_notification(notification, acquisition_run_key="run"),
                    1,
                )
                lifecycle = load_latest_market_lifecycle(
                    acquisition_run_key="run", token_mint=self.MINT, as_of=1002
                )
                trades = load_market_trades(
                    acquisition_run_key="run", token_mint=self.MINT, as_of=1002
                )

        self.assertIsNotNone(lifecycle)
        assert lifecycle is not None
        self.assertEqual(lifecycle.observation.market_started_at, 1000)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].observation.transaction_key, "signature-create-buy")

    def test_future_create_event_is_rejected(self):
        encoded = base64.b64encode(create_payload(mint=self.MINT, timestamp=1002)).decode()
        message = {
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 1},
                    "value": {
                        "signature": "future-create",
                        "err": None,
                        "logs": [f"Program data: {encoded}"],
                    },
                }
            },
        }
        with self.assertRaises(ValueError):
            parse_logs_notification(message, observed_at=1001)


if __name__ == "__main__":
    unittest.main()
