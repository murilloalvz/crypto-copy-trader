import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.shadow_execution_store import (
    ShadowDecision,
    close_shadow_run,
    load_shadow_decisions,
    record_shadow_decision,
    start_shadow_run,
)


def _decision(
    *,
    key: str = "d1",
    decided_at: int = 120,
    quote_observed_at: int = 119,
) -> ShadowDecision:
    return ShadowDecision(
        decision_key=key,
        token_mint="T",
        side="buy",
        decided_at=decided_at,
        quote_observed_at=quote_observed_at,
        quote_source="test",
        market_price_usd=10.0,
        expected_execution_price_usd=10.1,
        notional_usd=25.0,
        reason="candidate_signal",
        context_json='{"wallet_confirmations":1}',
    )


class ShadowExecutionStoreTests(unittest.TestCase):
    def test_run_config_is_frozen_and_decisions_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = start_shadow_run(
                    run_key="run-1",
                    strategy_version="candidate_v1",
                    activated_at=100,
                    config={"slippage_bps": 100},
                )
                same = start_shadow_run(
                    run_key="run-1",
                    strategy_version="candidate_v1",
                    activated_at=100,
                    config={"slippage_bps": 100},
                )
                self.assertEqual(run.id, same.id)
                self.assertTrue(record_shadow_decision(run.id, _decision()))
                self.assertFalse(record_shadow_decision(run.id, _decision()))
                rows = load_shadow_decisions(run.id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].decision_key, "d1")

    def test_existing_run_cannot_be_silently_reconfigured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                start_shadow_run(
                    run_key="run-1",
                    strategy_version="candidate_v1",
                    activated_at=100,
                    config={"slippage_bps": 100},
                )
                with self.assertRaises(ValueError):
                    start_shadow_run(
                        run_key="run-1",
                        strategy_version="candidate_v1",
                        activated_at=100,
                        config={"slippage_bps": 300},
                    )

    def test_decision_cannot_use_future_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = start_shadow_run(
                    run_key="run-1",
                    strategy_version="candidate_v1",
                    activated_at=100,
                    config={},
                )
                with self.assertRaises(ValueError):
                    record_shadow_decision(
                        run.id,
                        _decision(decided_at=120, quote_observed_at=121),
                    )

    def test_decision_cannot_predate_run_and_closed_run_rejects_new_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = start_shadow_run(
                    run_key="run-1",
                    strategy_version="candidate_v1",
                    activated_at=100,
                    config={},
                )
                with self.assertRaises(ValueError):
                    record_shadow_decision(
                        run.id,
                        _decision(decided_at=99, quote_observed_at=99),
                    )
                close_shadow_run(run.id)
                with self.assertRaises(ValueError):
                    record_shadow_decision(run.id, _decision())


if __name__ == "__main__":
    unittest.main()
