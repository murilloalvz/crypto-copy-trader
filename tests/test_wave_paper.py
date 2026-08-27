import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database, rows
from src.prices import PermanentPriceProviderError
from src.wave_paper import (
    LEGACY_WAVE_STRATEGY_VERSION,
    WAVE_STRATEGY_VERSION,
    backfill_wave_strategy_versions,
    latest_paper_signals,
    record_paper_signals,
    update_due_paper_checks,
)
from src.wave_radar import build_wave_radar_report
from tests.test_wave_radar import token


class FakePriceProvider:
    def __init__(self, price):
        self.price = price
        self.timestamps = []

    def price_at(self, _token, timestamp, *, max_distance_seconds=3_600):
        self.timestamps.append(timestamp)
        self.max_distance_seconds = max_distance_seconds
        return self.price


class FailingPriceProvider:
    def price_at(self, _token, _timestamp, *, max_distance_seconds=3_600):
        raise PermanentPriceProviderError(
            "Candle histórico distante.",
            code="distant_historical_candle",
        )


class WavePaperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "wave-paper.db"
        self.settings_patch = patch.object(
            database, "settings", SimpleNamespace(database_path=self.path)
        )
        self.settings_patch.start()
        initialize_database()

    def tearDown(self):
        self.settings_patch.stop()
        self.directory.cleanup()

    def approved_results(self):
        return build_wave_radar_report([token()]).results

    def test_records_one_signal_with_three_horizons_and_cooldown(self):
        created = record_paper_signals(
            self.approved_results(),
            detected_at=1_000,
            copy_size_usd=25,
            slippage_bps=100,
        )
        duplicate = record_paper_signals(
            self.approved_results(),
            detected_at=1_300,
            copy_size_usd=25,
            slippage_bps=100,
        )

        self.assertEqual(created, 1)
        self.assertEqual(duplicate, 0)
        self.assertEqual(rows("SELECT COUNT(*) AS total FROM wave_signals")[0]["total"], 1)
        self.assertEqual(
            rows("SELECT COUNT(*) AS total FROM wave_signal_checks")[0]["total"], 3
        )
        signal = rows("SELECT strategy_version FROM wave_signals")[0]
        self.assertEqual(signal["strategy_version"], WAVE_STRATEGY_VERSION)

    def test_backfills_only_historical_signals_that_match_momentum_gate(self):
        base_snapshot = {
            "wave_score": 61,
            "token": {"volume_5m_usd": 10_000, "volume_1h_usd": 120_000},
        }
        momentum_snapshot = {
            "wave_score": 61,
            "token": {"volume_5m_usd": 17_000, "volume_1h_usd": 120_000},
        }
        with database.connection() as conn:
            conn.executemany(
                """INSERT INTO wave_signals
                (token_mint, detected_at, wave_score, entry_market_price_usd,
                entry_execution_price_usd, copy_size_usd, slippage_bps,
                strategy_version, snapshot_json)
                VALUES (?, ?, 61, 1, 1.01, 25, 100, ?, ?)""",
                [
                    (
                        "baseline-token",
                        1_000,
                        LEGACY_WAVE_STRATEGY_VERSION,
                        json.dumps(base_snapshot),
                    ),
                    (
                        "momentum-token",
                        1_001,
                        LEGACY_WAVE_STRATEGY_VERSION,
                        json.dumps(momentum_snapshot),
                    ),
                ],
            )

        updated = backfill_wave_strategy_versions()
        versions = {
            item["token_mint"]: item["strategy_version"]
            for item in rows("SELECT token_mint, strategy_version FROM wave_signals")
        }

        self.assertEqual(updated, 1)
        self.assertEqual(versions["baseline-token"], LEGACY_WAVE_STRATEGY_VERSION)
        self.assertEqual(versions["momentum-token"], WAVE_STRATEGY_VERSION)

    def test_prices_exact_due_horizons_and_completes_signal(self):
        record_paper_signals(
            self.approved_results(),
            detected_at=1_000,
            copy_size_usd=25,
            slippage_bps=100,
        )
        provider = FakePriceProvider(0.0011)

        first = update_due_paper_checks(provider, now=1_301)
        final = update_due_paper_checks(provider, now=4_601)
        signal = latest_paper_signals(1)[0]

        self.assertEqual(first, {"completed": 1, "failed": 0, "pending": 2})
        self.assertEqual(final, {"completed": 2, "failed": 0, "pending": 0})
        self.assertEqual(provider.timestamps, [1_300, 1_900, 4_600])
        self.assertEqual(provider.max_distance_seconds, 120)
        self.assertEqual(signal["status"], "completed")
        self.assertAlmostEqual(signal["checks"][0]["return_pct"], 7.821782, places=5)
        self.assertAlmostEqual(signal["checks"][0]["pnl_usd"], 1.955445, places=5)

    def test_records_structured_price_failure_code(self):
        record_paper_signals(
            self.approved_results(),
            detected_at=1_000,
            copy_size_usd=25,
            slippage_bps=100,
        )

        result = update_due_paper_checks(FailingPriceProvider(), now=1_301)
        check = rows(
            """SELECT status, error, error_code, retry_count
            FROM wave_signal_checks WHERE horizon_minutes=5"""
        )[0]

        self.assertEqual(result, {"completed": 0, "failed": 1, "pending": 2})
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["error_code"], "distant_historical_candle")
        self.assertIn("Candle histórico distante", check["error"])
        self.assertEqual(check["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
