from __future__ import annotations

from pathlib import Path
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 import (
    DEFAULT_SNIPER_POLICY,
    _screening_preflight,
)
from src.launch_burst_sniper_v1 import EXPECTED_POLICY_HASH


class LaunchBurstSniperRunnerV1Tests(unittest.TestCase):
    def test_preflight_validates_frozen_policy_before_live(self):
        result = _screening_preflight(
            sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
            duration_seconds=900,
        )
        self.assertTrue(result["validated_before_acquisition"])
        self.assertEqual(result["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        self.assertEqual(result["screening_run_duration_seconds"], 900)
        self.assertEqual(result["active_chain_profile"], "solana:mainnet:pumpfun")

    def test_screening_duration_cannot_be_changed_in_place(self):
        with self.assertRaisesRegex(ValueError, "screening duration is frozen at 900s"):
            _screening_preflight(
                sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
                duration_seconds=300,
            )


if __name__ == "__main__":
    unittest.main()
