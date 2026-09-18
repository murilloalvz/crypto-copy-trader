from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.buy_event_acceleration_replication_v0.decompose import run_decomposition


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class BuyEventAccelerationDecompositionV0Tests(unittest.TestCase):
    def test_decomposition_separates_exit_failure_from_route_closed_performance(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            _write(
                run / "buy-event-acceleration-replication-v0.json",
                {
                    "classification": "PASS_BUY_EVENT_ACCELERATION_REPLICATION_V0",
                    "decision": "ITERATE",
                    "population": {
                        "fresh_median_feature_value": -0.8,
                        "fresh_feature_route_usable_default_sol_n": 4,
                    },
                },
            )
            rows = [
                {"episode_key": "l1", "baseline_admitted": True, "is_default_sol_quote": True, "route_status": "ROUTE_CLOSED", "fixed_return_pct": 10.0, "features": {"mf_buy_event_rate_acceleration_per_s2": -1.2}},
                {"episode_key": "l2", "baseline_admitted": True, "is_default_sol_quote": True, "route_status": "ROUTE_CLOSED", "fixed_return_pct": -5.0, "features": {"mf_buy_event_rate_acceleration_per_s2": -0.8}},
                {"episode_key": "u1", "baseline_admitted": True, "is_default_sol_quote": True, "route_status": "ROUTE_CLOSED", "fixed_return_pct": 8.0, "features": {"mf_buy_event_rate_acceleration_per_s2": -0.4}},
                {"episode_key": "u2", "baseline_admitted": True, "is_default_sol_quote": True, "route_status": "UNROUTABLE_EXIT", "fixed_return_pct": -100.0, "features": {"mf_buy_event_rate_acceleration_per_s2": 0.2}},
            ]
            _write(
                run / "market-first-feature-discovery-v1.json",
                {"classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1", "rows": rows},
            )
            _write(
                run / "route-result-v2.json",
                {
                    "decisions": [
                        {"episode_key": "l1", "status": "ROUTE_CLOSED", "gross_route_return_pct": 12.0},
                        {"episode_key": "l2", "status": "ROUTE_CLOSED", "gross_route_return_pct": -3.0},
                        {"episode_key": "u1", "status": "ROUTE_CLOSED", "gross_route_return_pct": 10.0},
                        {"episode_key": "u2", "status": "UNROUTABLE_EXIT"},
                    ]
                },
            )

            report = run_decomposition(run_dir=run)

        self.assertEqual(report["classification"], "PASS_BUY_EVENT_ACCELERATION_DECOMPOSITION_V0")
        self.assertEqual(report["replication_decision_unchanged"], "ITERATE")
        self.assertEqual(report["population_parity_n"], 4)
        self.assertEqual(report["lower_half_more_negative_acceleration"]["exit_failure_count"], 0)
        self.assertEqual(report["upper_half_less_negative_or_positive_acceleration"]["exit_failure_count"], 1)
        self.assertGreater(
            report["decomposition"]["upper_minus_lower_exit_failure_rate_pct_points"],
            0,
        )
        self.assertFalse(report["threshold_search_performed"])
        self.assertFalse(report["selector_changed"])

    def test_population_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            _write(
                run / "buy-event-acceleration-replication-v0.json",
                {
                    "classification": "PASS_BUY_EVENT_ACCELERATION_REPLICATION_V0",
                    "decision": "ITERATE",
                    "population": {
                        "fresh_median_feature_value": -0.8,
                        "fresh_feature_route_usable_default_sol_n": 2,
                    },
                },
            )
            _write(
                run / "market-first-feature-discovery-v1.json",
                {"classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1", "rows": []},
            )
            _write(run / "route-result-v2.json", {"decisions": []})
            with self.assertRaisesRegex(ValueError, "population parity mismatch"):
                run_decomposition(run_dir=run)


if __name__ == "__main__":
    unittest.main()
