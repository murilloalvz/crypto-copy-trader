import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation


class CausalQuoteProviderMetadataTests(unittest.TestCase):
    def test_provider_metadata_roundtrips_through_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=100,
                        observed_at=100,
                        price_usd=2.0,
                        source="jupiter_swap_v2_order:metis",
                        executable=False,
                        provider_router="metis",
                        provider_slippage_bps=50,
                        provider_price_impact_pct_points=-0.12,
                        provider_swap_usd_value=24.9,
                    ),
                    quote_key="q",
                )
                loaded = load_causal_quotes(quote_keys=["q"])[0]

        self.assertEqual(loaded.provider_router, "metis")
        self.assertEqual(loaded.provider_slippage_bps, 50)
        self.assertAlmostEqual(loaded.provider_price_impact_pct_points, -0.12)
        self.assertAlmostEqual(loaded.provider_swap_usd_value, 24.9)

    def test_old_quote_schema_migrates_without_inventing_historical_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with database.connection() as conn:
                    conn.executescript(
                        """
                        CREATE TABLE causal_quote_observations (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            quote_key TEXT NOT NULL UNIQUE,
                            token_mint TEXT NOT NULL,
                            side TEXT NOT NULL,
                            market_time INTEGER NOT NULL,
                            observed_at INTEGER NOT NULL,
                            price_usd REAL NOT NULL,
                            liquidity_usd REAL,
                            executable INTEGER NOT NULL,
                            resolution_seconds INTEGER NOT NULL,
                            source TEXT NOT NULL,
                            input_mint TEXT,
                            output_mint TEXT,
                            input_amount_raw TEXT,
                            output_amount_raw TEXT,
                            route_id TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
                        INSERT INTO causal_quote_observations(
                            quote_key, token_mint, side, market_time, observed_at, price_usd,
                            executable, resolution_seconds, source
                        ) VALUES ('legacy', 'T', 'buy', 100, 100, 1.0, 0, 1, 'old');
                        """
                    )
                loaded = load_causal_quotes(quote_keys=["legacy"])[0]

        self.assertIsNone(loaded.provider_router)
        self.assertIsNone(loaded.provider_slippage_bps)
        self.assertIsNone(loaded.provider_price_impact_pct_points)
        self.assertIsNone(loaded.provider_swap_usd_value)


if __name__ == "__main__":
    unittest.main()
