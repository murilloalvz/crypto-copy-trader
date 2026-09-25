from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import (
    inspect_known_market_lifecycle,
    record_market_lifecycle,
)
from src.market_opportunity_radar import MarketLifecycleObservation
from src.post_transition_reacceleration_v0 import (
    PostTransitionResearchState,
)
from src.post_transition_snapshot_journal_v0 import (
    ImmutableSnapshotJournalV0,
    verify_snapshot_journal,
)
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_stream import PumpSwapCreatePoolEvent, PumpSwapTradeEvent


class PostTransitionResearchPersistenceV0Tests(unittest.TestCase):
    def test_lineage_lookup_distinguishes_missing_found_and_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(
                database,
                "settings",
                SimpleNamespace(database_path=path),
            ):
                missing = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=99,
                    venue="pump_bonding_curve",
                )
                self.assertEqual(missing.status, "MISSING")
                self.assertIsNone(missing.lifecycle)

                record_market_lifecycle(
                    acquisition_run_key="run-a",
                    event_key="birth-a",
                    source_provider="pump",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=100,
                        observed_at=105,
                        venue="pump_bonding_curve",
                    ),
                )
                found = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=150,
                    venue="pump_bonding_curve",
                )
                self.assertEqual(found.status, "FOUND")
                self.assertEqual(found.row_count, 1)
                self.assertEqual(found.distinct_identity_count, 1)
                self.assertIsNotNone(found.lifecycle)

                record_market_lifecycle(
                    acquisition_run_key="run-b",
                    event_key="birth-b",
                    source_provider="conflict",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=101,
                        observed_at=160,
                        venue="pump_bonding_curve",
                    ),
                )
                still_found = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=150,
                    venue="pump_bonding_curve",
                )
                self.assertEqual(still_found.status, "FOUND")

                ambiguous = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=200,
                    venue="pump_bonding_curve",
                )
                self.assertEqual(ambiguous.status, "AMBIGUOUS")
                self.assertIsNone(ambiguous.lifecycle)
                self.assertEqual(ambiguous.distinct_identity_count, 2)

    def _snapshot(self):
        create = PumpSwapCreatePoolEvent(
            pool="POOL",
            creator="CREATOR",
            base_mint="TOKEN",
            quote_mint=WSOL_MINT,
            base_mint_decimals=6,
            quote_mint_decimals=9,
            timestamp=1000,
        )
        state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=1001,
            pump_birth_market_started_at=900,
            pump_birth_observed_at=905,
        )
        state.ingest_trade(
            PumpSwapTradeEvent(
                side="buy",
                pool="POOL",
                user="wallet",
                timestamp=1002,
                base_amount_raw=100_000_000,
                quote_amount_raw=1_000_000_000,
            ),
            observed_at=1002,
            event_key="trade",
            transaction_key="tx",
            arrival_index=0,
        )
        return state.snapshot(
            as_of_observed_at=1002,
            max_arrival_index=0,
        )

    def test_snapshot_journal_is_hash_chained_and_idempotent(self):
        snapshot = self._snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.jsonl"
            journal = ImmutableSnapshotJournalV0(path)
            inserted, first = journal.append(snapshot)
            replayed, second = journal.append(snapshot)

            self.assertTrue(inserted)
            self.assertFalse(replayed)
            self.assertEqual(first, second)
            summary = verify_snapshot_journal(path)
            self.assertEqual(summary["record_count"], 1)
            self.assertTrue(summary["hash_chain_valid"])
            self.assertEqual(
                summary["final_record_hash_sha256"],
                first["record_hash_sha256"],
            )

    def test_snapshot_journal_detects_tampering_on_reopen(self):
        snapshot = self._snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.jsonl"
            ImmutableSnapshotJournalV0(path).append(snapshot)
            row = json.loads(path.read_text(encoding="utf-8"))
            row["snapshot"]["current_price"] = 999.0
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "record hash mismatch"):
                ImmutableSnapshotJournalV0(path)


if __name__ == "__main__":
    unittest.main()
