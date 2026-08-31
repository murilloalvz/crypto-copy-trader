import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection, initialize_database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_confirmation_placebo import ConfirmationPolicy, WalletCohort
from src.wallet_confirmation_study import (
    ConfirmationStudySpec,
    activate_confirmation_study,
    register_confirmation_study,
)
from src.wallet_confirmation_wave_study import (
    evaluate_wave_confirmation_study,
    materialize_wave_confirmation_events,
)
from src.wallet_forward_observations import record_wallet_forward_observation


class WalletConfirmationWaveStudyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(
            database,
            "settings",
            SimpleNamespace(database_path=Path(self.directory.name) / "study.db"),
        )
        self.patch.start()
        initialize_database()
        self.spec = ConfirmationStudySpec(
            study_key="wave-study",
            frozen_at=1_000,
            preperiod_cutoff=900,
            starts_at=1_100,
            ends_at=2_000,
            target=WalletCohort("target", ("A", "B"), "target"),
            placebos=(WalletCohort("placebo", ("C", "D"), "placebo"),),
            policy=ConfirmationPolicy(window_seconds=300, min_unique_buy_wallets=2),
            horizons_minutes=(15,),
            wave_strategy_version="wave_v3_volume_integrity",
        )
        register_confirmation_study(self.spec)

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def _signal(self, token: str, detected_at: int, return_pct: float, *, strategy=None) -> int:
        strategy = strategy or self.spec.wave_strategy_version
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO wave_signals(
                    token_mint, symbol, name, detected_at, wave_score,
                    entry_market_price_usd, entry_execution_price_usd,
                    copy_size_usd, slippage_bps, strategy_version, snapshot_json
                ) VALUES (?, ?, ?, ?, 60, 1, 1, 25, 100, ?, '{}')""",
                (token, token, token, detected_at, strategy),
            )
            signal_id = int(cursor.lastrowid)
            conn.execute(
                """INSERT INTO wave_signal_checks(
                    signal_id, horizon_minutes, target_at, observed_at,
                    market_price_usd, execution_price_usd, return_pct, pnl_usd, status
                ) VALUES (?, 15, ?, ?, 1, 1, ?, ?, 'completed')""",
                (
                    signal_id,
                    detected_at + 900,
                    detected_at + 900,
                    return_pct,
                    return_pct / 100 * 25,
                ),
            )
        return signal_id

    def _buy(self, wallet: str, token: str, observed_at: int, key: str) -> None:
        record_wallet_forward_observation(
            WalletActionObservation(
                wallet,
                token,
                "buy",
                chain_time=max(0, observed_at - 5),
                observed_at=observed_at,
            ),
            observation_key=key,
        )

    def test_materializes_same_wave_universe_and_compares_target_to_placebo(self):
        activate_confirmation_study("wave-study", now=1_100)
        self._signal("T1", 1_200, 10.0)
        self._signal("T2", 1_300, 2.0)

        self._buy("A", "T1", 1_180, "a-t1")
        self._buy("B", "T1", 1_190, "b-t1")
        self._buy("C", "T1", 1_185, "c-t1")

        self._buy("A", "T2", 1_280, "a-t2")
        self._buy("C", "T2", 1_270, "c-t2")
        self._buy("D", "T2", 1_290, "d-t2")

        materialized = materialize_wave_confirmation_events(
            "wave-study",
            as_of=1_400,
        )
        evaluation = evaluate_wave_confirmation_study("wave-study")

        self.assertEqual(materialized.opportunity_count, 2)
        self.assertEqual(materialized.expected_event_count, 4)
        self.assertEqual(materialized.newly_materialized_event_count, 4)
        rates = {item.cohort_name: item for item in evaluation.cohort_rates}
        self.assertEqual(rates["target"].opportunity_count, 2)
        self.assertEqual(rates["target"].confirmed_count, 1)
        self.assertEqual(rates["placebo"].confirmed_count, 1)
        comparison = evaluation.comparisons[0]
        self.assertAlmostEqual(
            comparison.target_minus_median_placebo_mean_return_pct,
            8.0,
        )
        self.assertEqual(
            comparison.interpretation_label,
            "DESCRIPTIVE_PLACEBO_COMPARISON",
        )

    def test_future_wallet_observation_cannot_confirm_past_wave_signal(self):
        activate_confirmation_study("wave-study", now=1_100)
        signal_id = self._signal("T", 1_200, 5.0)
        self._buy("A", "T", 1_190, "a")
        self._buy("B", "T", 1_201, "b-future")

        materialize_wave_confirmation_events("wave-study", as_of=1_300)
        with connection() as conn:
            row = conn.execute(
                """SELECT confirmed, unique_buy_wallet_count
                FROM wallet_confirmation_study_events
                WHERE study_key='wave-study' AND signal_id=? AND cohort_name='target'""",
                (signal_id,),
            ).fetchone()

        self.assertEqual(row["confirmed"], 0)
        self.assertEqual(row["unique_buy_wallet_count"], 1)

    def test_materialized_event_is_not_rewritten_by_later_backfill(self):
        activate_confirmation_study("wave-study", now=1_100)
        signal_id = self._signal("T", 1_200, 5.0)
        self._buy("A", "T", 1_190, "a")
        materialize_wave_confirmation_events("wave-study", as_of=1_300)

        # Simulates a row imported later whose timestamp claims it was observable before t.
        # Once the prospective event is frozen we do not let that rewrite the decision.
        self._buy("B", "T", 1_195, "b-late-import")
        second = materialize_wave_confirmation_events("wave-study", as_of=1_300)
        with connection() as conn:
            row = conn.execute(
                """SELECT confirmed, unique_buy_wallet_count
                FROM wallet_confirmation_study_events
                WHERE study_key='wave-study' AND signal_id=? AND cohort_name='target'""",
                (signal_id,),
            ).fetchone()

        self.assertEqual(second.newly_materialized_event_count, 0)
        self.assertEqual(row["confirmed"], 0)
        self.assertEqual(row["unique_buy_wallet_count"], 1)

    def test_wrong_strategy_and_pre_start_signals_are_excluded(self):
        activate_confirmation_study("wave-study", now=1_100)
        self._signal("OLD", 1_050, 5.0)
        self._signal("OTHER", 1_200, 5.0, strategy="wave_v2_momentum")
        self._signal("RIGHT", 1_300, 5.0)

        summary = materialize_wave_confirmation_events("wave-study", as_of=1_400)

        self.assertEqual(summary.opportunity_count, 1)
        self.assertEqual(summary.expected_event_count, 2)

    def test_frozen_but_not_active_study_cannot_materialize(self):
        with self.assertRaises(ValueError):
            materialize_wave_confirmation_events("wave-study", as_of=1_400)


if __name__ == "__main__":
    unittest.main()
