import unittest
from unittest.mock import patch

import route_research_forward_cohort_v43 as v43
from src.route_research_forward_collection_v43 import collect_route_research_forward_v43


PASS_OUTPUT = """
SUMMARY
elapsed=120.0s received={'pump': 100, 'pumpswap': 900} enqueued={'pump': 100, 'pumpswap': 900} dropped={}
persistence_completed={'pump': 100, 'pumpswap': 900} radar_processed={'pump': 100, 'pumpswap': 900} radar_coverage_pct=100.0% worker_errors={}
raw_radar_hits={'pump': 10, 'pumpswap': 20} unique_episodes=5 reference_asset_episodes=0
bundle_wallets_total=50 bundle_flow30_total=60 risk_missing=5
pump_radar_end_to_end_wait_ms p50=100.0 p95=1800.0 max=2000.0
pumpswap_pipeline_end_to_end_ms p50=200.0 p95=3300.0 max=4400.0
pumpswap_historical_pool_hits=10 network_hydrations=5 hydration_successes=5 rpc_failures=0 budget_skips=0
reservation_superset_violations=0
continuation_writer_fatal_error=False
V37 RETAINED
budget_skips=0
reservation_superset_violations=0
"""


class SystemsGateV43Tests(unittest.TestCase):
    def test_full_pass_is_11_of_11(self):
        result = v43.audit_systems_gate_v43(PASS_OUTPUT)
        self.assertTrue(result.passed)
        self.assertEqual(result.passed_count, 11)
        self.assertEqual(result.true_backlog_pct, 0.0)
        self.assertEqual(result.pumpswap_p95_ms, 3300.0)

    def test_pumpswap_tail_over_gate_fails(self):
        result = v43.audit_systems_gate_v43(
            PASS_OUTPUT.replace("p95=3300.0 max=4400.0", "p95=5100.0 max=6000.0")
        )
        self.assertFalse(result.passed)
        self.assertIn(("pumpswap_p95_le_5s", False), result.checks)

    def test_missing_replay_evidence_cannot_silently_pass(self):
        result = v43.audit_systems_gate_v43(
            PASS_OUTPUT.replace("continuation_writer_fatal_error=False\n", "")
        )
        self.assertFalse(result.passed)
        self.assertIn(("replay_auditable", False), result.checks)

    def test_true_backlog_uses_received_minus_processed_not_overlapping_counters(self):
        output = PASS_OUTPUT.replace(
            "radar_processed={'pump': 100, 'pumpswap': 900}",
            "radar_processed={'pump': 90, 'pumpswap': 850}",
        ).replace("radar_coverage_pct=100.0%", "radar_coverage_pct=94.0%")
        result = v43.audit_systems_gate_v43(output)
        self.assertAlmostEqual(result.true_backlog_pct, 6.0)
        self.assertFalse(result.passed)


class ForwardCollectionV43Tests(unittest.TestCase):
    def test_no_schedule_is_explicit_inconclusive(self):
        with patch(
            "src.route_research_forward_collection_v43.load_route_research_outcomes",
            return_value=(),
        ):
            result = collect_route_research_forward_v43(
                acquisition_run_key="run",
                api_key=None,
            )
        self.assertEqual(result.scheduled, 0)
        self.assertEqual(
            result.classification,
            "INCONCLUSIVE_NO_ROUTE_RESEARCH_SCHEDULE",
        )


if __name__ == "__main__":
    unittest.main()
