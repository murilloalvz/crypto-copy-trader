from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

from src.carbon_protocol_adapter import (
    ADAPTED as PROTOCOL_ADAPTED,
    adapt_carbon_pumpswap_pool_account_identity_v0,
)

VERSION = "helius_pumpswap_lazy_pool_context_replay_v1"
DEFAULT_DELAYS_MS = (50, 100, 250, 500, 1000)
PUMPSWAP_EVENT_TYPES = {"pumpswap_buy", "pumpswap_sell"}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _index_unique(
    rows: Iterable[dict[str, Any]], row_type: str
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        if row.get("type") != row_type:
            continue
        key = row.get("event_key")
        if not isinstance(key, str) or not key:
            continue
        if key in indexed:
            duplicates.append(key)
        indexed[key] = row
    return indexed, tuple(sorted(set(duplicates)))


def _initial_pool_availability(
    rows: Iterable[dict[str, Any]],
) -> tuple[dict[str, int], int, int]:
    """Reuse the production pool-account adapter so replay and live audit cannot drift."""

    availability: dict[str, int] = {}
    invalid = 0
    decoded_rows = 0
    for row in rows:
        if row.get("type") != "carbon_pumpswap_pool_account" or row.get("status") != "decoded":
            continue
        decoded_rows += 1
        adapted = adapt_carbon_pumpswap_pool_account_identity_v0(row)
        if adapted.status != PROTOCOL_ADAPTED or adapted.identity_observation is None:
            invalid += 1
            continue
        observation = adapted.identity_observation
        previous = availability.get(observation.pool)
        if previous is None or observation.observed_wall_ns < previous:
            availability[observation.pool] = observation.observed_wall_ns
    return availability, invalid, decoded_rows


def _ordered_pumpswap_trades(
    *,
    manifest_rows: list[dict[str, Any]],
    carbon_rows: list[dict[str, Any]],
) -> tuple[list[tuple[int, str, str]], dict[str, Any]]:
    manifests, manifest_duplicates = _index_unique(manifest_rows, "wss_target_event_manifest")
    events, carbon_duplicates = _index_unique(carbon_rows, "carbon_canonical_event")

    missing_manifest: list[str] = []
    rejected_manifest: list[str] = []
    invalid_rows: list[str] = []
    ordered: list[tuple[int, str, str]] = []

    for event_key, event in events.items():
        if event.get("status") != "decoded" or event.get("event_type") not in PUMPSWAP_EVENT_TYPES:
            continue
        manifest = manifests.get(event_key)
        if manifest is None:
            missing_manifest.append(event_key)
            continue
        if (
            manifest.get("transaction_succeeded") is not True
            or manifest.get("accepted_for_market_research") is not True
        ):
            rejected_manifest.append(event_key)
            continue
        received_ns = manifest.get("first_received_wall_ns")
        pool = event.get("pool")
        if (
            not isinstance(received_ns, int)
            or isinstance(received_ns, bool)
            or received_ns <= 0
            or not isinstance(pool, str)
            or not pool
        ):
            invalid_rows.append(event_key)
            continue
        ordered.append((received_ns, event_key, pool))

    ordered.sort(key=lambda item: (item[0], item[1]))
    diagnostics = {
        "manifest_duplicate_event_keys": len(manifest_duplicates),
        "carbon_duplicate_event_keys": len(carbon_duplicates),
        "missing_manifest_events": len(missing_manifest),
        "rejected_manifest_events": len(rejected_manifest),
        "invalid_trade_rows": len(invalid_rows),
        "valid_join": not (
            manifest_duplicates
            or carbon_duplicates
            or missing_manifest
            or rejected_manifest
            or invalid_rows
        ),
    }
    return ordered, diagnostics


def simulate_delay(
    trades: list[tuple[int, str, str]],
    *,
    initial_pool_availability: dict[str, int],
    lookup_delay_ms: int,
) -> dict[str, Any]:
    if lookup_delay_ms < 0:
        raise ValueError("lookup_delay_ms must be non-negative")

    delay_ns = lookup_delay_ms * 1_000_000
    pending_ready_ns: dict[str, int] = {}
    lazy_resolved: set[str] = set()
    counts: Counter[str] = Counter()
    unique_pools = {pool for _, _, pool in trades}

    for received_ns, _event_key, pool in trades:
        initial_ready = initial_pool_availability.get(pool)
        if initial_ready is not None and initial_ready <= received_ns:
            counts["initial_cache_hit"] += 1
            continue

        if pool in lazy_resolved:
            counts["lazy_hit"] += 1
            continue

        pending = pending_ready_ns.get(pool)
        if pending is not None and pending <= received_ns:
            lazy_resolved.add(pool)
            counts["lazy_hit"] += 1
            continue

        counts["miss"] += 1
        if pending is None:
            pending_ready_ns[pool] = received_ns + delay_ns
            counts["lookup_requests"] += 1
        else:
            counts["deduped_inflight_miss"] += 1

    total = len(trades)
    adapted = counts["initial_cache_hit"] + counts["lazy_hit"]
    initial_cached_pools_seen = sum(
        1
        for pool in unique_pools
        if pool in initial_pool_availability
        and any(
            event_pool == pool and initial_pool_availability[pool] <= received_ns
            for received_ns, _key, event_pool in trades
        )
    )
    return {
        "lookup_delay_ms": lookup_delay_ms,
        "pumpswap_trade_events": total,
        "unique_observed_pools": len(unique_pools),
        "initial_cached_pools_seen": initial_cached_pools_seen,
        "initial_cache_hit_events": counts["initial_cache_hit"],
        "lazy_hit_events": counts["lazy_hit"],
        "missing_context_events": counts["miss"],
        "lookup_requests": counts["lookup_requests"],
        "deduped_inflight_misses": counts["deduped_inflight_miss"],
        "context_coverage_pct": 0.0 if total == 0 else 100.0 * adapted / total,
        "first_trade_is_never_retroactively_recovered": True,
    }


def run_replay(
    *,
    manifest_path: Path,
    carbon_output_path: Path,
    pool_identities_path: Path | None = None,
    delays_ms: tuple[int, ...] = DEFAULT_DELAYS_MS,
) -> dict[str, Any]:
    if not delays_ms or any(delay < 0 for delay in delays_ms):
        raise ValueError("delays_ms must contain non-negative integers")

    manifest_rows = _jsonl(manifest_path)
    carbon_rows = _jsonl(carbon_output_path)
    identity_rows = _jsonl(pool_identities_path) if pool_identities_path is not None else []

    trades, join = _ordered_pumpswap_trades(
        manifest_rows=manifest_rows,
        carbon_rows=carbon_rows,
    )
    initial_availability, invalid_identities, decoded_identity_rows = _initial_pool_availability(
        identity_rows
    )
    scenarios = [
        simulate_delay(
            trades,
            initial_pool_availability=initial_availability,
            lookup_delay_ms=delay,
        )
        for delay in delays_ms
    ]

    valid = join["valid_join"] and invalid_identities == 0 and len(trades) > 0
    return {
        "type": "helius_pumpswap_lazy_pool_context_replay",
        "version": VERSION,
        "classification": (
            "VALID_COUNTERFACTUAL_LAZY_LOOKUP_REPLAY"
            if valid
            else "INVALID_COUNTERFACTUAL_LAZY_LOOKUP_REPLAY"
        ),
        "valid_replay": valid,
        "counterfactual_not_live_measured": True,
        "chain_complete_coverage_claimed": False,
        "economic_edge_evaluated": False,
        "assumes_lookup_success_and_identity_decode_success": True,
        "decoded_identity_rows": decoded_identity_rows,
        "initial_identity_rows": len(initial_availability),
        "invalid_identity_rows": invalid_identities,
        **join,
        "scenarios": scenarios,
        "notes": [
            "This replay measures only causal context availability, not economic performance.",
            "A pool's first cache-miss trade remains missing; no lookup result is backfilled.",
            "Fixed delay scenarios are counterfactual and do not claim measured live RPC latency.",
            "Lookup success and account decode success are optimistic assumptions in this replay.",
            "Initial pool-account identities are validated by the same production protocol adapter used by the live adapter audit.",
            "Standard WSS remains operational-only and not chain-complete.",
        ],
    }


def _parse_delays(raw: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not values or any(value < 0 for value in values):
        raise ValueError("delays must be comma-separated non-negative integers")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Counterfactual causal replay for PumpSwap lazy pool-context lookup"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--carbon-output", type=Path, required=True)
    parser.add_argument("--pool-identities", type=Path)
    parser.add_argument("--delays-ms", default=",".join(str(x) for x in DEFAULT_DELAYS_MS))
    args = parser.parse_args()

    report = run_replay(
        manifest_path=args.manifest,
        carbon_output_path=args.carbon_output,
        pool_identities_path=args.pool_identities,
        delays_ms=_parse_delays(args.delays_ms),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_replay"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
