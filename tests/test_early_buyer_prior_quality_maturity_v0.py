from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.early_buyer_prior_quality_v0.maturity import run_maturity_diagnostic
from benchmarks.early_buyer_prior_quality_v0.run import FEATURE_ID


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class EarlyBuyerPriorQualityMaturityV0Tests(unittest.TestCase):
    def test_maturity_diagnostic_preserves_iterate_and_reports_temporal_structure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for run_index, run_id in enumerate(("r1", "r2", "r3", "r4")):
                for index in range(10):
                    feature = float(index)
                    outcome = (
                        float(10 - index)
                        if run_index < 2
                        else float(index)
                    )
                    rows.append(
                        {
                            "run_id": run_id,
                            "episode_key": f"{run_id}-{index}",
                            "observed_t0": 1000 * (run_index + 1) + index,
                            FEATURE_ID: feature,
                            "history_coverage_pct": 20.0 + 20.0 * run_index,
                            "prior_association_count": 1 + run_index,
                            "prior_unique_episode_count": 1 + run_index,
                            "wallets_with_history": 1,
                            "current_route_closed_gross_return_pct": outcome,
                        }
                    )
            artifact = root / "early-buyer-prior-quality-v0.json"
            _write(
                artifact,
                {
                    "classification": "PASS_EARLY_BUYER_PRIOR_QUALITY_V0",
                    "decision": "ITERATE",
                    "rows": rows,
                },
            )

            report = run_maturity_diagnostic(discovery_artifact=artifact)

        self.assertEqual(
            report["classification"],
            "PASS_EARLY_BUYER_PRIOR_QUALITY_MATURITY_V0",
        )
        self.assertEqual(report["discovery_decision_unchanged"], "ITERATE")
        self.assertEqual(report["run_order"], ["r1", "r2", "r3", "r4"])
        self.assertFalse(report["guardrails"]["threshold_search_performed"])
        self.assertFalse(report["guardrails"]["support_threshold_promoted"])
        self.assertIn("r4", report["leave_one_run_out_pooled_primary"])
        self.assertEqual(
            report["chronological_halves"]["earlier_half"]["run_ids"],
            ["r1", "r2"],
        )
        self.assertEqual(
            report["chronological_halves"]["later_half"]["run_ids"],
            ["r3", "r4"],
        )

    def test_non_iterate_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "artifact.json"
            _write(
                artifact,
                {
                    "classification": "PASS_EARLY_BUYER_PRIOR_QUALITY_V0",
                    "decision": "KEEP",
                    "rows": [{"run_id": "r1"}],
                },
            )
            with self.assertRaisesRegex(ValueError, "defined only for ITERATE"):
                run_maturity_diagnostic(discovery_artifact=artifact)


if __name__ == "__main__":
    unittest.main()
