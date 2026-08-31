import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection, initialize_database
from src.discovery.models import WaveTokenSnapshot
from src.rejection_intelligence import ensure_rejection_schema

import opportunity_context


def _token(mint: str, volume_5m: float) -> WaveTokenSnapshot:
    return WaveTokenSnapshot(
        token=mint,
        name=mint,
        symbol=mint,
        price_usd=1.0,
        liquidity_usd=100_000,
        market_cap_usd=500_000,
        created_at_ms=1,
        holders=100,
        buys=60,
        sells=40,
        total_transactions=100,
        volume_5m_usd=volume_5m,
        volume_1h_usd=60_000,
        volume_24h_usd=600_000,
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


class OpportunityContextCliTests(unittest.TestCase):
    def test_latest_market_snapshot_respects_as_of_and_can_use_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                ensure_rejection_schema()
                signal_token = _token("T", 10_000)
                reject_token = _token("T", 20_000)
                future_token = _token("T", 30_000)
                with connection() as conn:
                    conn.execute(
                        """INSERT INTO wave_signals(
                            token_mint, symbol, name, detected_at, wave_score,
                            entry_market_price_usd, entry_execution_price_usd,
                            copy_size_usd, slippage_bps, strategy_version, snapshot_json
                        ) VALUES ('T','T','T',100,60,1,1,25,100,'wave_v3_volume_integrity',?)""",
                        (json.dumps({"token": asdict(signal_token)}),),
                    )
                    run = conn.execute(
                        """INSERT INTO wave_discovery_runs(
                            started_at, completed_at, source, requested_token_limit,
                            policy_json, status
                        ) VALUES (1000, 1100, 'test', 1, '{}', 'completed')"""
                    )
                    for detected_at, snapshot in ((200, reject_token), (400, future_token)):
                        conn.execute(
                            """INSERT INTO wave_rejection_decisions(
                                run_id, token_mint, symbol, detected_at, entry_price_usd,
                                wave_score, data_valid, barrier_count, barriers_json,
                                cautions_json, score_components_json, snapshot_json
                            ) VALUES (?, 'T','T',?,1,50,1,1,'[\"risk_high\"]','[]','{}',?)""",
                            (int(run.lastrowid), detected_at, json.dumps(asdict(snapshot))),
                        )

                snapshot = opportunity_context._latest_market_snapshot("T", 300)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.volume_5m_usd, 20_000)

    def test_no_snapshot_before_first_persisted_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                ensure_rejection_schema()
                with connection() as conn:
                    token = _token("T", 10_000)
                    conn.execute(
                        """INSERT INTO wave_signals(
                            token_mint, symbol, name, detected_at, wave_score,
                            entry_market_price_usd, entry_execution_price_usd,
                            copy_size_usd, slippage_bps, strategy_version, snapshot_json
                        ) VALUES ('T','T','T',100,60,1,1,25,100,'wave_v3_volume_integrity',?)""",
                        (json.dumps({"token": asdict(token)}),),
                    )
                snapshot = opportunity_context._latest_market_snapshot("T", 99)

        self.assertIsNone(snapshot)


if __name__ == "__main__":
    unittest.main()
