from __future__ import annotations

from types import SimpleNamespace
import unittest

from benchmarks.burst_incremental_tournament_v0.run import (
    _take,
)


class BurstIncrementalTournamentV0Tests(unittest.TestCase):
    def _row(self, repetition, impact):
        return SimpleNamespace(
            features={
                "flow30_repeated_wallet_event_share_pct": repetition,
                "entry_price_impact_pct_points": impact,
            }
        )

    def test_low_repetition_rule(self):
        cuts = {
            "repetition_low_max": 10.0,
            "repetition_mid_max": 20.0,
            "impact_closeness_low_max": -2.0,
            "impact_closeness_mid_max": -0.5,
        }
        self.assertTrue(
            _take(self._row(5.0, -1.0), "LOW_REPETITION", cuts)
        )
        self.assertFalse(
            _take(self._row(15.0, -1.0), "LOW_REPETITION", cuts)
        )

    def test_impact_close_rule_uses_distance_to_zero(self):
        cuts = {
            "repetition_low_max": 10.0,
            "repetition_mid_max": 20.0,
            "impact_closeness_low_max": -2.0,
            "impact_closeness_mid_max": -0.5,
        }
        self.assertTrue(
            _take(self._row(15.0, -0.1), "IMPACT_CLOSE_TO_ZERO", cuts)
        )
        self.assertFalse(
            _take(self._row(15.0, -3.0), "IMPACT_CLOSE_TO_ZERO", cuts)
        )

    def test_and_requires_both(self):
        cuts = {
            "repetition_low_max": 10.0,
            "repetition_mid_max": 20.0,
            "impact_closeness_low_max": -2.0,
            "impact_closeness_mid_max": -0.5,
        }
        self.assertTrue(
            _take(
                self._row(5.0, -0.1),
                "LOW_REPETITION_AND_IMPACT_CLOSE",
                cuts,
            )
        )
        self.assertFalse(
            _take(
                self._row(15.0, -0.1),
                "LOW_REPETITION_AND_IMPACT_CLOSE",
                cuts,
            )
        )
        self.assertFalse(
            _take(
                self._row(5.0, -3.0),
                "LOW_REPETITION_AND_IMPACT_CLOSE",
                cuts,
            )
        )


if __name__ == "__main__":
    unittest.main()
