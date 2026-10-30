import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import analytics, database, services
from src.analytics import paper_performance, wallet_metrics
from src.database import add_wallet, initialize_database, rows
from src.demo import (
    DEMO_WALLET_ADDRESS,
    DEMO_WALLET_LABEL,
    DemoPriceProvider,
    DemoSolanaClient,
)
from src.services import generate_paper_trades, price_paper_trades, sync_wallet


class OfflineDemoTests(unittest.TestCase):
    def test_complete_demo_flow_works_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = SimpleNamespace(
                database_path=Path(directory) / "demo.db",
                max_signatures=30,
                copy_size_usd=25,
                slippage_bps=100,
                copy_delay_seconds=15,
                starting_balance_usd=1_000,
            )
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
                patch.object(analytics, "settings", test_settings),
            ):
                initialize_database()
                add_wallet(DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL)

                sync_result = sync_wallet(
                    DEMO_WALLET_ADDRESS, client=DemoSolanaClient()
                )
                created = generate_paper_trades(DEMO_WALLET_ADDRESS)
                price_result = price_paper_trades(
                    DEMO_WALLET_ADDRESS, provider=DemoPriceProvider()
                )
                performance = paper_performance(DEMO_WALLET_ADDRESS)
                metrics = wallet_metrics(DEMO_WALLET_ADDRESS)
                transaction_rows = rows(
                    """SELECT kind, dex, token_change FROM transactions
                    WHERE wallet_address=? ORDER BY block_time""",
                    (DEMO_WALLET_ADDRESS,),
                )

                repeated = sync_wallet(
                    DEMO_WALLET_ADDRESS, client=DemoSolanaClient()
                )

        self.assertEqual(sync_result["found"], 10)
        self.assertEqual(sync_result["inserted"], 10)
        self.assertEqual(sync_result["failed"], 0)
        self.assertEqual(sync_result["rpc_endpoint"], "offline-local")
        self.assertEqual(created, 10)
        self.assertEqual(price_result["priced"], 10)
        self.assertEqual(price_result["failed"], 0)
        self.assertEqual(price_result["closed"], 5)
        self.assertEqual(performance["closed_trades"], 5)
        self.assertGreater(performance["realized_pnl_usd"], 0)
        self.assertIsNotNone(metrics["score"])
        self.assertTrue(all(item["kind"] == "swap" for item in transaction_rows))
        self.assertTrue(all(item["dex"] for item in transaction_rows))
        self.assertEqual(
            sum(item["token_change"] > 0 for item in transaction_rows), 5
        )
        self.assertEqual(
            sum(item["token_change"] < 0 for item in transaction_rows), 5
        )
        self.assertEqual(repeated["inserted"], 0)
        self.assertEqual(repeated["skipped"], 10)


if __name__ == "__main__":
    unittest.main()
