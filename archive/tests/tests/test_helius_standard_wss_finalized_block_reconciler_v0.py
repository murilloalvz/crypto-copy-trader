import unittest

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
)
from benchmarks.helius_standard_wss_shadow_v0.reconcile_finalized_blocks import (
    derive_shadow_slot_window,
    extract_block_candidates,
    reconcile_signature_sets,
    wss_signature_sets,
)


class HeliusStandardWssFinalizedBlockReconcilerV0Tests(unittest.TestCase):
    def test_shadow_window_and_program_sets_use_exact_log_slots(self):
        rows = [
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 10, "signature": "A"},
            {"type": "logs_notification", "subscription_label": "pumpswap_logs", "slot": 12, "signature": "B"},
            {"type": "slot_notification", "subscription_label": "slot", "slot": 99},
        ]
        window = derive_shadow_slot_window(rows)
        self.assertEqual(window["min_slot"], 10)
        self.assertEqual(window["max_slot"], 12)
        sets = wss_signature_sets(rows, min_slot=10, max_slot=12)
        self.assertEqual(sets["pump"], {"A"})
        self.assertEqual(sets["pumpswap"], {"B"})

    def test_accounts_only_block_extracts_program_mentions_and_failure_status(self):
        block = {
            "blockTime": 123,
            "transactions": [
                {
                    "transaction": {
                        "signatures": ["SIG_PUMP"],
                        "accountKeys": [
                            {"pubkey": "payer"},
                            {"pubkey": PUMP_PROGRAM_ID},
                        ],
                    },
                    "meta": {"err": None},
                },
                {
                    "transaction": {
                        "signatures": ["SIG_BOTH"],
                        "accountKeys": [
                            {"pubkey": PUMP_PROGRAM_ID},
                            {"pubkey": PUMPSWAP_PROGRAM_ID},
                        ],
                    },
                    "meta": {"err": {"InstructionError": [1, "Custom"]}},
                },
                {
                    "transaction": {
                        "signatures": ["OTHER"],
                        "accountKeys": [{"pubkey": "11111111111111111111111111111111"}],
                    },
                    "meta": {"err": None},
                },
            ],
        }
        rows = extract_block_candidates(slot=77, block=block)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["programs_mentioned"], ["pump"])
        self.assertTrue(rows[0]["transaction_succeeded"])
        self.assertEqual(rows[1]["programs_mentioned"], ["pump", "pumpswap"])
        self.assertFalse(rows[1]["transaction_succeeded"])

    def test_recall_and_comparison_counts_are_withheld_when_reference_is_incomplete(self):
        truth = [
            {
                "signature": "A",
                "programs_mentioned": ["pump"],
                "transaction_succeeded": True,
            }
        ]
        result = reconcile_signature_sets(
            wss_sets={"pump": {"A", "PROCESSED_ONLY"}, "pumpswap": set()},
            truth_rows=truth,
            complete_truth_enumeration=False,
        )
        pump = result["pump"]
        self.assertEqual(pump["wss_processed_signatures"], 2)
        self.assertIsNone(pump["finalized_truth_signatures"])
        self.assertIsNone(pump["finalized_success_truth_signatures"])
        self.assertIsNone(pump["wss_and_finalized_intersection"])
        self.assertIsNone(pump["finalized_truth_missed_by_wss"])
        self.assertIsNone(pump["wss_processed_absent_from_finalized_truth"])
        self.assertIsNone(pump["finalized_success_seen_by_wss"])
        self.assertIsNone(pump["finalized_signature_recall_pct"])
        self.assertIsNone(pump["finalized_success_signature_recall_pct"])
        self.assertEqual(pump["missed_finalized_examples"], [])
        self.assertEqual(pump["processed_absent_finalized_examples"], [])

    def test_reconciliation_surfaces_missed_and_processed_absent_finalized(self):
        truth = [
            {"signature": "A", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"signature": "B", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"signature": "S", "programs_mentioned": ["pumpswap"], "transaction_succeeded": False},
        ]
        result = reconcile_signature_sets(
            wss_sets={"pump": {"A", "PROCESSED_ONLY"}, "pumpswap": {"S"}},
            truth_rows=truth,
            complete_truth_enumeration=True,
        )
        self.assertEqual(result["pump"]["finalized_truth_missed_by_wss"], 1)
        self.assertEqual(result["pump"]["wss_processed_absent_from_finalized_truth"], 1)
        self.assertEqual(result["pump"]["finalized_signature_recall_pct"], 50.0)
        self.assertEqual(result["pumpswap"]["finalized_signature_recall_pct"], 100.0)
        self.assertIsNone(result["pumpswap"]["finalized_success_signature_recall_pct"])


if __name__ == "__main__":
    unittest.main()
