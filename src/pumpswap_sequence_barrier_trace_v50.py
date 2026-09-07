from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import threading
import time
from typing import Any


@dataclass
class SequenceTraceV50:
    sequence: int
    notification_id: int
    signature: str
    ingress_monotonic: float
    normalization_completed_monotonic: float | None = None
    reservation_created_monotonic: float | None = None
    submit_monotonic: float | None = None
    dependency_ready_monotonic: float | None = None
    completed_monotonic: float | None = None
    assets: tuple[str, ...] = ()
    tickets: tuple[tuple[str, int], ...] = ()
    disposition: str | None = None


@dataclass(frozen=True)
class SequenceBarrierRowV50:
    sequence: int
    blocker_sequence: int
    self_ingress_to_normalization_seconds: float
    prefix_normalization_barrier_seconds: float
    post_prefix_coordinator_seconds: float
    normalization_to_reservation_seconds: float
    reservation_to_submit_seconds: float | None
    submit_to_dependency_ready_seconds: float | None


@dataclass(frozen=True)
class BlockerSummaryV50:
    blocker_sequence: int
    blocked_successors: int
    total_successor_barrier_seconds: float
    max_successor_barrier_seconds: float
    blocker_ingress_to_normalization_seconds: float


@dataclass(frozen=True)
class SequenceBarrierSnapshotV50:
    ingress_count: int
    normalization_count: int
    reservation_count: int
    submit_or_skip_count: int
    ready_count: int
    rows: tuple[SequenceBarrierRowV50, ...]
    blockers: tuple[BlockerSummaryV50, ...]


def percentile_v50(values: list[float] | tuple[float, ...], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


class PumpSwapSequenceBarrierTraceV50:
    """Diagnostic-only reconstruction of PumpSwap global reservation head-of-line delay.

    The v19 reservation coordinator issues reservations strictly in PumpSwap ingress sequence.
    Therefore, for sequence ``i``, the earliest possible global release time is the prefix maximum
    of normalization completion times for sequences ``0..i``. A later-normalized predecessor that
    owns that prefix maximum is the exact global watermark blocker for already-normalized
    successors. This tracer records timestamps only; it never participates in scheduling.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_ingress_sequence = 0
        self._next_reservation_sequence = 0
        self._by_sequence: dict[int, SequenceTraceV50] = {}
        self._sequence_by_notification_id: dict[int, int] = {}
        self._sequence_by_reservation_identity: dict[tuple[str, int], int] = {}

    @staticmethod
    def _reservation_identity(reservation: Any) -> tuple[str, int]:
        reservation_id = int(getattr(reservation, "reservation_id", -1))
        if reservation_id >= 0:
            return ("issued", reservation_id)
        return ("external", id(reservation))

    def observe_ingress(self, notification: Any, *, observed_monotonic: float | None = None) -> int:
        now = time.monotonic() if observed_monotonic is None else float(observed_monotonic)
        notification_id = id(notification)
        signature = str(getattr(notification, "signature", ""))
        with self._lock:
            if notification_id in self._sequence_by_notification_id:
                return self._sequence_by_notification_id[notification_id]
            sequence = self._next_ingress_sequence
            self._next_ingress_sequence += 1
            self._sequence_by_notification_id[notification_id] = sequence
            self._by_sequence[sequence] = SequenceTraceV50(
                sequence=sequence,
                notification_id=notification_id,
                signature=signature,
                ingress_monotonic=now,
            )
            return sequence

    def observe_normalization(self, notification: Any, handle: Any) -> None:
        notification_id = id(notification)
        completed = float(getattr(handle, "normalization_completed_monotonic"))
        with self._lock:
            sequence = self._sequence_by_notification_id.get(notification_id)
            if sequence is None:
                return
            self._by_sequence[sequence].normalization_completed_monotonic = completed

    def observe_reservation(self, reservation: Any) -> None:
        with self._lock:
            sequence = self._next_reservation_sequence
            self._next_reservation_sequence += 1
            trace = self._by_sequence.get(sequence)
            if trace is None:
                return
            trace.reservation_created_monotonic = float(
                getattr(reservation, "created_monotonic", time.monotonic())
            )
            trace.assets = tuple(str(asset) for asset in getattr(reservation, "assets", ()))
            trace.tickets = tuple(
                (str(asset), int(ticket)) for asset, ticket in getattr(reservation, "tickets", ())
            )
            self._sequence_by_reservation_identity[
                self._reservation_identity(reservation)
            ] = sequence

    def observe_submit_or_skip(
        self,
        reservation: Any,
        *,
        disposition: str,
        observed_monotonic: float | None = None,
    ) -> None:
        now = time.monotonic() if observed_monotonic is None else float(observed_monotonic)
        with self._lock:
            sequence = self._sequence_by_reservation_identity.get(
                self._reservation_identity(reservation)
            )
            if sequence is None:
                return
            trace = self._by_sequence[sequence]
            if trace.submit_monotonic is None:
                trace.submit_monotonic = now
                trace.disposition = disposition

    def observe_ready(self, work: Any) -> None:
        reservation = getattr(work, "reservation", None)
        if reservation is None:
            return
        ready = float(getattr(work, "dependency_ready_monotonic", time.monotonic()))
        with self._lock:
            sequence = self._sequence_by_reservation_identity.get(
                self._reservation_identity(reservation)
            )
            if sequence is None:
                return
            self._by_sequence[sequence].dependency_ready_monotonic = ready

    def observe_complete(self, reservation: Any, *, observed_monotonic: float | None = None) -> None:
        now = time.monotonic() if observed_monotonic is None else float(observed_monotonic)
        with self._lock:
            sequence = self._sequence_by_reservation_identity.get(
                self._reservation_identity(reservation)
            )
            if sequence is None:
                return
            self._by_sequence[sequence].completed_monotonic = now

    def snapshot(self) -> SequenceBarrierSnapshotV50:
        with self._lock:
            traces = [self._by_sequence[index] for index in sorted(self._by_sequence)]

        rows: list[SequenceBarrierRowV50] = []
        prefix_max_normalization: float | None = None
        prefix_blocker_sequence: int | None = None
        blocker_accumulator: dict[int, list[float]] = defaultdict(list)

        for trace in traces:
            normalization = trace.normalization_completed_monotonic
            reservation = trace.reservation_created_monotonic
            if normalization is None or reservation is None:
                continue

            if prefix_max_normalization is None or normalization >= prefix_max_normalization:
                prefix_max_normalization = normalization
                prefix_blocker_sequence = trace.sequence

            assert prefix_blocker_sequence is not None
            barrier = max(0.0, prefix_max_normalization - normalization)
            coordinator = max(0.0, reservation - prefix_max_normalization)
            normalization_to_reservation = max(0.0, reservation - normalization)
            reservation_to_submit = (
                max(0.0, trace.submit_monotonic - reservation)
                if trace.submit_monotonic is not None
                else None
            )
            submit_to_ready = (
                max(0.0, trace.dependency_ready_monotonic - trace.submit_monotonic)
                if trace.submit_monotonic is not None
                and trace.dependency_ready_monotonic is not None
                else None
            )
            self_normalization = max(0.0, normalization - trace.ingress_monotonic)

            if prefix_blocker_sequence != trace.sequence and barrier > 0:
                blocker_accumulator[prefix_blocker_sequence].append(barrier)

            rows.append(
                SequenceBarrierRowV50(
                    sequence=trace.sequence,
                    blocker_sequence=prefix_blocker_sequence,
                    self_ingress_to_normalization_seconds=self_normalization,
                    prefix_normalization_barrier_seconds=barrier,
                    post_prefix_coordinator_seconds=coordinator,
                    normalization_to_reservation_seconds=normalization_to_reservation,
                    reservation_to_submit_seconds=reservation_to_submit,
                    submit_to_dependency_ready_seconds=submit_to_ready,
                )
            )

        trace_by_sequence = {trace.sequence: trace for trace in traces}
        blockers: list[BlockerSummaryV50] = []
        for blocker_sequence, waits in blocker_accumulator.items():
            trace = trace_by_sequence[blocker_sequence]
            normalization = trace.normalization_completed_monotonic
            assert normalization is not None
            blockers.append(
                BlockerSummaryV50(
                    blocker_sequence=blocker_sequence,
                    blocked_successors=len(waits),
                    total_successor_barrier_seconds=sum(waits),
                    max_successor_barrier_seconds=max(waits, default=0.0),
                    blocker_ingress_to_normalization_seconds=max(
                        0.0, normalization - trace.ingress_monotonic
                    ),
                )
            )
        blockers.sort(
            key=lambda item: (
                item.total_successor_barrier_seconds,
                item.max_successor_barrier_seconds,
                item.blocked_successors,
            ),
            reverse=True,
        )

        return SequenceBarrierSnapshotV50(
            ingress_count=len(traces),
            normalization_count=sum(
                trace.normalization_completed_monotonic is not None for trace in traces
            ),
            reservation_count=sum(
                trace.reservation_created_monotonic is not None for trace in traces
            ),
            submit_or_skip_count=sum(trace.submit_monotonic is not None for trace in traces),
            ready_count=sum(trace.dependency_ready_monotonic is not None for trace in traces),
            rows=tuple(rows),
            blockers=tuple(blockers),
        )


def dominant_clock_v50(snapshot: SequenceBarrierSnapshotV50) -> str:
    if not snapshot.rows:
        return "insufficient_trace"
    barrier = percentile_v50(
        [row.prefix_normalization_barrier_seconds for row in snapshot.rows], 0.95
    )
    coordinator = percentile_v50(
        [row.post_prefix_coordinator_seconds for row in snapshot.rows], 0.95
    )
    reservation_submit = percentile_v50(
        [
            row.reservation_to_submit_seconds
            for row in snapshot.rows
            if row.reservation_to_submit_seconds is not None
        ],
        0.95,
    )
    submit_ready = percentile_v50(
        [
            row.submit_to_dependency_ready_seconds
            for row in snapshot.rows
            if row.submit_to_dependency_ready_seconds is not None
        ],
        0.95,
    )
    clocks = {
        "global_sequence_barrier": barrier,
        "post_prefix_coordinator": coordinator,
        "reservation_to_submit": reservation_submit,
        "per_asset_dependency": submit_ready,
    }
    return max(clocks, key=clocks.get)
