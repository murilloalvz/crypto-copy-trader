from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


def pearson_correlation(left: Iterable[float], right: Iterable[float]) -> float:
    pairs = list(zip(left, right))
    if len(pairs) < 2:
        return 0.0
    left_mean = sum(item[0] for item in pairs) / len(pairs)
    right_mean = sum(item[1] for item in pairs) / len(pairs)
    left_centered = [item[0] - left_mean for item in pairs]
    right_centered = [item[1] - right_mean for item in pairs]
    left_norm = sum(value * value for value in left_centered) ** 0.5
    right_norm = sum(value * value for value in right_centered) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left_centered, right_centered)) / (
        left_norm * right_norm
    )


@dataclass(frozen=True)
class PumpSwapHOLDiagnosticSnapshotV7:
    records: int
    stateful_records: int
    demoted_records: int
    dependency_wait_p95_seconds: float
    ready_capacity_wait_p95_seconds: float
    stateful_predecessor_incomplete_p95_seconds: float
    stateful_capacity_wait_p95_seconds: float
    demoted_predecessor_incomplete_p95_seconds: float
    demoted_capacity_wait_p95_seconds: float
    stateful_finalizer_occupied_p95_seconds: float
    demoted_finalizer_occupied_p95_seconds: float
    writer_result_wait_p95_seconds: float
    writer_vs_dependency_correlation: float
    writer_vs_ready_capacity_correlation: float
    top_hot_asset_count: int
    top_hot_dependency_wait_share_pct: float
    top_hot_dependency_wait_p95_seconds: float
    cold_dependency_wait_p95_seconds: float
    dependency_wait_by_asset_p95_seconds: tuple[tuple[str, float], ...]


@dataclass
class PumpSwapHOLDiagnosticsV7:
    """Observation-only attribution for the V6 remaining tail.

    A dependency wait is measured before a work item enters the ready queue. A capacity
    wait is measured after that entry and therefore cannot include an incomplete causal
    predecessor. This class records that distinction without participating in scheduling.
    """

    dependency_waits: list[float] = field(default_factory=list)
    ready_capacity_waits: list[float] = field(default_factory=list)
    writer_result_waits: list[float] = field(default_factory=list)
    _dependency_by_asset: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _stateful_dependency_waits: list[float] = field(default_factory=list)
    _stateful_capacity_waits: list[float] = field(default_factory=list)
    _demoted_dependency_waits: list[float] = field(default_factory=list)
    _demoted_capacity_waits: list[float] = field(default_factory=list)
    _stateful_occupied: list[float] = field(default_factory=list)
    _demoted_occupied: list[float] = field(default_factory=list)
    _writer_dependency_pairs: list[tuple[float, float]] = field(default_factory=list)
    _writer_capacity_pairs: list[tuple[float, float]] = field(default_factory=list)

    def record(
        self,
        *,
        blocking_assets: tuple[str, ...],
        dependency_wait_seconds: float,
        ready_capacity_wait_seconds: float,
        writer_result_wait_seconds: float,
        finalizer_occupied_seconds: float,
        is_demoted: bool,
    ) -> None:
        dependency_wait = max(0.0, float(dependency_wait_seconds))
        capacity_wait = max(0.0, float(ready_capacity_wait_seconds))
        writer_wait = max(0.0, float(writer_result_wait_seconds))
        occupied = max(0.0, float(finalizer_occupied_seconds))
        self.dependency_waits.append(dependency_wait)
        self.ready_capacity_waits.append(capacity_wait)
        self.writer_result_waits.append(writer_wait)
        self._writer_dependency_pairs.append((writer_wait, dependency_wait))
        self._writer_capacity_pairs.append((writer_wait, capacity_wait))
        for asset in blocking_assets:
            self._dependency_by_asset[str(asset)].append(dependency_wait)
        if is_demoted:
            self._demoted_dependency_waits.append(dependency_wait)
            self._demoted_capacity_waits.append(capacity_wait)
            self._demoted_occupied.append(occupied)
        else:
            self._stateful_dependency_waits.append(dependency_wait)
            self._stateful_capacity_waits.append(capacity_wait)
            self._stateful_occupied.append(occupied)

    def snapshot(self) -> PumpSwapHOLDiagnosticSnapshotV7:
        by_asset = {
            asset: tuple(waits)
            for asset, waits in self._dependency_by_asset.items()
            if waits
        }
        ordered_assets = sorted(
            by_asset,
            key=lambda asset: (-sum(by_asset[asset]), asset),
        )
        top_assets = set(ordered_assets[:5])
        top_values = [
            wait
            for asset, waits in by_asset.items()
            if asset in top_assets
            for wait in waits
        ]
        cold_values = [
            wait
            for asset, waits in by_asset.items()
            if asset not in top_assets
            for wait in waits
        ]
        total_wait = sum(self.dependency_waits)
        top_wait = sum(top_values)
        return PumpSwapHOLDiagnosticSnapshotV7(
            records=len(self.dependency_waits),
            stateful_records=len(self._stateful_dependency_waits),
            demoted_records=len(self._demoted_dependency_waits),
            dependency_wait_p95_seconds=percentile(self.dependency_waits, 0.95),
            ready_capacity_wait_p95_seconds=percentile(self.ready_capacity_waits, 0.95),
            stateful_predecessor_incomplete_p95_seconds=percentile(
                self._stateful_dependency_waits, 0.95
            ),
            stateful_capacity_wait_p95_seconds=percentile(
                self._stateful_capacity_waits, 0.95
            ),
            demoted_predecessor_incomplete_p95_seconds=percentile(
                self._demoted_dependency_waits, 0.95
            ),
            demoted_capacity_wait_p95_seconds=percentile(
                self._demoted_capacity_waits, 0.95
            ),
            stateful_finalizer_occupied_p95_seconds=percentile(
                self._stateful_occupied, 0.95
            ),
            demoted_finalizer_occupied_p95_seconds=percentile(
                self._demoted_occupied, 0.95
            ),
            writer_result_wait_p95_seconds=percentile(self.writer_result_waits, 0.95),
            writer_vs_dependency_correlation=pearson_correlation(
                (item[0] for item in self._writer_dependency_pairs),
                (item[1] for item in self._writer_dependency_pairs),
            ),
            writer_vs_ready_capacity_correlation=pearson_correlation(
                (item[0] for item in self._writer_capacity_pairs),
                (item[1] for item in self._writer_capacity_pairs),
            ),
            top_hot_asset_count=len(top_assets),
            top_hot_dependency_wait_share_pct=(
                100.0 * top_wait / total_wait if total_wait else 0.0
            ),
            top_hot_dependency_wait_p95_seconds=percentile(top_values, 0.95),
            cold_dependency_wait_p95_seconds=percentile(cold_values, 0.95),
            dependency_wait_by_asset_p95_seconds=tuple(
                (asset, percentile(by_asset[asset], 0.95))
                for asset in ordered_assets
            ),
        )
