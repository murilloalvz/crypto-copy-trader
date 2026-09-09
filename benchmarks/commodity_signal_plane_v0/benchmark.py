from __future__ import annotations

import argparse
import bisect
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import statistics
import time
import tracemalloc
from typing import Callable, Iterable

from src.market_opportunity_radar import (
    MarketLifecycleObservation,
    MarketMovementTrigger,
    MarketRadarConfig,
    MarketTradeObservation,
    detect_market_movement,
)

TRACE_VERSION = "canonical_market_trace_v0"
DEFAULT_SCALES = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class TraceRecord:
    sequence: int
    arrival_offset_ns: int
    kind: str
    event_key: str
    source_provider: str
    trade: MarketTradeObservation | None = None
    lifecycle: MarketLifecycleObservation | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.arrival_offset_ns < 0:
            raise ValueError("arrival_offset_ns must be non-negative")
        if self.kind not in {"trade", "lifecycle"}:
            raise ValueError("kind must be trade or lifecycle")
        if not self.event_key.strip() or not self.source_provider.strip():
            raise ValueError("event_key/source_provider cannot be blank")
        if self.kind == "trade" and (self.trade is None or self.lifecycle is not None):
            raise ValueError("trade record must contain only trade payload")
        if self.kind == "lifecycle" and (self.lifecycle is None or self.trade is not None):
            raise ValueError("lifecycle record must contain only lifecycle payload")


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def _record_to_json(record: TraceRecord) -> dict:
    payload = {
        "type": record.kind,
        "sequence": record.sequence,
        "arrival_offset_ns": record.arrival_offset_ns,
        "event_key": record.event_key,
        "source_provider": record.source_provider,
    }
    if record.trade is not None:
        payload["observation"] = asdict(record.trade)
    else:
        assert record.lifecycle is not None
        payload["observation"] = asdict(record.lifecycle)
    return payload


def _record_from_json(payload: dict) -> TraceRecord:
    kind = str(payload["type"])
    observation = dict(payload["observation"])
    if kind == "trade":
        return TraceRecord(
            sequence=int(payload["sequence"]),
            arrival_offset_ns=int(payload["arrival_offset_ns"]),
            kind=kind,
            event_key=str(payload["event_key"]),
            source_provider=str(payload["source_provider"]),
            trade=MarketTradeObservation(**observation),
        )
    if kind == "lifecycle":
        return TraceRecord(
            sequence=int(payload["sequence"]),
            arrival_offset_ns=int(payload["arrival_offset_ns"]),
            kind=kind,
            event_key=str(payload["event_key"]),
            source_provider=str(payload["source_provider"]),
            lifecycle=MarketLifecycleObservation(**observation),
        )
    raise ValueError(f"unknown trace record type: {kind}")


def write_trace(path: Path, records: Iterable[TraceRecord], *, metadata: dict) -> dict:
    materialized = tuple(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "type": "trace_header",
        "version": TRACE_VERSION,
        "record_count": len(materialized),
        **metadata,
    }
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
        for record in materialized:
            handle.write(
                json.dumps(_record_to_json(record), sort_keys=True, separators=(",", ":"))
                + "\n"
            )
    return header


def load_trace(path: Path) -> tuple[dict, tuple[TraceRecord, ...]]:
    with path.open("r", encoding="utf-8") as handle:
        first = handle.readline()
        if not first:
            raise ValueError("trace is empty")
        header = json.loads(first)
        if header.get("type") != "trace_header" or header.get("version") != TRACE_VERSION:
            raise ValueError("unsupported trace header/version")
        records = tuple(_record_from_json(json.loads(line)) for line in handle if line.strip())
    if int(header.get("record_count", -1)) != len(records):
        raise ValueError("trace record_count mismatch")
    expected = list(range(len(records)))
    actual = [item.sequence for item in records]
    if actual != expected:
        raise ValueError("trace sequence must be contiguous and ordered")
    offsets = [item.arrival_offset_ns for item in records]
    if offsets != sorted(offsets):
        raise ValueError("arrival offsets must be non-decreasing")
    return header, records


PUMP_LIFECYCLE_VENUES = {"pump", "pump_bonding_curve", "pumpfun", "pump.fun"}


def _uses_lifecycle(trade: MarketTradeObservation) -> bool:
    venue = (trade.venue or "").strip().lower()
    return venue in PUMP_LIFECYCLE_VENUES


def _is_pump_lifecycle(item: MarketLifecycleObservation) -> bool:
    venue = (item.venue or "").strip().lower()
    return venue in PUMP_LIFECYCLE_VENUES


def _trigger_snapshot(trigger: MarketMovementTrigger | None) -> dict | None:
    if trigger is None:
        return None
    return {
        "token_mint": trigger.token_mint,
        "as_of": trigger.as_of,
        "method_version": trigger.method_version,
        "trigger_kind": trigger.trigger_kind,
        "direction": trigger.direction,
        "features": asdict(trigger.features),
    }


class ReferenceRadarState:
    """Unbounded reference state; correctness oracle at the Radar boundary."""

    def __init__(self, config: MarketRadarConfig = MarketRadarConfig()) -> None:
        self.config = config
        self.trades: dict[str, list[MarketTradeObservation]] = defaultdict(list)
        self.lifecycle: dict[str, MarketLifecycleObservation] = {}

    def ingest(self, record: TraceRecord) -> MarketMovementTrigger | None:
        if record.kind == "lifecycle":
            assert record.lifecycle is not None
            if _is_pump_lifecycle(record.lifecycle):
                current = self.lifecycle.get(record.lifecycle.token_mint)
                if current is None or record.lifecycle.observed_at >= current.observed_at:
                    self.lifecycle[record.lifecycle.token_mint] = record.lifecycle
            return None

        assert record.trade is not None
        trade = record.trade
        self.trades[trade.token_mint].append(trade)
        lifecycle = self.lifecycle.get(trade.token_mint) if _uses_lifecycle(trade) else None
        return detect_market_movement(
            self.trades[trade.token_mint],
            token_mint=trade.token_mint,
            as_of=trade.observed_at,
            lifecycle=lifecycle,
            config=self.config,
        )


class BoundedMemoryRadarState:
    """Memory-first shadow state retaining only the detector's causal horizon."""

    def __init__(self, config: MarketRadarConfig = MarketRadarConfig()) -> None:
        self.config = config
        self.trades: dict[str, deque[tuple[int, int, int, MarketTradeObservation]]] = defaultdict(deque)
        self.lifecycle: dict[str, MarketLifecycleObservation] = {}
        self.late_chain_time_inserts = 0

    def _insert_trade(self, record: TraceRecord) -> deque[tuple[int, int, int, MarketTradeObservation]]:
        assert record.trade is not None
        trade = record.trade
        rows = self.trades[trade.token_mint]
        item = (trade.chain_time, trade.observed_at, record.sequence, trade)
        if not rows or (rows[-1][0], rows[-1][1], rows[-1][2]) <= item[:3]:
            rows.append(item)
        else:
            self.late_chain_time_inserts += 1
            materialized = list(rows)
            keys = [(x[0], x[1], x[2]) for x in materialized]
            index = bisect.bisect_right(keys, item[:3])
            materialized.insert(index, item)
            rows.clear()
            rows.extend(materialized)

        cutoff = trade.observed_at - self.config.baseline_horizon_seconds
        while rows and rows[0][0] <= cutoff:
            rows.popleft()
        return rows

    def ingest(self, record: TraceRecord) -> MarketMovementTrigger | None:
        if record.kind == "lifecycle":
            assert record.lifecycle is not None
            if _is_pump_lifecycle(record.lifecycle):
                current = self.lifecycle.get(record.lifecycle.token_mint)
                if current is None or record.lifecycle.observed_at >= current.observed_at:
                    self.lifecycle[record.lifecycle.token_mint] = record.lifecycle
            return None

        assert record.trade is not None
        trade = record.trade
        rows = self._insert_trade(record)
        lifecycle = self.lifecycle.get(trade.token_mint) if _uses_lifecycle(trade) else None
        return detect_market_movement(
            [item[3] for item in rows],
            token_mint=trade.token_mint,
            as_of=trade.observed_at,
            lifecycle=lifecycle,
            config=self.config,
        )


def _measure_path(
    records: tuple[TraceRecord, ...],
    factory: Callable[[], ReferenceRadarState | BoundedMemoryRadarState],
) -> dict:
    state = factory()
    decisions: dict[int, dict | None] = {}
    service_seconds: list[float] = []
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    for record in records:
        started = time.perf_counter_ns()
        trigger = state.ingest(record)
        service_seconds.append((time.perf_counter_ns() - started) / 1_000_000_000.0)
        if record.kind == "trade":
            decisions[record.sequence] = _trigger_snapshot(trigger)
    cpu_seconds = time.process_time() - cpu_started
    wall_seconds = time.perf_counter() - wall_started

    tracemalloc.start()
    memory_state = factory()
    for record in records:
        memory_state.ingest(record)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "decisions": decisions,
        "service_seconds": service_seconds,
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "peak_tracemalloc_bytes": peak_bytes,
        "sustainable_eps": (len(records) / wall_seconds if wall_seconds > 0 else math.inf),
        "service_p50_ms": (_percentile(service_seconds, 50) or 0.0) * 1000.0,
        "service_p95_ms": (_percentile(service_seconds, 95) or 0.0) * 1000.0,
        "service_p99_ms": (_percentile(service_seconds, 99) or 0.0) * 1000.0,
        "late_chain_time_inserts": int(getattr(state, "late_chain_time_inserts", 0)),
    }


def simulate_single_worker_queue(
    records: tuple[TraceRecord, ...],
    service_seconds: list[float],
    *,
    scale: float | None,
) -> dict:
    if len(records) != len(service_seconds):
        raise ValueError("records/service_seconds length mismatch")
    if not records:
        return {
            "scale": "MAX" if scale is None else scale,
            "arrival_rate_eps": 0.0,
            "queue_wait_p50_ms": 0.0,
            "queue_wait_p95_ms": 0.0,
            "queue_wait_p99_ms": 0.0,
            "outstanding_high_water": 0,
            "queue_depth_high_water": 0,
            "oldest_item_age_max_ms": 0.0,
            "outstanding_at_source_end": 0,
            "backlog_at_source_end": 0,
            "backlog_growth_eps_at_source_end": 0.0,
            "drain_after_source_seconds": 0.0,
        }
    if scale is not None and scale <= 0:
        raise ValueError("scale must be positive")

    base_arrivals = [item.arrival_offset_ns / 1_000_000_000.0 for item in records]
    arrivals = [0.0 for _ in base_arrivals] if scale is None else [x / scale for x in base_arrivals]

    completions: deque[float] = deque()
    pending_arrivals: deque[float] = deque()
    waits: list[float] = []
    oldest_ages: list[float] = []
    outstanding_high_water = 0
    queue_depth_high_water = 0
    previous_end = 0.0

    for arrival, service in zip(arrivals, service_seconds):
        while completions and completions[0] <= arrival:
            completions.popleft()
            pending_arrivals.popleft()

        started = max(arrival, previous_end)
        ended = started + max(0.0, service)
        wait = started - arrival
        waits.append(wait)
        completions.append(ended)
        pending_arrivals.append(arrival)
        previous_end = ended
        outstanding_high_water = max(outstanding_high_water, len(completions))
        queue_depth_high_water = max(queue_depth_high_water, max(0, len(completions) - 1))
        oldest_ages.append(max(0.0, arrival - pending_arrivals[0]))

    last_arrival = arrivals[-1]
    outstanding_end = sum(1 for completion in completions if completion > last_arrival)
    # One outstanding item can simply be the item in service at the instant the source stops.
    # Backlog here means *waiting* work, which is the saturation signal we care about.
    backlog_end = max(0, outstanding_end - 1)
    source_span = max(0.0, last_arrival - arrivals[0])
    arrival_rate = math.inf if scale is None or source_span <= 0 else (len(arrivals) - 1) / source_span

    backlog_growth_eps = (backlog_end / source_span) if source_span > 0 else 0.0
    return {
        "scale": "MAX" if scale is None else scale,
        "arrival_rate_eps": arrival_rate,
        "queue_wait_p50_ms": (_percentile(waits, 50) or 0.0) * 1000.0,
        "queue_wait_p95_ms": (_percentile(waits, 95) or 0.0) * 1000.0,
        "queue_wait_p99_ms": (_percentile(waits, 99) or 0.0) * 1000.0,
        "outstanding_high_water": outstanding_high_water,
        "queue_depth_high_water": queue_depth_high_water,
        "oldest_item_age_max_ms": (max(oldest_ages) if oldest_ages else 0.0) * 1000.0,
        "outstanding_at_source_end": outstanding_end,
        "backlog_at_source_end": backlog_end,
        "backlog_growth_eps_at_source_end": backlog_growth_eps,
        "drain_after_source_seconds": max(0.0, previous_end - last_arrival),
    }


def _path_report(records: tuple[TraceRecord, ...], measured: dict, scales: tuple[float, ...]) -> dict:
    service = measured["service_seconds"]
    mean_service = statistics.fmean(service) if service else 0.0
    capacity_eps = (1.0 / mean_service) if mean_service > 0 else math.inf
    queues = [simulate_single_worker_queue(records, service, scale=scale) for scale in scales]
    queues.append(simulate_single_worker_queue(records, service, scale=None))
    finite = [item for item in queues if item["scale"] != "MAX"]
    mean_rate_knee = next(
        (
            item["scale"]
            for item in finite
            if math.isfinite(item["arrival_rate_eps"])
            and capacity_eps > 0
            and item["arrival_rate_eps"] >= capacity_eps
        ),
        None,
    )
    backlog_knee = next(
        (item["scale"] for item in finite if item["backlog_at_source_end"] > 0),
        None,
    )
    return {
        key: value
        for key, value in measured.items()
        if key not in {"decisions", "service_seconds"}
    } | {
        "service_mean_ms": mean_service * 1000.0,
        "capacity_eps_from_mean_service": capacity_eps,
        "saturation_knee_scale_by_mean_rate": mean_rate_knee,
        "first_scale_with_source_end_backlog": backlog_knee,
        "queue_simulation": queues,
    }


def run_benchmark(
    records: tuple[TraceRecord, ...],
    *,
    scales: tuple[float, ...] = DEFAULT_SCALES,
) -> dict:
    reference = _measure_path(records, ReferenceRadarState)
    shadow = _measure_path(records, BoundedMemoryRadarState)

    decision_sequences = sorted(set(reference["decisions"]) | set(shadow["decisions"]))
    mismatches = [
        {
            "sequence": sequence,
            "reference": reference["decisions"].get(sequence),
            "shadow": shadow["decisions"].get(sequence),
        }
        for sequence in decision_sequences
        if reference["decisions"].get(sequence) != shadow["decisions"].get(sequence)
    ]
    exact_matches = len(decision_sequences) - len(mismatches)
    parity_pct = 100.0 if not decision_sequences else 100.0 * exact_matches / len(decision_sequences)

    source_span = 0.0
    observed_rate = 0.0
    if len(records) >= 2:
        source_span = (records[-1].arrival_offset_ns - records[0].arrival_offset_ns) / 1_000_000_000.0
        if source_span > 0:
            observed_rate = (len(records) - 1) / source_span

    return {
        "benchmark_version": "canonical_state_signal_kernel_v0",
        "trace_version": TRACE_VERSION,
        "record_count": len(records),
        "trade_decision_points": len(decision_sequences),
        "source_span_seconds": source_span,
        "observed_arrival_rate_eps": observed_rate,
        "parity": {
            "exact_matches": exact_matches,
            "mismatches": len(mismatches),
            "parity_pct": parity_pct,
            "first_mismatches": mismatches[:20],
        },
        "reference": _path_report(records, reference, scales),
        "shadow_memory_kernel": _path_report(records, shadow, scales),
        "interpretation": {
            "comparison_boundary": "canonical MarketTradeObservation/MarketLifecycleObservation -> frozen Radar",
            "decision_cadence": "per canonical trade record; this is kernel equivalence, not bridge notification parity",
            "carbon_decoder_tested": False,
            "why": (
                "This v0 benchmarks the canonical Radar boundary only. Carbon Pump/PumpSwap "
                "decoders require raw Solana transaction/meta/instruction trace data; persisted "
                "MarketTradeObservation rows are insufficient for a scientifically valid decoder comparison."
            ),
            "next_if_parity_100": "capture raw transaction trace and add Carbon decoder parity v1",
        },
    }


def export_persisted_trace(*, acquisition_run_key: str, out: Path) -> dict:
    from src.market_observation_store import ensure_market_observation_schema
    from src.database import connection

    run_key = acquisition_run_key.strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be blank")
    ensure_market_observation_schema()
    with connection() as conn:
        trades = conn.execute(
            """SELECT id, event_key, source_provider, token_mint, side, chain_time, observed_at,
            wallet_address, notional_usd, price_usd, venue, transaction_key
            FROM market_trade_observations WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchall()
        lifecycles = conn.execute(
            """SELECT id, event_key, source_provider, token_mint, market_started_at, observed_at, venue
            FROM market_lifecycle_observations WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchall()

    staged: list[tuple[tuple, str, object]] = []
    for row in trades:
        observation = MarketTradeObservation(
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
            wallet_address=(str(row["wallet_address"]) if row["wallet_address"] is not None else None),
            notional_usd=(float(row["notional_usd"]) if row["notional_usd"] is not None else None),
            price_usd=(float(row["price_usd"]) if row["price_usd"] is not None else None),
            venue=(str(row["venue"]) if row["venue"] is not None else None),
            transaction_key=(str(row["transaction_key"]) if row["transaction_key"] is not None else None),
        )
        staged.append(
            ((observation.observed_at, 1, observation.chain_time, int(row["id"]), str(row["event_key"])), "trade", (row, observation))
        )
    for row in lifecycles:
        observation = MarketLifecycleObservation(
            token_mint=str(row["token_mint"]),
            market_started_at=int(row["market_started_at"]),
            observed_at=int(row["observed_at"]),
            venue=(str(row["venue"]) if row["venue"] is not None else None),
        )
        staged.append(
            ((observation.observed_at, 0, observation.market_started_at, int(row["id"]), str(row["event_key"])), "lifecycle", (row, observation))
        )
    staged.sort(key=lambda item: item[0])
    if not staged:
        raise ValueError(f"no persisted market observations found for run-key {run_key!r}")

    first_observed = int(staged[0][0][0])
    tie_counts: dict[int, int] = defaultdict(int)
    records: list[TraceRecord] = []
    for sequence, (sort_key, kind, packed) in enumerate(staged):
        observed_at = int(sort_key[0])
        tie_index = tie_counts[observed_at]
        tie_counts[observed_at] += 1
        arrival_offset_ns = (observed_at - first_observed) * 1_000_000_000 + tie_index * 1_000
        row, observation = packed
        records.append(
            TraceRecord(
                sequence=sequence,
                arrival_offset_ns=arrival_offset_ns,
                kind=kind,
                event_key=str(row["event_key"]),
                source_provider=str(row["source_provider"]),
                trade=(observation if kind == "trade" else None),
                lifecycle=(observation if kind == "lifecycle" else None),
            )
        )

    return write_trace(
        out,
        records,
        metadata={
            "source": "persisted_market_observation_store",
            "acquisition_run_key": run_key,
            "order_quality": "reconstructed_from_second_resolution_observed_at",
            "equal_timestamp_tie_break": "lifecycle_then_chain_time_then_table_id_then_event_key",
            "raw_solana_transaction_available": False,
            "warning": "Equal-second ingress order is reconstructed, not proven original ingress order.",
        },
    )


def generate_synthetic_trace(*, out: Path, events: int, seed: int) -> dict:
    if events <= 0:
        raise ValueError("events must be positive")
    rng = random.Random(seed)
    token_count = max(6, min(48, events // 100 or 6))
    tokens = [f"SYNTH-{i:02d}" for i in range(token_count)]
    base_time = 1_000_000
    records: list[TraceRecord] = []

    sequence = 0
    for index, token in enumerate(tokens):
        if index % 2:
            continue
        lifecycle = MarketLifecycleObservation(
            token_mint=token,
            market_started_at=base_time - (20 + index * 11),
            observed_at=base_time,
            venue="pump_bonding_curve",
        )
        records.append(
            TraceRecord(
                sequence=sequence,
                arrival_offset_ns=sequence * 10_000,
                kind="lifecycle",
                event_key=f"lifecycle:{token}",
                source_provider="synthetic",
                lifecycle=lifecycle,
            )
        )
        sequence += 1

    target_eps = 70.0
    normal_interval = int(1_000_000_000 / target_eps)
    arrival_ns = 1_000_000
    for index in range(events):
        burst = (index % 600) < 120
        interval = max(1, normal_interval // (6 if burst else 1))
        arrival_ns += interval
        if burst and rng.random() < 0.62:
            token = tokens[0]
        else:
            token = tokens[index % token_count]
        observed_at = base_time + arrival_ns // 1_000_000_000
        lag = 1 if index % 17 == 0 else 0
        chain_time = observed_at - lag
        side = "buy" if (index + (0 if burst else 1)) % 4 != 0 else "sell"
        venue = "pump_bonding_curve" if int(token.split("-")[-1]) % 2 == 0 else "pumpswap"
        notional = 4.0 + (index % 23) * 0.7
        price = 1.0 + (index % 101) * 0.0005
        trade = MarketTradeObservation(
            token_mint=token,
            side=side,
            chain_time=int(chain_time),
            observed_at=int(observed_at),
            wallet_address=f"W-{index % 997}",
            notional_usd=notional,
            price_usd=price,
            venue=venue,
            transaction_key=f"TX-{index // 2}",
        )
        records.append(
            TraceRecord(
                sequence=sequence,
                arrival_offset_ns=arrival_ns,
                kind="trade",
                event_key=f"trade:{index}",
                source_provider="synthetic",
                trade=trade,
            )
        )
        sequence += 1

    records.sort(key=lambda item: (item.arrival_offset_ns, item.sequence))
    records = [
        TraceRecord(
            sequence=i,
            arrival_offset_ns=item.arrival_offset_ns,
            kind=item.kind,
            event_key=item.event_key,
            source_provider=item.source_provider,
            trade=item.trade,
            lifecycle=item.lifecycle,
        )
        for i, item in enumerate(records)
    ]
    return write_trace(
        out,
        records,
        metadata={
            "source": "deterministic_synthetic",
            "seed": seed,
            "target_normal_eps": target_eps,
            "raw_solana_transaction_available": False,
        },
    )


def _parse_scales(raw: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    if not values or any(value <= 0 for value in values):
        raise ValueError("scales must be a comma-separated list of positive numbers")
    return values


def _print_summary(report: dict) -> None:
    print("Canonical State/Signal Kernel Benchmark v0")
    print(f"records={report['record_count']} decision_points={report['trade_decision_points']}")
    print(
        f"parity={report['parity']['parity_pct']:.3f}% "
        f"mismatches={report['parity']['mismatches']}"
    )
    print(f"observed_arrival_rate={report['observed_arrival_rate_eps']:.2f} events/s")
    for key in ("reference", "shadow_memory_kernel"):
        item = report[key]
        print(
            f"{key}: wall={item['wall_seconds']:.3f}s "
            f"capacity~{item['capacity_eps_from_mean_service']:.1f}/s "
            f"service_p95={item['service_p95_ms']:.3f}ms "
            f"service_p99={item['service_p99_ms']:.3f}ms "
            f"knee_rate={item['saturation_knee_scale_by_mean_rate']} "
            f"knee_backlog={item['first_scale_with_source_end_backlog']}"
        )
        for queue in item["queue_simulation"]:
            scale = queue["scale"]
            scale_label = "MAX" if scale == "MAX" else f"{scale}x"
            print(
                f"  {scale_label}: qwait_p95={queue['queue_wait_p95_ms']:.2f}ms "
                f"qwait_p99={queue['queue_wait_p99_ms']:.2f}ms "
                f"depth_hi={queue['queue_depth_high_water']} "
                f"drain={queue['drain_after_source_seconds']:.3f}s"
            )
    print("carbon_decoder_tested=False (raw transaction/meta trace required for decoder parity v1)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline canonical state/signal-kernel benchmark v0")
    sub = parser.add_subparsers(dest="command", required=True)

    export_cmd = sub.add_parser("export", help="export persisted market observations to JSONL")
    export_cmd.add_argument("--run-key", required=True)
    export_cmd.add_argument("--out", required=True, type=Path)

    synthetic_cmd = sub.add_parser("synthetic", help="write deterministic synthetic trace")
    synthetic_cmd.add_argument("--out", required=True, type=Path)
    synthetic_cmd.add_argument("--events", type=int, default=10_000)
    synthetic_cmd.add_argument("--seed", type=int, default=68)

    run_cmd = sub.add_parser("run", help="run reference-vs-memory-kernel benchmark")
    run_cmd.add_argument("--trace", required=True, type=Path)
    run_cmd.add_argument("--out", required=True, type=Path)
    run_cmd.add_argument("--scales", default="1,1.25,1.5,2")

    args = parser.parse_args(argv)
    if args.command == "export":
        header = export_persisted_trace(acquisition_run_key=args.run_key, out=args.out)
        print(json.dumps(header, indent=2, sort_keys=True))
        return 0
    if args.command == "synthetic":
        header = generate_synthetic_trace(out=args.out, events=args.events, seed=args.seed)
        print(json.dumps(header, indent=2, sort_keys=True))
        return 0

    _, records = load_trace(args.trace)
    report = run_benchmark(records, scales=_parse_scales(args.scales))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _print_summary(report)
    print(f"report={args.out}")
    return 0 if report["parity"]["mismatches"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
