import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import (
    load_wallet_forward_observations,
    record_wallet_forward_observation,
)


class WalletForwardObservationTests(unittest.TestCase):
    def test_persists_once_and_loads_causally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = WalletActionObservation("A", "T", "buy", 100, 120)
                second = WalletActionObservation("B", "T", "sell", 130, 170)

                self.assertTrue(
                    record_wallet_forward_observation(
                        first,
                        observation_key="A:sig1:T:buy",
                        signature="sig1",
                    )
                )
                self.assertFalse(
                    record_wallet_forward_observation(
                        first,
                        observation_key="A:sig1:T:buy",
                        signature="sig1",
                    )
                )
                self.assertTrue(
                    record_wallet_forward_observation(
                        second,
                        observation_key="B:sig2:T:sell",
                        signature="sig2",
                    )
                )

                early = load_wallet_forward_observations(token_mint="T", as_of=150)
                all_rows = load_wallet_forward_observations(token_mint="T")

        self.assertEqual(len(early), 1)
        self.assertEqual(early[0].address, "A")
        self.assertEqual(len(all_rows), 2)

    def test_rejects_observation_that_was_seen_before_chain_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forward.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    record_wallet_forward_observation(
                        WalletActionObservation("A", "T", "buy", 200, 100),
                        observation_key="bad",
                    )


if __name__ == "__main__":
    unittest.main()
