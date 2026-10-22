from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PartialOrderSnapshotV6:
    """Diagnostics for the causal-admission dependency graph."""

    admissions: int
    dependency_edges: int
    disjoint_admissions: int
    overlapping_admissions: int
    out_of_ingress_admissions: int
    max_predecessors_per_admission: int


class PumpSwapPartialOrderCoordinatorV6:
    """Build per-asset dependencies without a global normalization prefix.

    Ordering is the order in which a notification's conservative asset superset becomes
    causally available. The coordinator does not claim ingress FIFO across an unresolved
    normalization gap. It does preserve one ticket chain per asset: a reservation waits only
    for the immediately preceding admitted reservation that touches the same asset.

    Every edge points to an earlier admission, so multi-asset reservations cannot create a
    dependency cycle. The underlying ready scheduler remains responsible for release, skip,
    completion, and stateful/demoted queue semantics.
    """

    def __init__(self, scheduler: Any) -> None:
        self.scheduler = scheduler
        self._last_admission_by_asset: dict[str, int] = {}
        self._predecessors_by_reservation: dict[int, tuple[int, ...]] = {}
        self._seen_sequences: set[int] = set()
        self._max_sequence = -1
        self._admissions = 0
        self._dependency_edges = 0
        self._disjoint_admissions = 0
        self._overlapping_admissions = 0
        self._out_of_ingress_admissions = 0
        self._max_predecessors = 0

    def reserve(self, sequence: int, assets: tuple[str, ...] | list[str]):
        sequence = int(sequence)
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        if sequence in self._seen_sequences:
            raise RuntimeError(f"duplicate PumpSwap partial-order sequence: {sequence}")

        normalized_assets = tuple(
            sorted({str(asset).strip() for asset in assets if str(asset).strip()})
        )
        predecessor_ids = tuple(
            sorted(
                {
                    self._last_admission_by_asset[asset]
                    for asset in normalized_assets
                    if asset in self._last_admission_by_asset
                }
            )
        )
        reservation = self.scheduler.reserve(normalized_assets)
        reservation_id = int(getattr(reservation, "reservation_id", -1))
        if reservation_id < 0:
            raise RuntimeError("partial-order reservation is missing its identity")
        if any(predecessor_id >= reservation_id for predecessor_id in predecessor_ids):
            raise RuntimeError("partial-order predecessor is not earlier than its reservation")

        self._seen_sequences.add(sequence)
        if sequence < self._max_sequence:
            self._out_of_ingress_admissions += 1
        self._max_sequence = max(self._max_sequence, sequence)
        self._admissions += 1
        self._dependency_edges += len(predecessor_ids)
        self._max_predecessors = max(self._max_predecessors, len(predecessor_ids))
        if predecessor_ids:
            self._overlapping_admissions += 1
        else:
            self._disjoint_admissions += 1
        self._predecessors_by_reservation[reservation_id] = predecessor_ids
        for asset in normalized_assets:
            self._last_admission_by_asset[asset] = reservation_id
        return reservation

    def assert_acyclic(self) -> None:
        for reservation_id, predecessors in self._predecessors_by_reservation.items():
            if any(predecessor_id >= reservation_id for predecessor_id in predecessors):
                raise AssertionError(
                    "PumpSwap partial-order graph contains a non-causal dependency"
                )

    def snapshot(self) -> PartialOrderSnapshotV6:
        self.assert_acyclic()
        return PartialOrderSnapshotV6(
            admissions=self._admissions,
            dependency_edges=self._dependency_edges,
            disjoint_admissions=self._disjoint_admissions,
            overlapping_admissions=self._overlapping_admissions,
            out_of_ingress_admissions=self._out_of_ingress_admissions,
            max_predecessors_per_admission=self._max_predecessors,
        )
