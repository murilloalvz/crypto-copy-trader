import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import add_wallet, connection, initialize_database, rows
from src.services import reparse_wallet_transactions


class ReconciliationTests(unittest.TestCase):
    def test_existing_database_receives_dex_column(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    """CREATE TABLE transactions (
                    signature TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    block_time INTEGER,
                    status TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sol_change REAL NOT NULL DEFAULT 0,
                    fee_sol REAL NOT NULL DEFAULT 0,
                    token_mint TEXT,
                    token_change REAL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )

            test_settings = SimpleNamespace(database_path=database_path)
            with patch.object(database, "settings", test_settings):
                initialize_database()
                columns = {
                    row["name"] for row in rows("PRAGMA table_info(transactions)")
                }

        self.assertIn("dex", columns)

    def test_reparse_filters_false_positive_without_deleting_raw_history(self):
        wallet = "Wallet1111111111111111111111111111111111"
        signature = "legacy-false-positive"
        token = "TokenMint"
        raw_tx = {
            "blockTime": 1_700_000_000,
            "transaction": {
                "message": {
                    "accountKeys": [{"pubkey": wallet}],
                    "instructions": [],
                }
            },
            "meta": {
                "err": None,
                "fee": 5_000,
                "preBalances": [2_000_000_000],
                "postBalances": [1_499_995_000],
                "preTokenBalances": [],
                "postTokenBalances": [
                    {
                        "owner": wallet,
                        "mint": token,
                        "uiTokenAmount": {"uiAmountString": "100"},
                    }
                ],
            },
        }
        raw_json = json.dumps(raw_tx)

        with tempfile.TemporaryDirectory() as directory:
            test_settings = SimpleNamespace(
                database_path=Path(directory) / "copytrader.db"
            )
            with patch.object(database, "settings", test_settings):
                initialize_database()
                add_wallet(wallet, "Teste")
                with connection() as conn:
                    conn.execute(
                        """INSERT INTO transactions
                        (signature, wallet_address, block_time, status, kind, dex,
                         sol_change, fee_sol, token_mint, token_change, raw_json)
                        VALUES (?, ?, ?, 'success', 'swap', NULL, -0.5, 0.000005,
                                ?, 100, ?)""",
                        (signature, wallet, raw_tx["blockTime"], token, raw_json),
                    )
                    conn.execute(
                        """INSERT INTO paper_trades
                        (source_signature, wallet_address, token_mint, side,
                         source_amount, simulated_usd, slippage_bps, delay_seconds,
                         status)
                        VALUES (?, ?, ?, 'buy', 100, 25, 100, 15, 'open')""",
                        (signature, wallet, token),
                    )

                updated = reparse_wallet_transactions(wallet)

                transaction = rows(
                    "SELECT kind, dex, raw_json FROM transactions WHERE signature=?",
                    (signature,),
                )[0]
                paper = rows(
                    """SELECT status, price_error FROM paper_trades
                    WHERE source_signature=?""",
                    (signature,),
                )[0]

        self.assertEqual(updated, 1)
        self.assertEqual(transaction["kind"], "token_transfer")
        self.assertIsNone(transaction["dex"])
        self.assertEqual(transaction["raw_json"], raw_json)
        self.assertEqual(paper["status"], "filtered_non_swap")
        self.assertIn("não é um swap confirmado", paper["price_error"])
