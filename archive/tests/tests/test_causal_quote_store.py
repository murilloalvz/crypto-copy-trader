import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation


class CausalQuoteStoreTests(unittest.TestCase):
    def test_explicit_quote_keys_scope_and_empty_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=100,
                        observed_at=100,
                        price_usd=1.0,
                        source="test",
                        executable=False,
                    ),
                    quote_key="event-a:+0",
                )
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=110,
                        observed_at=110,
                        price_usd=2.0,
                        source="test",
                        executable=False,
                    ),
                    quote_key="event-b:+0",
                )

                all_quotes = load_causal_quotes()
                scoped = load_causal_quotes(quote_keys=["event-b:+0"])
                empty = load_causal_quotes(quote_keys=[])

        self.assertEqual(len(all_quotes), 2)
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0].price_usd, 2.0)
        self.assertEqual(empty, [])

    def test_quote_key_scope_composes_with_side_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=100,
                        observed_at=100,
                        price_usd=1.0,
                        source="test",
                        executable=False,
                    ),
                    quote_key="buy",
                )
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="sell",
                        market_time=101,
                        observed_at=101,
                        price_usd=1.1,
                        source="test",
                        executable=False,
                    ),
                    quote_key="sell",
                )
                result = load_causal_quotes(
                    quote_keys=["buy", "sell"],
                    side="buy",
                )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].side, "buy")


if __name__ == "__main__":
    unittest.main()
