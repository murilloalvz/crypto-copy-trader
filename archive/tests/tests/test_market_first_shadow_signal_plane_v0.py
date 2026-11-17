from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmarks.market_first_capacity_harness_v0.shadow_signal_plane import (
    compare_trigger_ledgers_v0,
    derive_signal_path_comparison_v0,
)
from src import database


class MarketFirstShadowSignalPlaneV0Tests(unittest.TestCase):
    def test_trigger_ledger_exact_match(self) -> None:
        ledger = [
            {"token_mint": "A", "as_of": 10, "trigger_kind": "activity_acceleration"},
            {"token_mint": "B", "as_of": 20, "trigger_kind": "fresh_market_burst"},
        ]
        result = compare_trigger_ledgers_v0(ledger, list(ledger))
        self.assertTrue(result["exact_match"])
        self.assertEqual(result["baseline_count"], 2)
        self.assertEqual(result["shadow_count"], 2)
        self.assertIsNone(result["first_mismatch_index"])

    def test_trigger_ledger_reports_first_mismatch(self) -> None:
        baseline = [{"token_mint": "A"}, {"token_mint": "B"}]
        shadow = [{"token_mint": "A"}, {"token_mint": "C"}]
        result = compare_trigger_ledgers_v0(baseline, shadow)
        self.assertFalse(result["exact_match"])
        self.assertEqual(result["first_mismatch_index"], 1)

    def test_signal_path_projection_is_additive_and_reports_savings(self) -> None:
        result = derive_signal_path_comparison_v0(
            reduce_ms=1800.0,
            decoder_ms=2800.0,
            baseline_canonical_ms=3000.0,
            shadow_canonical_ms=500.0,
        )
        self.assertEqual(result["shared_reduce_plus_decoder_ms"], 4600.0)
        self.assertEqual(result["baseline_signal_chunk_service_ms"], 7600.0)
        self.assertEqual(result["shadow_signal_chunk_service_ms"], 5100.0)
        self.assertEqual(result["shadow_saved_ms"], 2500.0)
        self.assertFalse(result["single_chunk_reference_le_5s"])
        self.assertFalse(result["single_chunk_reference_le_2s"])

    def test_isolated_database_settings_replace_frozen_settings_object(self) -> None:
        original = database.settings
        replacement_path = Path("isolated-shadow.db")
        replacement = replace(original, database_path=replacement_path)

        self.assertIsNot(replacement, original)
        self.assertEqual(replacement.database_path, replacement_path)
        self.assertEqual(database.settings.database_path, original.database_path)

        with patch.object(database, "settings", replacement):
            self.assertIs(database.settings, replacement)
            self.assertEqual(database.settings.database_path, replacement_path)

        self.assertIs(database.settings, original)


if __name__ == "__main__":
    unittest.main()
