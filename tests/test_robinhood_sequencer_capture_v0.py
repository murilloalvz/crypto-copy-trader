import unittest

from benchmarks.robinhood_sequencer_shadow_v0.capture import SequenceTrackerV0


class RobinhoodSequencerCaptureV0Tests(unittest.TestCase):
    def test_contiguous_sequences_advance_reconnect_cursor(self):
        tracker = SequenceTrackerV0()
        for value in (100, 101, 102):
            tracker.observe(value)
        row = tracker.to_dict()
        self.assertEqual(row["message_count"], 3)
        self.assertEqual(row["first_sequence"], 100)
        self.assertEqual(row["last_sequence"], 102)
        self.assertEqual(row["next_requested_sequence"], 103)
        self.assertEqual(row["missing_sequence_count"], 0)
        self.assertEqual(row["duplicate_or_reordered_count"], 0)
        self.assertEqual(row["gaps"], [])

    def test_gap_is_counted_exactly_and_cursor_moves_to_new_high_watermark(self):
        tracker = SequenceTrackerV0()
        tracker.observe(10)
        tracker.observe(14)
        row = tracker.to_dict()
        self.assertEqual(row["missing_sequence_count"], 3)
        self.assertEqual(
            row["gaps"],
            [{
                "after_sequence": 10,
                "next_observed_sequence": 14,
                "missing_count": 3,
            }],
        )
        self.assertEqual(row["last_sequence"], 14)
        self.assertEqual(row["next_requested_sequence"], 15)

    def test_duplicate_or_reordered_sequence_does_not_move_high_watermark(self):
        tracker = SequenceTrackerV0()
        for value in (20, 21, 21, 19, 22):
            tracker.observe(value)
        row = tracker.to_dict()
        self.assertEqual(row["message_count"], 5)
        self.assertEqual(row["duplicate_or_reordered_count"], 2)
        self.assertEqual(row["last_sequence"], 22)
        self.assertEqual(row["next_requested_sequence"], 23)
        self.assertEqual(row["missing_sequence_count"], 0)

    def test_empty_tracker_has_no_reconnect_cursor(self):
        tracker = SequenceTrackerV0()
        self.assertIsNone(tracker.next_requested_sequence)
        self.assertIsNone(tracker.to_dict()["first_sequence"])

    def test_negative_sequence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            SequenceTrackerV0().observe(-1)


if __name__ == "__main__":
    unittest.main()
