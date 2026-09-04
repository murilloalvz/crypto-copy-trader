import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_deferred_persistence_v5 import PumpSwapEarlyReservationAssetIndex


class PumpSwapEarlyReservationAssetIndexTests(unittest.TestCase):
    def _prepared(self, *, run_key: str, transaction_key: str, token: str):
        return SimpleNamespace(
            acquisition_run_key=run_key,
            transaction_key=transaction_key,
            trade_writes=(
                SimpleNamespace(
                    observation=SimpleNamespace(token_mint=token),
                ),
            ),
        )

    def test_bootstrap_preserves_existing_canonical_transaction_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reservation-index.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="existing-event",
                    source_provider="test",
                    observation=MarketTradeObservation(
                        token_mint="EXISTING",
                        side="buy",
                        chain_time=998,
                        observed_at=999,
                        wallet_address="wallet-B",
                        venue="pumpswap",
                        transaction_key="sig-1",
                    ),
                )
                index = PumpSwapEarlyReservationAssetIndex.load_from_store(
                    acquisition_run_key="run"
                )
                assets = index.reservation_assets(
                    self._prepared(
                        run_key="run",
                        transaction_key="sig-1",
                        token="INCOMING",
                    )
                )

        self.assertEqual(assets, ("EXISTING", "INCOMING"))

    def test_repeated_transaction_unions_incoming_assets_in_memory(self):
        index = PumpSwapEarlyReservationAssetIndex(acquisition_run_key="run")
        first = index.reservation_assets(
            self._prepared(run_key="run", transaction_key="sig-1", token="A")
        )
        second = index.reservation_assets(
            self._prepared(run_key="run", transaction_key="sig-1", token="B")
        )

        self.assertEqual(first, ("A",))
        self.assertEqual(second, ("A", "B"))

    def test_run_key_mismatch_is_fatal(self):
        index = PumpSwapEarlyReservationAssetIndex(acquisition_run_key="run-A")
        with self.assertRaises(ValueError):
            index.reservation_assets(
                self._prepared(run_key="run-B", transaction_key="sig-1", token="A")
            )


if __name__ == "__main__":
    unittest.main()
