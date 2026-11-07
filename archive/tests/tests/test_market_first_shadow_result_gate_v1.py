from __future__ import annotations

import unittest

from benchmarks.market_first_capacity_harness_v0.shadow_result_gate import (
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    classify_shadow_result_v1,
)


def _base_result() -> dict:
    pipeline = {
        "canonical_events_paired": 10,
        "decoded_events": 9,
        "decode_failures_seen_in_processing": 0,
        "out_of_window_events": 1,
        "lifecycle_events_ingested": 1,
        "market_trade_adapted_events": 5,
        "market_trade_statuses": {"ADAPTED": 5},
        "matched_unit_statuses": {"ADAPTED": 5},
        "kernel_trade_events_ingested": 5,
        "kernel_retained_trade_rows": 5,
        "kernel_tracked_assets": 2,
        "kernel_triggers_emitted": 2,
        "unresolved_pool_event_count": 3,
        "unresolved_unique_pool_count": 2,
        "semantic_errors": [],
        "persistence_errors": [],
        "chunk_errors": [],
        "research_errors": [],
    }
    return {
        "classification": "FAIL_MARKET_FIRST_SHADOW_SIGNAL_PLANE_V0",
        "trigger_parity": {
            "exact_match": True,
            "baseline_count": 2,
            "shadow_count": 2,
            "first_mismatch_index": None,
        },
        "unresolved_pool_set_exact_match": True,
        "signal_path": {"single_chunk_reference_le_5s": True},
        "baseline": {"pipeline": dict(pipeline)},
        "shadow": {"pipeline": dict(pipeline)},
    }


class MarketFirstShadowResultGateV1Tests(unittest.TestCase):
    def test_post_signal_research_error_is_visible_but_non_gating(self) -> None:
        result = _base_result()
        result["baseline"]["pipeline"]["research_errors"] = ["missing discovery run"]
        gated = classify_shadow_result_v1(result)
        self.assertEqual(gated["classification"], PASS_CLASSIFICATION)
        self.assertEqual(
            gated["non_gating_post_signal_research_errors"]["baseline"],
            ["missing discovery run"],
        )

    def test_persistence_error_remains_gating(self) -> None:
        result = _base_result()
        result["baseline"]["pipeline"]["persistence_errors"] = ["write failed"]
        gated = classify_shadow_result_v1(result)
        self.assertEqual(gated["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(gated["gates"]["baseline_signal_errors_empty"])

    def test_counter_mismatch_fails(self) -> None:
        result = _base_result()
        result["shadow"]["pipeline"]["kernel_trade_events_ingested"] = 4
        gated = classify_shadow_result_v1(result)
        self.assertEqual(gated["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(gated["gates"]["signal_pipeline_counters_exact_match"])

    def test_trigger_mismatch_fails(self) -> None:
        result = _base_result()
        result["trigger_parity"]["exact_match"] = False
        gated = classify_shadow_result_v1(result)
        self.assertEqual(gated["classification"], FAIL_CLASSIFICATION)

    def test_reference_latency_gate_fails_closed(self) -> None:
        result = _base_result()
        result["signal_path"]["single_chunk_reference_le_5s"] = False
        gated = classify_shadow_result_v1(result)
        self.assertEqual(gated["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(gated["gates"]["single_chunk_reference_le_5s"])


if __name__ == "__main__":
    unittest.main()
