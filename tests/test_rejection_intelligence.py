import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection, initialize_database
from src.discovery.models import WaveTokenSnapshot
from src.prices import PermanentPriceProviderError, TemporaryPriceProviderError
from src.rejection_intelligence import (
    REJECTION_SELECTION_COOLDOWN_SECONDS,
    record_rejection_decisions,
    select_rejection_followups,
    settle_due_rejection_followups,
    summarize_rejection_lab,
)
from src.wave_radar import WaveRadarReport, WaveRadarResult


def _token(mint: str, price: float = 1.0) -> WaveTokenSnapshot:
    return WaveTokenSnapshot(
        token=mint,
        name=mint,
        symbol=mint,
        price_usd=price,
        liquidity_usd=100_000,
        market_cap_usd=500_000,
        created_at_ms=1,
        holders=100,
        buys=60,
        sells=40,
        total_transactions=100,
        volume_5m_usd=10_000,
        volume_1h_usd=50_000,
        volume_24h_usd=500_000,
        top10_pct=20,
        dev_pct=2,
        insiders_pct=3,
        snipers_pct=4,
        risk_score=2,
        lp_burn_pct=100,
        mint_authority=None,
        freeze_authority=None,
        market="test",
        pool_address="pool",
    )


def _result(mint: str, score: float, barriers: tuple[str, ...]) -> WaveRadarResult:
    return WaveRadarResult(
        token=_token(mint),
        wave_score=score,
        passed=not barriers,
        reasons=(),
        barriers=barriers,
        cautions=(),
        score_components={"test": score},
        volume_acceleration=2.0,
        buy_pressure_pct=60.0,
    )


def _report() -> WaveRadarReport:
    results = (
        _result("MULTI", 80, ("liquidity_low", "risk_high")),
        _result("LIQ", 60, ("liquidity_low",)),
        _result("RISK", 55, ("risk_high",)),
        _result("PASS", 90, ()),
    )
    return WaveRadarReport(
        analyzed_count=4,
        passed_count=1,
        results=results,
        rejected_by_reason={"liquidity_low": 2, "risk_high": 2},
    )


class RejectionIntelligenceTests(unittest.TestCase):
    def _seed_run(self, *, started_at: int = 1000) -> int:
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO wave_discovery_runs(
                    started_at, completed_at, source, requested_token_limit, policy_json, status
                ) VALUES (?, ?, 'test', 4, '{}', 'completed')""",
                (started_at, started_at + 100),
            )
            run_id = int(cursor.lastrowid)
            for mint, score, passed, barriers in (
                ("MULTI", 80, 0, '["liquidity_low","risk_high"]'),
                ("LIQ", 60, 0, '["liquidity_low"]'),
                ("RISK", 55, 0, '["risk_high"]'),
                ("PASS", 90, 1, '[]'),
            ):
                conn.execute(
                    """INSERT INTO wave_discovery_candidates(
                        run_id, token_mint, symbol, wave_score, data_valid,
                        strategy_passed, barriers_json
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)""",
                    (run_id, mint, mint, score, passed, barriers),
                )
        return run_id

    def test_records_only_rejections_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reject.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                run_id = self._seed_run()
                inserted = record_rejection_decisions(
                    _report(), run_id=run_id, detected_at=100
                )
                with connection() as conn:
                    rows = conn.execute(
                        """SELECT token_mint, snapshot_json
                        FROM wave_rejection_decisions ORDER BY token_mint"""
                    ).fetchall()
        self.assertEqual(inserted, 3)
        self.assertEqual(
            [row["token_mint"] for row in rows],
            ["LIQ", "MULTI", "RISK"],
        )
        self.assertIn('"liquidity_usd":100000', rows[0]["snapshot_json"])

    def test_selection_prefers_distinct_single_barrier_near_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reject.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                run_id = self._seed_run()
                record_rejection_decisions(_report(), run_id=run_id, detected_at=100)
                selection = select_rejection_followups(run_id, max_tokens=2)
                with connection() as conn:
                    selected = conn.execute(
                        """SELECT token_mint, selection_reason
                        FROM wave_rejection_decisions
                        WHERE selected_for_followup=1 ORDER BY token_mint"""
                    ).fetchall()
                    followups = conn.execute(
                        "SELECT * FROM wave_rejection_followups"
                    ).fetchall()
        self.assertEqual(selection.newly_selected_count, 2)
        self.assertEqual(
            [row["token_mint"] for row in selected],
            ["LIQ", "RISK"],
        )
        self.assertTrue(
            all(
                row["selection_reason"] == "single_barrier_stratum"
                for row in selected
            )
        )
        self.assertEqual(len(followups), 6)

    def test_selection_cooldown_avoids_reusing_same_mint_then_allows_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reject.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()

                run_1 = self._seed_run(started_at=1_000)
                record_rejection_decisions(_report(), run_id=run_1, detected_at=100)
                select_rejection_followups(run_1, max_tokens=1)

                run_2 = self._seed_run(started_at=2_000)
                record_rejection_decisions(_report(), run_id=run_2, detected_at=200)
                select_rejection_followups(run_2, max_tokens=1)

                run_3 = self._seed_run(started_at=3_000)
                expired_at = 100 + REJECTION_SELECTION_COOLDOWN_SECONDS + 1
                record_rejection_decisions(
                    _report(), run_id=run_3, detected_at=expired_at
                )
                select_rejection_followups(run_3, max_tokens=1)

                with connection() as conn:
                    selected = conn.execute(
                        """SELECT run_id, token_mint
                        FROM wave_rejection_decisions
                        WHERE selected_for_followup=1
                        ORDER BY run_id"""
                    ).fetchall()

        self.assertEqual(
            [(row["run_id"], row["token_mint"]) for row in selected],
            [(run_1, "LIQ"), (run_2, "RISK"), (run_3, "LIQ")],
        )

    def test_settlement_records_returns_and_defers_temporary_errors(self):
        class FakeProvider:
            def price_at(self, mint, timestamp, *, max_distance_seconds):
                if mint == "RISK":
                    raise TemporaryPriceProviderError("temporary")
                return 1.2

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reject.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                run_id = self._seed_run()
                record_rejection_decisions(_report(), run_id=run_id, detected_at=100)
                select_rejection_followups(
                    run_id,
                    max_tokens=2,
                    horizons_minutes=(5,),
                )
                settled = settle_due_rejection_followups(
                    FakeProvider(), now=1000, run_id=run_id, max_checks=10
                )
                summary = summarize_rejection_lab(run_id)
                with connection() as conn:
                    rows = conn.execute(
                        """SELECT d.token_mint, f.status, f.return_pct, f.retry_count
                        FROM wave_rejection_followups f
                        JOIN wave_rejection_decisions d ON d.id=f.rejection_id
                        ORDER BY d.token_mint"""
                    ).fetchall()
        self.assertEqual(
            (settled.attempted, settled.completed, settled.deferred),
            (2, 1, 1),
        )
        self.assertEqual(rows[0]["status"], "completed")
        self.assertAlmostEqual(rows[0]["return_pct"], 20.0)
        self.assertEqual(rows[1]["status"], "pending")
        self.assertEqual(rows[1]["retry_count"], 1)
        self.assertEqual(summary.horizons[0].coverage_pct, 50.0)

        isolated = {
            (item.barrier, item.horizon_minutes): item
            for item in summary.single_barrier_horizons
        }
        self.assertEqual(isolated[("liquidity_low", 5)].coverage_pct, 100.0)
        self.assertAlmostEqual(
            isolated[("liquidity_low", 5)].mean_return_pct,
            20.0,
        )
        self.assertEqual(isolated[("risk_high", 5)].coverage_pct, 0.0)
        self.assertEqual(isolated[("risk_high", 5)].pending_count, 1)

    def test_permanent_provider_error_fails_followup(self):
        class FakeProvider:
            def price_at(self, mint, timestamp, *, max_distance_seconds):
                raise PermanentPriceProviderError("gone", code="no_pool")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reject.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                run_id = self._seed_run()
                record_rejection_decisions(_report(), run_id=run_id, detected_at=100)
                select_rejection_followups(
                    run_id,
                    max_tokens=1,
                    horizons_minutes=(5,),
                )
                settled = settle_due_rejection_followups(
                    FakeProvider(), now=1000, run_id=run_id
                )
        self.assertEqual(
            (settled.attempted, settled.failed, settled.deferred),
            (1, 1, 0),
        )


if __name__ == "__main__":
    unittest.main()
