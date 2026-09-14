import unittest

from src.robinhood_nitro_bootstrap_v0 import (
    BACKLOG_CONFIRMED,
    LIVE_CANDIDATE,
    UNKNOWN_BLOCK_UNRESOLVED,
    UNKNOWN_NO_BLOCK_HASH,
    anchor_is_still_canonical_v0,
    classify_feed_message_against_anchor_v0,
    make_rpc_head_anchor_v0,
)
from src.robinhood_nitro_feed_v0 import NitroFeedMessageV0


def _message(*, block_hash="0x" + "22" * 32, observed_at_ns=2_000):
    return NitroFeedMessageV0(
        sequence_number=123,
        block_hash=block_hash,
        l1_kind=3,
        sender="0x" + "11" * 20,
        l1_block_number=10,
        l1_timestamp=20,
        request_id=None,
        l1_base_fee_raw=0,
        delayed_messages_read=0,
        l2_message_raw=b"",
        signature_raw=b"",
        block_metadata_raw=b"",
        observed_at_ns=observed_at_ns,
    )


class RobinhoodNitroBootstrapV0Tests(unittest.TestCase):
    def setUp(self):
        self.anchor = make_rpc_head_anchor_v0(
            {
                "number": "0x64",
                "hash": "0x" + "aa" * 32,
                "timestamp": "0x3e8",
            },
            captured_at_ns=1_000,
        )

    def test_block_at_or_before_preconnect_head_is_confirmed_backlog(self):
        row = classify_feed_message_against_anchor_v0(
            _message(),
            anchor=self.anchor,
            resolved_block_row={
                "number": "0x64",
                "hash": "0x" + "22" * 32,
            },
        )
        self.assertEqual(row.classification, BACKLOG_CONFIRMED)
        self.assertFalse(row.eligible_for_feed_latency)
        self.assertEqual(row.resolved_block_number, 100)

    def test_block_after_preconnect_head_is_live_candidate(self):
        row = classify_feed_message_against_anchor_v0(
            _message(),
            anchor=self.anchor,
            resolved_block_row={
                "number": "0x65",
                "hash": "0x" + "22" * 32,
            },
        )
        self.assertEqual(row.classification, LIVE_CANDIDATE)
        self.assertTrue(row.eligible_for_feed_latency)
        self.assertEqual(row.resolved_block_number, 101)

    def test_unresolved_or_missing_hash_never_becomes_latency_eligible(self):
        unresolved = classify_feed_message_against_anchor_v0(
            _message(), anchor=self.anchor, resolved_block_row=None
        )
        self.assertEqual(unresolved.classification, UNKNOWN_BLOCK_UNRESOLVED)
        self.assertFalse(unresolved.eligible_for_feed_latency)

        no_hash = classify_feed_message_against_anchor_v0(
            _message(block_hash=None), anchor=self.anchor, resolved_block_row=None
        )
        self.assertEqual(no_hash.classification, UNKNOWN_NO_BLOCK_HASH)
        self.assertFalse(no_hash.eligible_for_feed_latency)

    def test_resolution_hash_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            classify_feed_message_against_anchor_v0(
                _message(),
                anchor=self.anchor,
                resolved_block_row={
                    "number": "0x65",
                    "hash": "0x" + "33" * 32,
                },
            )

    def test_feed_observation_must_follow_anchor(self):
        with self.assertRaisesRegex(ValueError, "predates"):
            classify_feed_message_against_anchor_v0(
                _message(observed_at_ns=999),
                anchor=self.anchor,
                resolved_block_row=None,
            )

    def test_anchor_reorg_guard(self):
        self.assertTrue(
            anchor_is_still_canonical_v0(
                self.anchor,
                {"number": "0x64", "hash": "0x" + "aa" * 32},
            )
        )
        self.assertFalse(
            anchor_is_still_canonical_v0(
                self.anchor,
                {"number": "0x64", "hash": "0x" + "bb" * 32},
            )
        )


if __name__ == "__main__":
    unittest.main()
