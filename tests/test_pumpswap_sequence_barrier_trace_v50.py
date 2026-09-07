import unittest
from types import SimpleNamespace

from src.pumpswap_sequence_barrier_trace_v50 import (
    PumpSwapSequenceBarrierTraceV50,
    dominant_clock_v50,
)
import unified_market_route_research_smoke_v50 as v50


def _notification(signature: str):
    return SimpleNamespace(signature=signature)


def _handle(completed: float):
    return SimpleNamespace(normalization_completed_monotonic=completed)


def _reservation(reservation_id: int, created: float, asset: str, ticket: int):
    return SimpleNamespace(
        reservation_id=reservation_id,
        created_monotonic=created,
        assets=(asset,),
        tickets=((asset, ticket),),
    )


class PumpSwapSequenceBarrierTraceV50Tests(unittest.TestCase):
    def test_ingress_retains_notification_identity_under_high_churn(self):
        trace = PumpSwapSequenceBarrierTraceV50()
        for index in range(5000):
            trace.observe_ingress(
                _notification(f"sig{index}"),
                observed_monotonic=float(index),
            )

        snapshot = trace.snapshot()
        self.assertEqual(snapshot.ingress_count, 5000)
        self.assertEqual(len(trace._sequence_by_notification_id), 5000)
        self.assertEqual(len(trace._by_sequence), 5000)
        self.assertTrue(
            all(item.notification_ref is not None for item in trace._by_sequence.values())
        )

    def test_prefix_blocker_attributes_successor_wait_to_late_predecessor(self):
        trace = PumpSwapSequenceBarrierTraceV50()
        n0 = _notification("sig0")
        n1 = _notification("sig1")
        n2 = _notification("sig2")

        trace.observe_ingress(n0, observed_monotonic=0.0)
        trace.observe_ingress(n1, observed_monotonic=0.1)
        trace.observe_ingress(n2, observed_monotonic=0.2)

        trace.observe_normalization(n0, _handle(1.0))
        trace.observe_normalization(n1, _handle(4.0))
        trace.observe_normalization(n2, _handle(2.0))

        r0 = _reservation(0, 1.1, "A", 0)
        r1 = _reservation(1, 4.1, "B", 0)
        r2 = _reservation(2, 4.1, "C", 0)
        trace.observe_reservation(r0)
        trace.observe_reservation(r1)
        trace.observe_reservation(r2)

        trace.observe_submit_or_skip(r0, disposition="skip", observed_monotonic=1.11)
        trace.observe_submit_or_skip(r1, disposition="submit", observed_monotonic=4.11)
        trace.observe_submit_or_skip(r2, disposition="submit", observed_monotonic=4.11)

        snapshot = trace.snapshot()
        self.assertEqual(len(snapshot.rows), 3)
        row2 = snapshot.rows[2]
        self.assertEqual(row2.sequence, 2)
        self.assertEqual(row2.blocker_sequence, 1)
        self.assertAlmostEqual(row2.prefix_normalization_barrier_seconds, 2.0)
        self.assertAlmostEqual(row2.post_prefix_coordinator_seconds, 0.1)
        self.assertAlmostEqual(row2.normalization_to_reservation_seconds, 2.1)

        self.assertEqual(snapshot.blockers[0].blocker_sequence, 1)
        self.assertEqual(snapshot.blockers[0].blocker_signature, "sig1")
        self.assertEqual(snapshot.blockers[0].blocked_successors, 1)
        self.assertAlmostEqual(
            snapshot.blockers[0].total_successor_barrier_seconds,
            2.0,
        )

    def test_dominant_clock_detects_global_barrier_with_tail_support(self):
        trace = PumpSwapSequenceBarrierTraceV50()
        notifications = [_notification(f"sig{index}") for index in range(30)]
        for index, notification in enumerate(notifications):
            trace.observe_ingress(notification, observed_monotonic=index * 0.01)

        trace.observe_normalization(notifications[0], _handle(1.0))
        trace.observe_normalization(notifications[1], _handle(4.0))
        for index in range(2, 30):
            trace.observe_normalization(notifications[index], _handle(2.0 + index * 0.001))

        trace.observe_reservation(_reservation(0, 1.01, "A0", 0))
        trace.observe_reservation(_reservation(1, 4.01, "A1", 0))
        for index in range(2, 30):
            reservation = _reservation(index, 4.01 + index * 0.0001, f"A{index}", 0)
            trace.observe_reservation(reservation)
            trace.observe_submit_or_skip(
                reservation,
                disposition="submit",
                observed_monotonic=4.02 + index * 0.0001,
            )

        snapshot = trace.snapshot()
        self.assertEqual(dominant_clock_v50(snapshot), "global_sequence_barrier")
        self.assertGreaterEqual(snapshot.blockers[0].blocked_successors, 20)

    def test_self_slow_item_is_not_counted_as_blocked_successor(self):
        trace = PumpSwapSequenceBarrierTraceV50()
        n0 = _notification("sig0")
        n1 = _notification("sig1")
        trace.observe_ingress(n0, observed_monotonic=0.0)
        trace.observe_ingress(n1, observed_monotonic=0.1)
        trace.observe_normalization(n0, _handle(1.0))
        trace.observe_normalization(n1, _handle(3.0))
        trace.observe_reservation(_reservation(0, 1.01, "A", 0))
        trace.observe_reservation(_reservation(1, 3.01, "B", 0))

        snapshot = trace.snapshot()
        self.assertEqual(
            [row.prefix_normalization_barrier_seconds for row in snapshot.rows],
            [0.0, 0.0],
        )
        self.assertEqual(snapshot.blockers, ())

    def test_reservation_and_ready_lifecycle_is_counted_without_scheduler_mutation(self):
        trace = PumpSwapSequenceBarrierTraceV50()
        notification = _notification("sig")
        trace.observe_ingress(notification, observed_monotonic=1.0)
        trace.observe_normalization(notification, _handle(1.2))
        reservation = _reservation(0, 1.3, "A", 0)
        trace.observe_reservation(reservation)
        trace.observe_submit_or_skip(
            reservation,
            disposition="submit",
            observed_monotonic=1.4,
        )
        trace.observe_ready(
            SimpleNamespace(reservation=reservation, dependency_ready_monotonic=1.7)
        )
        trace.observe_complete(reservation, observed_monotonic=1.8)

        snapshot = trace.snapshot()
        self.assertEqual(snapshot.ingress_count, 1)
        self.assertEqual(snapshot.normalization_count, 1)
        self.assertEqual(snapshot.reservation_count, 1)
        self.assertEqual(snapshot.submit_or_skip_count, 1)
        self.assertEqual(snapshot.ready_count, 1)
        self.assertAlmostEqual(snapshot.rows[0].reservation_to_submit_seconds, 0.1)
        self.assertAlmostEqual(snapshot.rows[0].submit_to_dependency_ready_seconds, 0.3)

    def test_v50_keeps_immutable_reference_to_v49_runner(self):
        self.assertIsNot(v50._BASE_V49_RUN_SMOKE, v50.run_smoke_v50)


if __name__ == "__main__":
    unittest.main()
