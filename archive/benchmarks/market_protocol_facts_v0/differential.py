"""Differential causal-invariance benchmark for market_protocol_facts_v0."""

import argparse
import json
import random
from dataclasses import asdict

from src.market_protocol_facts import (
    PumpCurveStateObservation,
    PumpMigrationEvidence,
    PumpSwapPoolObservation,
    build_market_protocol_facts_v0,
)


def _pump(rng: random.Random, i: int, mint: str) -> PumpCurveStateObservation:
    chain_time = 100 + i
    lag = rng.choice((0, 1, 2, 5, 31, 120))
    complete = True if i >= 80 else False
    real_tokens = max(0, 1_000_000 - i * 12_500)
    return PumpCurveStateObservation(
        token_mint=mint,
        chain_time=chain_time,
        observed_at=chain_time + lag,
        evidence_key=f"pump:{mint}:{i}",
        source="synthetic_protocol_differential",
        complete=complete,
        quote_mint="SOL",
        virtual_token_reserves=2_000_000 - i * 10_000,
        virtual_quote_reserves=100_000 + i * 5_000,
        real_token_reserves=real_tokens,
        real_quote_reserves=i * 5_000,
        token_total_supply=2_000_000,
    )


def _swap(rng: random.Random, i: int, mint: str) -> PumpSwapPoolObservation:
    chain_time = 210 + i
    lag = rng.choice((0, 1, 3, 35))
    virtual = None if i % 7 == 0 else (i % 5) * 10
    return PumpSwapPoolObservation(
        token_mint=mint,
        pool=f"POOL_{mint}",
        chain_time=chain_time,
        observed_at=chain_time + lag,
        evidence_key=f"swap:{mint}:{i}",
        source="synthetic_protocol_differential",
        base_mint=mint,
        quote_mint="SOL",
        pool_index=0,
        pool_base_token_reserves=max(0, 900_000 - i * 3_000),
        pool_quote_token_reserves=300_000 + i * 2_000,
        virtual_quote_reserves=virtual,
    )


def run(seed: int, snapshots: int) -> dict:
    rng = random.Random(seed)
    mint = "MINT_A"
    other = "MINT_B"
    pump_rows = [_pump(rng, i, mint) for i in range(100)]
    pump_rows += [_pump(rng, i, other) for i in range(25)]
    swap_rows = [_swap(rng, i, mint) for i in range(40)]
    swap_rows += [_swap(rng, i, other) for i in range(10)]
    migration_rows = [
        PumpMigrationEvidence(
            token_mint=mint,
            pool="POOL_MINT_A",
            pool_index=0,
            chain_time=225,
            observed_at=235,
            evidence_key="migration:MINT_A:canonical",
            source="synthetic_protocol_differential",
            evidence_kind="pump_migrate_instruction",
        ),
        PumpMigrationEvidence(
            token_mint=other,
            pool="POOL_MINT_B",
            pool_index=0,
            chain_time=220,
            observed_at=220,
            evidence_key="migration:MINT_B:noise",
            source="synthetic_protocol_differential",
            evidence_kind="pump_migrate_instruction",
        ),
    ]

    all_rows = sorted(
        [*pump_rows, *swap_rows, *migration_rows],
        key=lambda row: (row.observed_at, row.chain_time, row.evidence_key),
    )

    checked = 0
    mismatches = []
    lifecycle_counts: dict[str, int] = {}
    missing_virtual_snapshots = 0

    low = 100
    high = max(row.observed_at for row in all_rows) + 1
    for _ in range(snapshots):
        as_of = rng.randint(low, high)
        causal_pump = tuple(row for row in pump_rows if row.observed_at <= as_of)
        causal_swap = tuple(row for row in swap_rows if row.observed_at <= as_of)
        causal_migration = tuple(row for row in migration_rows if row.observed_at <= as_of)

        baseline = build_market_protocol_facts_v0(
            token_mint=mint,
            as_of=as_of,
            pump_curve_observations=causal_pump,
            pumpswap_pool_observations=causal_swap,
            migration_evidence=causal_migration,
        )
        future_appended = build_market_protocol_facts_v0(
            token_mint=mint,
            as_of=as_of,
            pump_curve_observations=pump_rows,
            pumpswap_pool_observations=swap_rows,
            migration_evidence=migration_rows,
        )

        checked += 1
        lifecycle_counts[baseline.lifecycle_label] = (
            lifecycle_counts.get(baseline.lifecycle_label, 0) + 1
        )
        if "pumpswap_virtual_quote_reserves_missing" in baseline.data_quality_flags:
            missing_virtual_snapshots += 1
        if baseline != future_appended:
            mismatches.append(
                {
                    "as_of": as_of,
                    "baseline": asdict(baseline),
                    "future_appended": asdict(future_appended),
                }
            )
            if len(mismatches) >= 5:
                break

    valid = checked == snapshots and not mismatches
    return {
        "type": "market_protocol_facts_v0_differential",
        "seed": seed,
        "snapshots_requested": snapshots,
        "snapshots_checked": checked,
        "exact_future_append_invariance": checked - len(mismatches),
        "mismatch_count": len(mismatches),
        "lifecycle_counts": lifecycle_counts,
        "missing_virtual_snapshots": missing_virtual_snapshots,
        "classification": (
            "PASS_MARKET_PROTOCOL_FACTS_V0_DIFFERENTIAL"
            if valid
            else "FAIL_MARKET_PROTOCOL_FACTS_V0_DIFFERENTIAL"
        ),
        "mismatch_examples": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--snapshots", type=int, default=5000)
    args = parser.parse_args()
    result = run(args.seed, args.snapshots)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["mismatch_count"] == 0 and result["snapshots_checked"] == args.snapshots else 1


if __name__ == "__main__":
    raise SystemExit(main())
