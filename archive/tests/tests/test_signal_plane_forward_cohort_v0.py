from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import src.signal_plane_forward_cohort_v0 as cohort


class SignalPlaneForwardCohortV0Tests(unittest.TestCase):
    def test_fresh_v68_requires_valid_promotion_before_bridge(self):
        with patch.object(
            cohort.bridge,
            "run_bridge",
            new=AsyncMock(
                side_effect=AssertionError("bridge must not run without promotion")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "requires a promotion report"):
                cohort.run_signal_plane_forward_cohort_v0(
                    run_key="v68-flow60-fresh-20260922-03-A",
                    bootstrap_report=Path("bootstrap.json"),
                    acquisition_duration_seconds=1,
                )

    def test_fresh_v68_valid_promotion_authorizes_bridge_component(self):
        bridge_mock = AsyncMock(
            return_value={
                "classification": "FAIL_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0"
            }
        )
        with patch.object(
            cohort.promotion,
            "validate_promotion_report",
            return_value=(True, "ok"),
        ), patch.object(
            cohort.bridge,
            "run_bridge",
            new=bridge_mock,
        ):
            result = cohort.run_signal_plane_forward_cohort_v0(
                run_key="v68-flow60-fresh-20260922-03-A",
                bootstrap_report=Path("bootstrap.json"),
                promotion_report=Path("promotion.json"),
                acquisition_duration_seconds=1,
            )

        self.assertFalse(result.passed)
        self.assertTrue(
            bridge_mock.await_args.kwargs["allow_v68_fresh_run_key"]
        )

    def test_bridge_failure_stops_before_forward_collection(self):
        with patch.object(
            cohort.bridge,
            "run_bridge",
            new=AsyncMock(
                return_value={
                    "classification": "FAIL_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0"
                }
            ),
        ), patch.object(
            cohort.forward_collection,
            "collect_route_research_forward_v43",
            side_effect=AssertionError("forward collector must not run"),
        ):
            result = cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.decision_count, 0)
        self.assertEqual(
            result.forward_classification,
            "NOT_STARTED_BRIDGE_FAIL",
        )

    def test_minimum_and_exact_schedule_gate_forward_collection(self):
        with patch.object(
            cohort.bridge,
            "run_bridge",
            new=AsyncMock(
                return_value={
                    "classification": cohort.bridge.PASS_CLASSIFICATION
                }
            ),
        ), patch.object(
            cohort,
            "_cohort_schedule_audit",
            return_value=(29, 87, True),
        ), patch.object(
            cohort.forward_collection,
            "collect_route_research_forward_v43",
            side_effect=AssertionError("undersized cohort must not collect"),
        ):
            result = cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.decision_count, 29)
        self.assertEqual(
            result.forward_classification,
            "INCONCLUSIVE_SIGNAL_PLANE_COHORT_LT_MINIMUM",
        )

    def test_complete_signal_plane_forward_cohort_passes(self):
        collection = SimpleNamespace(
            classification="PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE",
            target_lateness_p95_seconds=1,
        )
        original_probe = cohort.forward_collection.JupiterResearchExitRouteProbe

        with patch.object(
            cohort.bridge,
            "run_bridge",
            new=AsyncMock(
                return_value={
                    "classification": cohort.bridge.PASS_CLASSIFICATION
                }
            ),
        ), patch.object(
            cohort,
            "_cohort_schedule_audit",
            return_value=(40, 120, True),
        ), patch.object(
            cohort,
            "_descriptive_readiness",
            return_value=(0, 3),
        ), patch.object(
            cohort.forward_collection,
            "collect_route_research_forward_v43",
            return_value=collection,
        ) as collect:
            result = cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.decision_count, 40)
        self.assertEqual(result.scheduled_count, 120)
        self.assertEqual(result.target_lateness_p95_seconds, 1)
        self.assertEqual(
            cohort.forward_collection.JupiterResearchExitRouteProbe,
            original_probe,
        )
        collect.assert_called_once()

    def test_frozen_v68_route_parameters_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "max_episodes=40"):
            cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
                max_episodes=41,
            )
        with self.assertRaisesRegex(ValueError, "research_notional_usd=25"):
            cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
                research_notional_usd=26.0,
            )
        with self.assertRaisesRegex(ValueError, "research_slippage_bps=100"):
            cohort.run_signal_plane_forward_cohort_v0(
                run_key="systems-cohort-A",
                bootstrap_report=Path("bootstrap.json"),
                acquisition_duration_seconds=1,
                research_slippage_bps=101,
            )


if __name__ == "__main__":
    unittest.main()
