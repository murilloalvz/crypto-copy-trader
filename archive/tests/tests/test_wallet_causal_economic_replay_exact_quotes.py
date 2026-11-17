import unittest
from types import SimpleNamespace
from unittest.mock import patch

import wallet_causal_economic_replay as cli


class ExactQuoteIdentityTests(unittest.TestCase):
    def test_loader_preserves_quote_identity_independent_of_time_order(self):
        quotes = {
            "late-key": SimpleNamespace(price_usd=2.0),
            "early-key": SimpleNamespace(price_usd=1.0),
        }

        def fake_loader(*, quote_keys):
            key = tuple(quote_keys)[0]
            return [quotes[key]]

        with patch.object(cli, "load_causal_quotes", side_effect=fake_loader):
            loaded = cli._load_quotes_by_exact_key(("late-key", "early-key"))

        self.assertIs(loaded["late-key"], quotes["late-key"])
        self.assertIs(loaded["early-key"], quotes["early-key"])


if __name__ == "__main__":
    unittest.main()
