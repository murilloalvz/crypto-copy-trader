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

import market_integrity_lab


def _token(mint: str) -> WaveTokenSnapshot:
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
        volume_5m_usd=12_000,
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


class MarketIntegrityCliTests(unittest.TestCase):
    def test_loads_wrapped_signal_and_raw_rejection_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integrity.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                initialize_database()
                ensure_rejection_schema()
                accepted = _token("ACCEPTED")
                rejected = _token("REJECTED")
                with connection() as conn:
                    conn.execute(
                        """INSERT INTO wave_signals(
                            token_mint, symbol, name, detected_at, wave_score,
                            entry_market_price_usd, entry_execution_price_usd,
                            copy_size_usd, slippage_bps, strategy_version, snapshot_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            accepted.token,
                            accepted.symbol,
                            accepted.name,
                            200,
                            60,
                            1,
                            1,
                            25,
                            100,
                            "wave_v3_volume_integrity",
                            json.dumps({"token": asdict(accepted)}),
                        ),
                    )
                    run = conn.execute(
                        """INSERT INTO wave_discovery_runs(
                            started_at, completed_at, source, requested_token_limit,
                            policy_json, status
                        ) VALUES (1000, 1100, 'test', 1, '{}', 'completed')"""
                    )
                    conn.execute(
                        """INSERT INTO wave_rejection_decisions(
                            run_id, token_mint, symbol, detected_at, entry_price_usd,
                            wave_score, data_valid, barrier_count, barriers_json,
                            cautions_json, score_components_json, snapshot_json
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, '[\"risk_high\"]', '[]', '{}', ?)""",
                        (
                            int(run.lastrowid),
                            rejected.token,
                            rejected.symbol,
                            300,
                            1,
                            50,
                            json.dumps(asdict(rejected)),
                        ),
                    )

                records = market_integrity_lab._load_records(1, 1)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["token"].token, "REJECTED")
        self.assertEqual(records[1]["token"].token, "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
