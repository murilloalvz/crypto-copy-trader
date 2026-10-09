from __future__ import annotations

import unittest

from benchmarks.carbon_runtime_replay_v1.suite import classify


def _report(
    *,
    events: int = 1000,
    pipeline_p95: float = 0.2,
    bystander_p50: float = 0.0,
    handoff_enqueued: int = 0,
    handoff_dropped: int = 0,
    worker_completed: int = 0,
    pipeline_order_violations: int = 0,
    worker_order_violations: int = 0,
) -> dict:
    return {
        "counts": {
            "source_sent": events,
            "pipeline_processed": events,
            "handoff_enqueued": handoff_enqueued,
            "handoff_dropped": handoff_dropped,
            "worker_completed": worker_completed,
        },
        "correctness": {
            "pipeline_order_violations": pipeline_order_violations,
            "worker_order_violations": worker_order_violations,
            "pipeline_current_at_end": 0,
            "downstream_current_at_end": 0,
        },
        "pressure": {
            "pipeline_outstanding_high_water": 10,
            "downstream_outstanding_high_water": 20,
        },
        "timing": {
            "pipeline_e2e": {"p95_ms": pipeline_p95},
            "bystander_after_slow": {"p50_ms": bystander_p50},
        },
    }


class CarbonRuntimeReplayV1SuiteTests(unittest.TestCase):
    def test_classifies_adapt_when_inline_hol_and_handoff_isolated(self) -> None:
        events = 1000
        reports = {
            "inline_fast": _report(events=events, pipeline_p95=0.2),
            "inline_slow": _report(events=events, pipeline_p95=3.0, bystander_p50=4.0),
            "handoff_slow": _report(
                events=events,
                pipeline_p95=0.3,
                handoff_enqueued=events,
                worker_completed=events,
            ),
            "handoff_burst": _report(
                events=events,
                pipeline_p95=0.4,
                handoff_enqueued=600,
                handoff_dropped=400,
                worker_completed=600,
            ),
        }
        verdict = classify(reports, events)
        self.assertEqual(verdict["classification"], "ADAPT_CARBON_RUNTIME_BOUNDARY")
        self.assertTrue(verdict["checks"]["inline_hol_reproduced"])
        self.assertTrue(verdict["checks"]["representative_zero_drop"])
        self.assertTrue(verdict["checks"]["representative_isolated"])

    def test_inconclusive_when_inline_hol_not_reproduced(self) -> None:
        events = 1000
        reports = {
            "inline_fast": _report(events=events, pipeline_p95=0.2),
            "inline_slow": _report(events=events, pipeline_p95=0.5, bystander_p50=0.6),
            "handoff_slow": _report(
                events=events,
                pipeline_p95=0.3,
                handoff_enqueued=events,
                worker_completed=events,
            ),
            "handoff_burst": _report(
                events=events,
                pipeline_p95=0.4,
                handoff_enqueued=600,
                handoff_dropped=400,
                worker_completed=600,
            ),
        }
        verdict = classify(reports, events)
        self.assertEqual(
            verdict["classification"],
            "INCONCLUSIVE_CARBON_INLINE_HOL_NOT_REPRODUCED",
        )

    def test_rejects_accounting_or_order_failure(self) -> None:
        events = 1000
        reports = {
            "inline_fast": _report(events=events, pipeline_p95=0.2),
            "inline_slow": _report(events=events, pipeline_p95=3.0, bystander_p50=4.0),
            "handoff_slow": _report(
                events=events,
                pipeline_p95=0.3,
                handoff_enqueued=999,
                handoff_dropped=0,
                worker_completed=999,
                pipeline_order_violations=1,
            ),
            "handoff_burst": _report(
                events=events,
                pipeline_p95=0.4,
                handoff_enqueued=600,
                handoff_dropped=400,
                worker_completed=600,
            ),
        }
        verdict = classify(reports, events)
        self.assertEqual(verdict["classification"], "REJECT_OR_INVESTIGATE_CARBON_RUNTIME_V1")


if __name__ == "__main__":
    unittest.main()
