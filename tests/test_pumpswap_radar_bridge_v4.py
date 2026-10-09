import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_radar_bridge_v3 import evaluate_persisted_pumpswap_notification_for_radar_v3
from src.pumpswap_radar_bridge_v4 import evaluate_persisted_pumpswap_notification_for_radar_v4
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class PumpSwapRadarBridgeV4Tests(unittest.TestCase):
    def _record(
        self,
        run_key: str,
        key: str,
        *,
        chain_time: int,
        observed_at: int,
        wallet: str,
        tx: str,
    ) -> None:
        record_market_trade(
            acquisition_run_key=run_key,
            event_key=key,
            source_provider="test",
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=chain_time,
                observed_at=observed_at,
                wallet_address=wallet,
                venue="pumpswap",
                transaction_key=tx,
            ),
        )

    def test_v4_preserves_v3_semantics_and_reports_phase_timings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for i in range(3):
                    self._record(
                        "run",
                        f"base-{i}",
                        chain_time=800 + i,
                        observed_at=801 + i,
                        wallet=f"B{i}",
                        tx=f"base-tx-{i}",
                    )
                for i in range(5):
                    self._record(
                        "run",
                        f"fast-{i}",
                        chain_time=976 + i * 4,
                        observed_at=977 + i * 4,
                        wallet=f"F{i}",
                        tx=f"fast-tx-{i}",
                    )
                self._record(
                    "run",
                    "trigger",
                    chain_time=996,
                    observed_at=997,
                    wallet="F5",
                    tx="trigger-tx",
                )

                notification = PumpSwapLogNotification(
                    signature="trigger-tx",
                    slot=1,
                    observed_at=997,
                    trade_events=(
                        PumpSwapTradeEvent(
                            side="buy",
                            pool="POOL",
                            user="F5",
                            timestamp=996,
                            base_amount_raw=1,
                            quote_amount_raw=1,
                            event_index=0,
                        ),
                    ),
                )
                persisted = PumpSwapNormalizedPersistResult(0, 0, 0, 0, 0, 0)

                v3 = evaluate_persisted_pumpswap_notification_for_radar_v3(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )
                v4 = evaluate_persisted_pumpswap_notification_for_radar_v4(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )

        self.assertEqual(v4.signature, v3.signature)
        self.assertEqual(v4.observed_at, v3.observed_at)
        self.assertEqual(v4.affected_tokens, v3.affected_tokens)
        self.assertEqual(len(v4.hits), len(v3.hits))
        self.assertEqual(v4.hits[0].token_mint, v3.hits[0].token_mint)
        self.assertEqual(v4.hits[0].trigger, v3.hits[0].trigger)
        self.assertEqual(v4.hits[0].episode.episode_key, v3.hits[0].episode.episode_key)

        telemetry = v4.telemetry
        self.assertEqual(telemetry.token_count, 1)
        self.assertGreaterEqual(telemetry.transaction_view_read_seconds, 0.0)
        self.assertGreaterEqual(telemetry.history_read_seconds, 0.0)
        self.assertGreaterEqual(telemetry.detect_seconds, 0.0)
        self.assertGreaterEqual(telemetry.episode_assign_seconds, 0.0)
        self.assertAlmostEqual(
            telemetry.db_read_seconds,
            telemetry.transaction_view_read_seconds + telemetry.history_read_seconds,
        )

    def test_v4_no_trigger_still_reports_read_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v4-no-trigger.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._record(
                    "run",
                    "only",
                    chain_time=100,
                    observed_at=101,
                    wallet="W",
                    tx="only-tx",
                )
                notification = PumpSwapLogNotification(
                    signature="only-tx",
                    slot=1,
                    observed_at=101,
                    trade_events=(
                        PumpSwapTradeEvent(
                            side="buy",
                            pool="POOL",
                            user="W",
                            timestamp=100,
                            base_amount_raw=1,
                            quote_amount_raw=1,
                            event_index=0,
                        ),
                    ),
                )
                persisted = PumpSwapNormalizedPersistResult(0, 0, 0, 0, 0, 0)
                result = evaluate_persisted_pumpswap_notification_for_radar_v4(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )

        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual(result.hits, ())
        self.assertEqual(result.telemetry.token_count, 1)
        self.assertGreaterEqual(result.telemetry.db_read_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
