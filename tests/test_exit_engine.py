import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database, rows
from src.exit_engine import (
    EXIT_POLICIES,
    ensure_exit_experiment,
    enroll_forward_signals,
    update_exit_positions,
)
from src.prices import (
    PermanentPriceProviderError,
    ProviderCycleBudgetExhausted,
    TemporaryPriceProviderError,
)
from src.strategy_versions import WAVE_STRATEGY_VERSION


class SequenceProvider:
    def __init__(self, prices):
        self.prices = prices
        self.timestamps = []

    def price_at(self, _token, timestamp, *, max_distance_seconds=3_600):
        self.timestamps.append(timestamp)
        return self.prices[timestamp]


class FailingProvider:
    def price_at(self, _token, _timestamp, *, max_distance_seconds=3_600):
        raise PermanentPriceProviderError("sem candle", code="no_historical_candle")


class TemporaryFailingProvider:
    def price_at(self, _token, _timestamp, *, max_distance_seconds=3_600):
        raise TemporaryPriceProviderError("rate limited")


class BudgetFailingProvider:
    def price_at(self, _token, _timestamp, *, max_distance_seconds=3_600):
        raise ProviderCycleBudgetExhausted("cycle budget")


class DynamicFailFixedSuccessProvider:
    def price_at(self, _token, timestamp, *, max_distance_seconds=3_600):
        if timestamp == 1920:
            raise PermanentPriceProviderError("dynamic missing", code="distant_historical_candle")
        if timestamp == 1900:
            return 1.0
        raise AssertionError(timestamp)


class OrderingProvider:
    def __init__(self):
        self.tokens = []

    def price_at(self, token, _timestamp, *, max_distance_seconds=3_600):
        self.tokens.append(token)
        return 1.0


class ExitEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "exit.db"
        self.patch = patch.object(
            database, "settings", SimpleNamespace(database_path=self.path)
        )
        self.patch.start()
        initialize_database()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def insert_signal(self, detected_at, token_mint="token"):
        with database.connection() as conn:
            return conn.execute(
                """INSERT INTO wave_signals
                (token_mint, detected_at, wave_score, entry_market_price_usd,
                 entry_execution_price_usd, copy_size_usd, slippage_bps,
                 strategy_version, snapshot_json)
                VALUES (?, ?, 70, 1, 1.01, 25, 100, ?, '{}')""",
                (token_mint, detected_at, WAVE_STRATEGY_VERSION),
            ).lastrowid

    def test_forward_boundary_excludes_existing_signals_and_is_idempotent(self):
        old_id = self.insert_signal(800, "old")
        experiment = ensure_exit_experiment(activated_at=900)
        new_id = self.insert_signal(1_000, "new")

        first = enroll_forward_signals(experiment["id"])
        second = enroll_forward_signals(experiment["id"])
        signal_ids = {
            item["signal_id"] for item in rows("SELECT signal_id FROM exit_positions")
        }

        self.assertEqual(experiment["start_after_signal_id"], old_id)
        self.assertEqual(signal_ids, {new_id})
        self.assertEqual(first.created_positions, len(EXIT_POLICIES))
        self.assertEqual(second.created_positions, 0)

    def test_default_forward_experiment_preregisters_one_minute_observations(self):
        experiment = ensure_exit_experiment(activated_at=900)

        self.assertEqual(experiment["expected_observation_interval_seconds"], 60)

    def test_policies_react_independently_to_only_observed_prices(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])
        provider = SequenceProvider(
            {1200: 1.25, 1500: 1.10, 1900: 0.90, 1920: 0.90, 4600: 1.0}
        )

        update_exit_positions(provider, now=1_301, experiment_id=experiment["id"])
        update_exit_positions(provider, now=1_601, experiment_id=experiment["id"])
        update_exit_positions(provider, now=1_981, experiment_id=experiment["id"])
        update_exit_positions(provider, now=4_681, experiment_id=experiment["id"])
        final = update_exit_positions(provider, now=4_681, experiment_id=experiment["id"])

        positions = {
            item["policy_version"]: item
            for item in rows(
                """SELECT ep.policy_version, p.* FROM exit_positions p
                JOIN exit_policies ep ON ep.id=p.policy_id"""
            )
        }
        self.assertEqual(provider.timestamps, [1200, 1500, 1920, 1900, 4600])
        self.assertEqual(positions["take_profit_20_v1"]["exit_at"], 1200)
        self.assertEqual(positions["trailing_stop_10_v1"]["exit_at"], 1500)
        self.assertEqual(positions["stop_loss_10_v1"]["exit_at"], 1920)
        self.assertEqual(positions["fixed_15m_v1"]["exit_at"], 1900)
        self.assertEqual(positions["fixed_60m_v1"]["exit_at"], 4600)
        self.assertAlmostEqual(positions["fixed_15m_v1"]["mfe_pct"], 23.762376, places=5)
        self.assertAlmostEqual(positions["fixed_15m_v1"]["mae_pct"], -10.891089, places=5)
        self.assertEqual(positions["fixed_15m_v1"]["observation_count"], 3)
        self.assertEqual(final.closed_positions, 0)
        self.assertEqual(final.open_signals, 0)
        self.assertEqual(len(rows("SELECT * FROM exit_positions")), len(EXIT_POLICIES))

    def test_open_signal_load_counts_entry_once_not_once_per_policy(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        result = update_exit_positions(
            SequenceProvider({1200: 1.0}), now=1_301, experiment_id=experiment["id"]
        )

        self.assertEqual(result.open_positions, len(EXIT_POLICIES))
        self.assertEqual(result.open_signals, 1)

    def test_gap_uses_first_observed_price_not_the_threshold(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        update_exit_positions(
            SequenceProvider({1200: 0.80}), now=1_301, experiment_id=experiment["id"]
        )
        stop = rows(
            """SELECT p.* FROM exit_positions p JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE ep.policy_version='stop_loss_10_v1'"""
        )[0]

        self.assertEqual(stop["exit_market_price_usd"], 0.80)
        self.assertLess(stop["net_return_pct"], -20)
        self.assertEqual(stop["exit_reason"], "stop_loss")

    def test_missing_price_is_audited_and_can_fail_due_positions(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        result = update_exit_positions(
            FailingProvider(), now=1_981, experiment_id=experiment["id"], max_attempts=1
        )

        observation = rows("SELECT * FROM exit_price_observations")[0]
        fixed_15 = rows(
            """SELECT p.status, p.error_code FROM exit_positions p
            JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE ep.policy_version='fixed_15m_v1'"""
        )[0]
        self.assertEqual(result.price_failures, 2)
        self.assertEqual(observation["status"], "failed")
        self.assertEqual(observation["error_code"], "no_historical_candle")
        self.assertEqual(fixed_15["status"], "failed")

    def test_temporary_failure_at_due_time_uses_target_counter_not_old_dynamic_failures(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])
        with database.connection() as conn:
            conn.execute(
                "UPDATE exit_positions SET retry_count=9, dynamic_retry_count=9"
            )

        update_exit_positions(
            TemporaryFailingProvider(), now=1_981,
            experiment_id=experiment["id"], max_attempts=3
        )

        fixed_15 = rows(
            """SELECT p.* FROM exit_positions p JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE ep.policy_version='fixed_15m_v1'"""
        )[0]
        self.assertEqual(fixed_15["status"], "open")
        self.assertEqual(fixed_15["target_retry_count"], 1)

    def test_repeated_temporary_target_failures_never_become_permanent_position_failure(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        for _ in range(4):
            update_exit_positions(
                TemporaryFailingProvider(), now=1_981,
                experiment_id=experiment["id"], max_attempts=3
            )

        fixed_15 = rows(
            """SELECT p.* FROM exit_positions p JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE ep.policy_version='fixed_15m_v1'"""
        )[0]
        self.assertEqual(fixed_15["status"], "open")
        self.assertEqual(fixed_15["target_retry_count"], 4)

    def test_runtime_v3_marks_new_positions_and_observations(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])
        update_exit_positions(
            SequenceProvider({1200: 1.0}), now=1_301, experiment_id=experiment["id"]
        )
        self.assertEqual(
            {r["runtime_version"] for r in rows("SELECT runtime_version FROM exit_positions")},
            {"exit_runtime_v3_adaptive_provider_budget"},
        )
        self.assertEqual(
            rows("SELECT runtime_version FROM exit_price_observations")[0]["runtime_version"],
            "exit_runtime_v3_adaptive_provider_budget",
        )

    def test_cycle_budget_deferral_does_not_consume_position_retry_counters(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        update_exit_positions(
            BudgetFailingProvider(), now=1_981,
            experiment_id=experiment["id"], max_attempts=1
        )

        positions = rows("SELECT * FROM exit_positions ORDER BY id")
        self.assertTrue(all(row["status"] == "open" for row in positions))
        self.assertTrue(all(row["retry_count"] == 0 for row in positions))
        self.assertTrue(all(row["dynamic_retry_count"] == 0 for row in positions))
        self.assertTrue(all(row["target_retry_count"] == 0 for row in positions))

    def test_dynamic_failure_does_not_fail_fixed_time_position(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000)
        enroll_forward_signals(experiment["id"])

        update_exit_positions(
            DynamicFailFixedSuccessProvider(), now=1_981,
            experiment_id=experiment["id"], max_attempts=1
        )

        fixed_15 = rows(
            """SELECT p.* FROM exit_positions p JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE ep.policy_version='fixed_15m_v1'"""
        )[0]
        self.assertEqual(fixed_15["status"], "closed")
        self.assertEqual(fixed_15["exit_at"], 1900)
        self.assertEqual(fixed_15["dynamic_retry_count"], 0)

    def test_signal_order_rotates_deterministically_by_observation_minute(self):
        experiment = ensure_exit_experiment(activated_at=900)
        self.insert_signal(1_000, "one")
        self.insert_signal(1_001, "two")
        self.insert_signal(1_002, "three")
        enroll_forward_signals(experiment["id"])
        provider = OrderingProvider()

        update_exit_positions(provider, now=1_301, experiment_id=experiment["id"])

        self.assertEqual(provider.tokens, ["three", "one", "two"])


if __name__ == "__main__":
    unittest.main()
