from __future__ import annotations

from types import SimpleNamespace
import unittest

from benchmarks.burst_participation_structure_discovery_v0.run import (
    CATASTROPHIC_RETURN_PCT,
    FEATURE_NAMES,
)


class BurstParticipationStructureDiscoveryV0Tests(unittest.TestCase):
    def test_feature_family_is_closed_and_excludes_v55_repetition(self):
        self.assertEqual(
            FEATURE_NAMES,
            (
                "flow30_top1_wallet_event_share_pct",
                "flow30_top3_wallet_event_share_pct",
                "flow60_top1_wallet_event_share_pct",
                "flow60_top3_wallet_event_share_pct",
                "flow30_buy_sell_wallet_overlap_share_pct",
                "flow60_buy_sell_wallet_overlap_share_pct",
            ),
        )
        self.assertNotIn(
            "flow30_repeated_wallet_event_share_pct",
            FEATURE_NAMES,
        )

    def test_catastrophic_tail_threshold_is_frozen(self):
        self.assertEqual(CATASTROPHIC_RETURN_PCT, -80.0)


if __name__ == "__main__":
    unittest.main()
