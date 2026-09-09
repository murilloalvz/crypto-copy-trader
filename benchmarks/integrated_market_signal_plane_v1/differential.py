from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random

from benchmarks.commodity_signal_plane_v0.benchmark import ReferenceRadarState, TraceRecord
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import IndexedWindowRadarState
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation

VERSION = "indexed_market_signal_plane_differential_v1"


def _snapshot(trigger) -> dict | None:
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


def generate_long_horizon_trace(*, seed: int, trades: int) -> tuple[TraceRecord, ...]:
    if trades <= 0:
        raise ValueError("trades must be positive")
    rng = random.Random(seed)
    tokens = [f"DIF-{i:02d}" for i in range(8)]
    base = 2_000_000 + seed * 10_000
    records: list[TraceRecord] = []
    sequence = 0

    # Only some Pump-like markets have lifecycle evidence; others intentionally remain missing.
    for index, token in enumerate(tokens):
        if index % 4 != 0:
            continue
        observed = base
        started = base - (20 + 11 * index)
        records.append(
            TraceRecord(
                sequence=sequence,
                arrival_offset_ns=sequence * 1_000,
                kind="lifecycle",
                event_key=f"life:{seed}:{token}",
                source_provider="differential",
                lifecycle=MarketLifecycleObservation(
                    token_mint=token,
                    market_started_at=started,
                    observed_at=observed,
                    venue="pump_bonding_curve",
                ),
            )
        )
        sequence += 1

    # Five trades per observed second -> 1,800 trades spans 360 seconds and forces pruning.
    for index in range(trades):
        observed_at = base + index // 5
        if rng.random() < 0.50:
            token = tokens[0]
        else:
            token = tokens[rng.randrange(len(tokens))]

        lag = rng.choices(
            population=(0, 1, 5, 31, 120, 301, 420),
            weights=(50, 18, 10, 8, 7, 5, 2),
            k=1,
        )[0]
        chain_time = max(0, observed_at - lag)
        side = "buy" if rng.random() < 0.62 else "sell"
        venue = "pump_bonding_curve" if int(token[-2:]) % 2 == 0 else "pumpswap"

        wallet = None if rng.random() < 0.18 else f"W{rng.randrange(40):02d}"
        transaction = None if rng.random() < 0.22 else f"TX{seed}-{index // rng.choice((1, 1, 2, 3))}"
        notional = None if rng.random() < 0.27 else round(1.0 + rng.random() * 40.0, 6)
        price = None if rng.random() < 0.31 else round(0.01 + rng.random() * 3.0, 9)

        records.append(
            TraceRecord(
                sequence=sequence,
                arrival_offset_ns=(observed_at - base) * 1_000_000_000 + (index % 5) * 10_000,
                kind="trade",
                event_key=f"trade:{seed}:{index}",
                source_provider="differential",
                trade=MarketTradeObservation(
                    token_mint=token,
                    side=side,
                    chain_time=chain_time,
                    observed_at=observed_at,
                    wallet_address=wallet,
                    notional_usd=notional,
                    price_usd=price,
                    venue=venue,
                    transaction_key=transaction,
                ),
            )
        )
        sequence += 1

    return tuple(records)


def run_differential(*, seeds: tuple[int, ...], trades_per_seed: int) -> dict:
    total_records = 0
    total_decisions = 0
    exact = 0
    mismatches: list[dict] = []
    total_late_inserts = 0
    total_compactions = 0

    for seed in seeds:
        reference = ReferenceRadarState()
        indexed = IndexedWindowRadarState()
        records = generate_long_horizon_trace(seed=seed, trades=trades_per_seed)
        total_records += len(records)

        for record in records:
            expected = reference.ingest(record)
            actual = indexed.ingest(record)
            if record.kind != "trade":
                continue
            total_decisions += 1
            e = _snapshot(expected)
            a = _snapshot(actual)
            if e == a:
                exact += 1
            elif len(mismatches) < 50:
                mismatches.append(
                    {
                        "seed": seed,
                        "sequence": record.sequence,
                        "expected": e,
                        "actual": a,
                    }
                )

        total_late_inserts += indexed.late_chain_time_inserts
        total_compactions += indexed.compactions

    parity_pct = 100.0 if total_decisions == 0 else 100.0 * exact / total_decisions
    checks = {
        "parity_100": exact == total_decisions and not mismatches,
        "late_insert_path_exercised": total_late_inserts > 0,
        "compaction_path_exercised": total_compactions > 0,
    }
    classification = (
        "PASS_INDEXED_KERNEL_LONG_HORIZON_DIFFERENTIAL_V1"
        if all(checks.values())
        else "FAIL_INDEXED_KERNEL_LONG_HORIZON_DIFFERENTIAL_V1"
    )
    return {
        "type": "indexed_kernel_differential_report",
        "version": VERSION,
        "seeds": list(seeds),
        "trades_per_seed": trades_per_seed,
        "records": total_records,
        "trade_decisions": total_decisions,
        "exact": exact,
        "parity_pct": parity_pct,
        "late_chain_time_inserts": total_late_inserts,
        "compactions": total_compactions,
        "first_mismatches": mismatches,
        "checks": checks,
        "classification": classification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexed kernel long-horizon differential v1")
    parser.add_argument("--seeds", default="11,29,68,97")
    parser.add_argument("--trades-per-seed", type=int, default=1800)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/integrated_market_signal_plane_v1/differential-report.json"),
    )
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.seeds.split(",") if item.strip())
    if not seeds or args.trades_per_seed <= 0:
        raise SystemExit("seeds and trades-per-seed must be non-empty/positive")
    report = run_differential(seeds=seeds, trades_per_seed=args.trades_per_seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["classification"] != "PASS_INDEXED_KERNEL_LONG_HORIZON_DIFFERENTIAL_V1":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
