from __future__ import annotations

import unittest

from benchmarks.launch_burst_concentration_decay_v0.confirm import (
    INCONCLUSIVE,
    KEEP,
    KILL,
    classify_confirmation,
)


class LaunchBurstConcentrationDecayConfirmationV1Tests(unittest.TestCase):
    def test_keep_requires_underlying_keep_with_support(self):
        classification, reason = classify_confirmation(
            {
                "decision": "KEEP",
                "decision_rule_checks": {
                    "minimum_sample_and_frequency_met": True,
                },
            }
        )
        self.assertEqual(classification, KEEP)
        self.assertIn("all_frozen_keep_conditions", reason)

    def test_iterate_with_sufficient_support_becomes_kill(self):
        classification, reason = classify_confirmation(
            {
                "decision": "ITERATE",
                "decision_rule_checks": {
                    "minimum_sample_and_frequency_met": True,
                },
            }
        )
        self.assertEqual(classification, KILL)
        self.assertIn("absolute_keep", reason)

    def test_kill_stays_kill(self):
        classification, _reason = classify_confirmation(
            {
                "decision": "KILL",
                "decision_rule_checks": {
                    "minimum_sample_and_frequency_met": True,
                },
            }
        )
        self.assertEqual(classification, KILL)

    def test_insufficient_support_is_inconclusive(self):
        classification, reason = classify_confirmation(
            {
                "decision": "ITERATE",
                "decision_rule_checks": {
                    "minimum_sample_and_frequency_met": False,
                },
            }
        )
        self.assertEqual(classification, INCONCLUSIVE)
        self.assertIn("support", reason)


if __name__ == "__main__":
    unittest.main()
