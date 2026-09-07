from types import SimpleNamespace

import pytest

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


def test_prefix_blocker_attributes_successor_wait_to_late_predecessor():
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
    assert len(snapshot.rows) == 3
    row2 = snapshot.rows[2]
    assert row2.sequence == 2
    assert row2.blocker_sequence == 1
    assert row2.prefix_normalization_barrier_seconds == pytest.approx(2.0)
    assert row2.post_prefix_coordinator_seconds == pytest.approx(0.1)
    assert row2.normalization_to_reservation_seconds == pytest.approx(2.1)

    assert snapshot.blockers[0].blocker_sequence == 1
    assert snapshot.blockers[0].blocker_signature == "sig1"
    assert snapshot.blockers[0].blocked_successors == 1
    assert snapshot.blockers[0].total_successor_barrier_seconds == pytest.approx(2.0)
    assert dominant_clock_v50(snapshot) == "global_sequence_barrier"


def test_self_slow_item_is_not_counted_as_blocked_successor():
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
    assert [row.prefix_normalization_barrier_seconds for row in snapshot.rows] == [0.0, 0.0]
    assert snapshot.blockers == ()


def test_reservation_and_ready_lifecycle_is_counted_without_changing_scheduler_state():
    trace = PumpSwapSequenceBarrierTraceV50()
    notification = _notification("sig")
    trace.observe_ingress(notification, observed_monotonic=1.0)
    trace.observe_normalization(notification, _handle(1.2))
    reservation = _reservation(0, 1.3, "A", 0)
    trace.observe_reservation(reservation)
    trace.observe_submit_or_skip(reservation, disposition="submit", observed_monotonic=1.4)
    trace.observe_ready(
        SimpleNamespace(reservation=reservation, dependency_ready_monotonic=1.7)
    )
    trace.observe_complete(reservation, observed_monotonic=1.8)

    snapshot = trace.snapshot()
    assert snapshot.ingress_count == 1
    assert snapshot.normalization_count == 1
    assert snapshot.reservation_count == 1
    assert snapshot.submit_or_skip_count == 1
    assert snapshot.ready_count == 1
    assert snapshot.rows[0].reservation_to_submit_seconds == pytest.approx(0.1)
    assert snapshot.rows[0].submit_to_dependency_ready_seconds == pytest.approx(0.3)


def test_v50_keeps_immutable_reference_to_v49_runner():
    assert v50._BASE_V49_RUN_SMOKE is not v50.run_smoke_v50
