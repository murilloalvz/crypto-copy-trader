import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.launch_burst_readiness_v0.run import (
    find_live_report_for_run,
    run_launch_burst_readiness_v0,
)


class LaunchBurstReadinessV0Tests(unittest.TestCase):
    def _report(self, path: Path, *, run_key: str, status: str, valid: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "run": {
                        "acquisition_run_key": run_key,
                        "status": status,
                    },
                    "valid_live_discovery": valid,
                }
            ),
            encoding="utf-8",
        )

    def _parity(self, *, exact: bool = True, same_second: int = 0) -> dict:
        return {
            "exact_match": exact,
            "diagnostics": {"same_second_multi_candidate_count": same_second},
            "scientific_lock": {
                "economic_outcomes_loaded": False,
                "return_values_reported": False,
            },
        }

    def test_find_live_report_ignores_open_and_invalid_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._report(
                root / "open" / "report.json",
                run_key="run",
                status="OPEN",
                valid=True,
            )
            self._report(
                root / "invalid" / "report.json",
                run_key="run",
                status="CLOSED",
                valid=False,
            )
            expected = root / "valid" / "report.json"
            self._report(expected, run_key="run", status="CLOSED", valid=True)
            found = find_live_report_for_run(
                acquisition_run_key="run",
                artifacts_root=root,
            )
        self.assertEqual(found, expected)

    def test_multiple_valid_reports_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._report(
                root / "a" / "report.json",
                run_key="run",
                status="CLOSED",
                valid=True,
            )
            self._report(
                root / "b" / "report.json",
                run_key="run",
                status="CLOSED",
                valid=True,
            )
            with self.assertRaises(RuntimeError):
                find_live_report_for_run(
                    acquisition_run_key="run",
                    artifacts_root=root,
                )

    def test_feature_research_can_be_ready_while_economic_outcomes_stay_blocked(self):
        db_coverage = {
            "sample": {
                "complete_snapshot_count": 5,
                "nonempty_snapshot_count": 4,
            },
            "scientific_lock": {
                "future_outcomes_loaded": False,
                "return_values_reported": False,
            },
        }
        matched_coverage = {
            "launch_sample": {"complete_anchor_count": 5},
            "trade_adaptation": {"adapted_count": 20},
            "scientific_lock": {
                "economic_outcomes_loaded": False,
                "return_values_reported": False,
            },
        }
        capabilities = SimpleNamespace(
            as_dict=lambda: {
                "feature_only_ready": True,
                "economic_outcome_ready": False,
                "blockers": ["official_executable_launch_burst_outcome_collector_not_proven"],
            }
        )
        with patch(
            "benchmarks.launch_burst_readiness_v0.run.select_latest_closed_launch_run_key",
            return_value="closed-run",
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.find_live_report_for_run",
            return_value=Path("report.json"),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_candidate_parity_v0",
            return_value=self._parity(),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_coverage_audit",
            return_value=db_coverage,
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_matched_unit_coverage_audit",
            return_value=matched_coverage,
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.build_launch_burst_source_capabilities_v0",
            return_value=capabilities,
        ):
            result = run_launch_burst_readiness_v0()

        self.assertEqual(
            result["classification"],
            "FEATURE_RESEARCH_READY_ECONOMIC_OUTCOME_BLOCKED",
        )
        self.assertTrue(result["readiness"]["candidate_ledger_parity_ready"])
        self.assertTrue(result["readiness"]["feature_research_ready"])
        self.assertTrue(result["readiness"]["matched_unit_research_ready"])
        self.assertFalse(result["readiness"]["economic_outcome_ready"])
        self.assertFalse(result["readiness"]["automatic_trade_ready"])
        self.assertFalse(result["scientific_lock"]["economic_outcomes_loaded"])
        self.assertFalse(result["scientific_lock"]["return_values_reported"])
        self.assertFalse(result["scientific_lock"]["candidate_thresholds_defined"])

    def test_candidate_parity_failure_blocks_all_downstream_readiness(self):
        capabilities = SimpleNamespace(
            as_dict=lambda: {
                "feature_only_ready": True,
                "economic_outcome_ready": True,
                "blockers": [],
            }
        )
        with patch(
            "benchmarks.launch_burst_readiness_v0.run.select_latest_closed_launch_run_key",
            return_value="closed-run",
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.find_live_report_for_run",
            return_value=Path("report.json"),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_candidate_parity_v0",
            return_value=self._parity(exact=False, same_second=1),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_coverage_audit",
            return_value={
                "sample": {"complete_snapshot_count": 5, "nonempty_snapshot_count": 5}
            },
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_matched_unit_coverage_audit",
            return_value={
                "launch_sample": {"complete_anchor_count": 5},
                "trade_adaptation": {"adapted_count": 10},
            },
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.build_launch_burst_source_capabilities_v0",
            return_value=capabilities,
        ):
            result = run_launch_burst_readiness_v0()

        self.assertEqual(result["classification"], "CANDIDATE_LEDGER_PARITY_FAILED")
        self.assertFalse(result["readiness"]["candidate_ledger_parity_ready"])
        self.assertFalse(result["readiness"]["feature_research_ready"])
        self.assertFalse(result["readiness"]["matched_unit_research_ready"])
        self.assertFalse(result["readiness"]["economic_outcome_ready"])
        self.assertIn("candidate_anchor_ledger_parity_failed", result["blockers"])
        self.assertIn(
            "same_second_lifecycle_candidates_require_exact_receive_order_audit",
            result["blockers"],
        )

    def test_no_complete_launch_sample_blocks_feature_readiness(self):
        capabilities = SimpleNamespace(
            as_dict=lambda: {
                "feature_only_ready": True,
                "economic_outcome_ready": False,
                "blockers": [],
            }
        )
        with patch(
            "benchmarks.launch_burst_readiness_v0.run.select_latest_closed_launch_run_key",
            return_value="closed-run",
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.find_live_report_for_run",
            return_value=Path("report.json"),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_candidate_parity_v0",
            return_value=self._parity(),
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_coverage_audit",
            return_value={
                "sample": {
                    "complete_snapshot_count": 0,
                    "nonempty_snapshot_count": 0,
                }
            },
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.run_matched_unit_coverage_audit",
            return_value={
                "launch_sample": {"complete_anchor_count": 0},
                "trade_adaptation": {"adapted_count": 0},
            },
        ), patch(
            "benchmarks.launch_burst_readiness_v0.run.build_launch_burst_source_capabilities_v0",
            return_value=capabilities,
        ):
            result = run_launch_burst_readiness_v0()

        self.assertEqual(result["classification"], "NEEDS_MORE_OR_BETTER_LAUNCH_SAMPLE")
        self.assertFalse(result["readiness"]["feature_research_ready"])
        self.assertIn(
            "no_complete_launch_burst_snapshot_in_selected_closed_run",
            result["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
