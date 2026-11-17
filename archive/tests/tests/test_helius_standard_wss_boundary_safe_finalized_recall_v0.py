import unittest

from benchmarks.helius_standard_wss_shadow_v0.boundary_safe_finalized_recall import (
    analyze_boundary_safe_recall,
)


class HeliusStandardWssBoundarySafeFinalizedRecallV0Tests(unittest.TestCase):
    def test_boundary_only_misses_are_removed(self):
        shadow = [
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 10, "signature": "P10_SEEN"},
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 11, "signature": "P11"},
            {"type": "logs_notification", "subscription_label": "pumpswap_logs", "slot": 11, "signature": "S11"},
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 12, "signature": "P12_SEEN"},
        ]
        truth = [
            {"slot": 10, "signature": "P10_SEEN", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 10, "signature": "P10_MISSED", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 11, "signature": "P11", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 11, "signature": "S11", "programs_mentioned": ["pumpswap"], "transaction_succeeded": True},
            {"slot": 12, "signature": "P12_SEEN", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 12, "signature": "P12_MISSED", "programs_mentioned": ["pump"], "transaction_succeeded": True},
        ]
        full_report = {
            "complete_truth_enumeration": True,
            "min_slot": 10,
            "max_slot": 12,
            "per_program": {
                "pump": {"finalized_truth_missed_by_wss": 2},
                "pumpswap": {"finalized_truth_missed_by_wss": 0},
            },
        }
        report = analyze_boundary_safe_recall(
            shadow_rows=shadow, truth_rows=truth, full_report=full_report
        )
        self.assertTrue(report["valid_boundary_safe_audit"])
        self.assertEqual(
            report["classification"],
            "PASS_BOUNDARY_SAFE_FINALIZED_SIGNATURE_RECALL_REFERENCE",
        )
        self.assertEqual(report["excluded_boundary_slots"], [10, 12])
        self.assertEqual(report["per_program"]["pump"]["finalized_signature_recall_pct"], 100.0)
        self.assertEqual(report["boundary_effect"]["pump"]["misses_removed_by_boundary_trim"], 2)
        self.assertEqual(report["interior_slots_with_misses"], 0)

    def test_interior_miss_is_preserved_and_localized(self):
        shadow = [
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 10, "signature": "EDGE"},
            {"type": "logs_notification", "subscription_label": "pump_logs", "slot": 11, "signature": "A"},
            {"type": "logs_notification", "subscription_label": "pumpswap_logs", "slot": 12, "signature": "EDGE2"},
        ]
        truth = [
            {"slot": 10, "signature": "EDGE", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 11, "signature": "A", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 11, "signature": "B", "programs_mentioned": ["pump"], "transaction_succeeded": True},
            {"slot": 12, "signature": "EDGE2", "programs_mentioned": ["pumpswap"], "transaction_succeeded": True},
        ]
        full_report = {
            "complete_truth_enumeration": True,
            "min_slot": 10,
            "max_slot": 12,
            "per_program": {
                "pump": {"finalized_truth_missed_by_wss": 1},
                "pumpswap": {"finalized_truth_missed_by_wss": 0},
            },
        }
        report = analyze_boundary_safe_recall(
            shadow_rows=shadow, truth_rows=truth, full_report=full_report
        )
        self.assertEqual(
            report["classification"],
            "MEASURED_BOUNDARY_SAFE_WSS_FINALIZED_SIGNATURE_GAPS",
        )
        self.assertEqual(report["per_program"]["pump"]["finalized_truth_missed_by_wss"], 1)
        self.assertEqual(report["per_program"]["pump"]["finalized_signature_recall_pct"], 50.0)
        self.assertEqual(report["interior_slots_with_misses"], 1)
        self.assertEqual(report["slots_with_misses"][0]["slot"], 11)
        self.assertEqual(report["slots_with_misses"][0]["per_program"]["pump"]["missed"], 1)

    def test_incomplete_reference_is_withheld(self):
        report = analyze_boundary_safe_recall(
            shadow_rows=[],
            truth_rows=[],
            full_report={
                "complete_truth_enumeration": False,
                "min_slot": 10,
                "max_slot": 12,
            },
        )
        self.assertFalse(report["valid_boundary_safe_audit"])
        self.assertEqual(report["classification"], "INCOMPLETE_BOUNDARY_SAFE_REFERENCE")


if __name__ == "__main__":
    unittest.main()
