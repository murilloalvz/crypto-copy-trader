from __future__ import annotations

import unittest

import participant_quality_native_memory_resume_v0 as resume


class ParticipantQualityNativeMemoryResumeV0Tests(unittest.TestCase):
    def test_valid_slots_are_exactly_four(self):
        self.assertEqual(
            resume.VALID_RUN_KEYS,
            (
                "participant-quality-native-memory-20260924-01-M1",
                "participant-quality-native-memory-20260924-01-M2R2",
                "participant-quality-native-memory-20260924-01-M3",
                "participant-quality-native-memory-20260924-01-M4",
            ),
        )

    def test_failed_m2_attempts_are_excluded(self):
        self.assertEqual(
            resume.EXCLUDED_HISTORY_RUN_KEYS,
            (
                "participant-quality-native-memory-20260924-01-M2",
                "participant-quality-native-memory-20260924-01-M2R1",
            ),
        )
        self.assertNotIn(
            resume.INVALID_M2,
            resume.VALID_RUN_KEYS,
        )


if __name__ == "__main__":
    unittest.main()
