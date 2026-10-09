from __future__ import annotations

import unittest

import participant_quality_native_memory_v1 as memory


class ParticipantQualityNativeMemoryV1Tests(unittest.TestCase):
    def test_version_declares_role_normalized_epoch(self):
        self.assertEqual(
            memory.VERSION,
            "participant_quality_native_memory_v1_role_normalized_epoch",
        )

    def test_memory_run_count_remains_four(self):
        self.assertEqual(memory.MEMORY_RUN_COUNT, 4)


if __name__ == "__main__":
    unittest.main()
