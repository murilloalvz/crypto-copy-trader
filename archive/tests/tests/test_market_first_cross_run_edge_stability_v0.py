from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_cross_run_edge_stability_v0.run import run_cross_run_stability_v0


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact(run_dir: Path, *, stable_rho: float, unstable_rho: float) -> None:
    _write(
        run_dir / "market-first-routeable-edge-discovery-v2.json",
        {
            "classification": "PASS_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2",
            "source_integrity": {
                "run_dir": str(run_dir),
                "route_usable_fixed_row_count": 20,
            },
            "cohorts": {
                "baseline_route_usable_default_sol_quote": {
                    "outcomes": {"trade_count": 18},
                    "features": {
                        "stable": {
                            "usable_pair_count": 18,
                            "spearman_with_fixed_60s_return": stable_rho,
                            "spearman_without_best_return_trade": stable_rho * 0.9,
                            "leave_one_out_sign_consistency_fraction": 1.0,
                            "feature_mean_positive_outcomes": 1.0,
                            "feature_mean_nonpositive_outcomes": 2.0,
                        },
                        "unstable": {
                            "usable_pair_count": 18,
                            "spearman_with_fixed_60s_return": unstable_rho,
                            "spearman_without_best_return_trade": unstable_rho,
                            "leave_one_out_sign_consistency_fraction": 0.8,
                            "feature_mean_positive_outcomes": 3.0,
                            "feature_mean_nonpositive_outcomes": 2.0,
                        },
                    },
                }
            },
        },
    )


class MarketFirstCrossRunEdgeStabilityV0Tests(unittest.TestCase):
    def test_only_cross_run_robust_direction_is_exposed_as_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runs = [root / f"run-{index}" for index in range(3)]
            _artifact(runs[0], stable_rho=-0.3, unstable_rho=0.2)
            _artifact(runs[1], stable_rho=-0.2, unstable_rho=-0.1)
            _artifact(runs[2], stable_rho=-0.4, unstable_rho=0.3)

            report = run_cross_run_stability_v0(run_dirs=runs)

        self.assertEqual(report["classification"], "PASS_MARKET_FIRST_CROSS_RUN_EDGE_STABILITY_V0")
        self.assertEqual(report["stable_direction_feature_ids"], ["stable"])
        stable = report["features"]["stable"]
        self.assertTrue(stable["full_spearman_sign_consistent_across_runs"])
        self.assertTrue(stable["without_best_sign_consistent_across_runs"])
        self.assertEqual(stable["cross_run_direction"], "negative")
        self.assertFalse(report["threshold_search_performed"])
        self.assertFalse(report["selector_changed"])

    def test_duplicate_capture_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "same"
            _artifact(run, stable_rho=-0.3, unstable_rho=0.2)
            with self.assertRaisesRegex(ValueError, "duplicate capture identity"):
                run_cross_run_stability_v0(run_dirs=[run, run])


if __name__ == "__main__":
    unittest.main()
