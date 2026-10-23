from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any, Iterable

VERSION = "external_market_evidence_comparison_v0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _native_flow(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    per_mint: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (
            row.get("type") != "helius_standard_wss_shadow_adapter_result"
            or row.get("stage") != "matched_unit_flow"
            or row.get("status") != "ADAPTED"
        ):
            continue
        observation = row.get("observation")
        if not isinstance(observation, dict):
            continue
        mint = observation.get("token_mint")
        if not isinstance(mint, str) or not mint:
            continue
        entry = per_mint.setdefault(
            mint,
            {
                "adapted_events": 0,
                "buys": 0,
                "sells": 0,
                "venues": Counter(),
                "first_observed_at": None,
                "last_observed_at": None,
            },
        )
        entry["adapted_events"] += 1
        side = observation.get("side")
        if side in {"buy", "sell"}:
            entry[f"{side}s"] += 1
        venue = observation.get("venue")
        if isinstance(venue, str) and venue:
            entry["venues"][venue] += 1
        observed_at = observation.get("observed_at")
        if isinstance(observed_at, int) and not isinstance(observed_at, bool):
            current_first = entry["first_observed_at"]
            current_last = entry["last_observed_at"]
            entry["first_observed_at"] = (
                observed_at if current_first is None else min(current_first, observed_at)
            )
            entry["last_observed_at"] = (
                observed_at if current_last is None else max(current_last, observed_at)
            )
    for entry in per_mint.values():
        entry["venues"] = dict(sorted(entry["venues"].items()))
    return per_mint


def _jupiter_by_mint(rows: Iterable[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    result: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        if row.get("type") != "jupiter_token_intelligence_observation":
            continue
        mint = row.get("mint")
        payload = row.get("payload")
        if not isinstance(mint, str) or not mint or not isinstance(payload, dict):
            continue
        if mint in result:
            duplicates += 1
            continue
        result[mint] = row
    return result, duplicates


def _dex_by_mint(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("type") != "dexscreener_market_evidence_observation":
            continue
        matched = row.get("matched_requested_mints")
        payload = row.get("payload")
        if not isinstance(matched, list) or not isinstance(payload, dict):
            continue
        for mint in matched:
            if isinstance(mint, str) and mint:
                result[mint].append(row)
    return dict(result)


def _deepest_dex_pair(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def key(row: dict[str, Any]) -> tuple[int, float, str]:
        payload = row.get("payload") or {}
        liquidity = payload.get("liquidity") if isinstance(payload, dict) else None
        usd = _finite_number(liquidity.get("usd")) if isinstance(liquidity, dict) else None
        pair_address = str(row.get("pair_address") or "")
        return (1 if usd is not None else 0, usd if usd is not None else -1.0, pair_address)

    return max(rows, key=key)


def compare_external_market_evidence(
    *,
    adapter_path: Path,
    jupiter_path: Path,
    dexscreener_path: Path,
    per_mint_out: Path,
) -> dict[str, Any]:
    native = _native_flow(_jsonl(adapter_path))
    jupiter, jupiter_duplicates = _jupiter_by_mint(_jsonl(jupiter_path))
    dex = _dex_by_mint(_jsonl(dexscreener_path))

    native_mints = set(native)
    jupiter_mints = native_mints & set(jupiter)
    dex_mints = native_mints & set(dex)
    both = jupiter_mints & dex_mints
    neither = native_mints - (jupiter_mints | dex_mints)

    output_rows: list[dict[str, Any]] = []
    for mint in sorted(native_mints):
        jup_row = jupiter.get(mint)
        jup_payload = jup_row.get("payload") if jup_row is not None else None
        dex_rows = dex.get(mint, [])
        deepest = _deepest_dex_pair(dex_rows)
        deepest_payload = deepest.get("payload") if deepest is not None else None
        output_rows.append(
            {
                "type": "external_market_evidence_comparison_row",
                "version": VERSION,
                "mint": mint,
                "native": native[mint],
                "jupiter": (
                    {
                        "available": True,
                        "received_wall_ns": jup_row.get("received_wall_ns"),
                        "organicScore": jup_payload.get("organicScore"),
                        "organicScoreLabel": jup_payload.get("organicScoreLabel"),
                        "holderCount": jup_payload.get("holderCount"),
                        "liquidity": jup_payload.get("liquidity"),
                        "usdPrice": jup_payload.get("usdPrice"),
                        "mcap": jup_payload.get("mcap"),
                        "fdv": jup_payload.get("fdv"),
                        "audit": jup_payload.get("audit"),
                        "firstPool": jup_payload.get("firstPool"),
                        "stats5m": jup_payload.get("stats5m"),
                    }
                    if isinstance(jup_payload, dict)
                    else {"available": False}
                ),
                "dexscreener": (
                    {
                        "available": True,
                        "pair_count": len(dex_rows),
                        "deepest_pair_address": deepest.get("pair_address"),
                        "received_wall_ns": deepest.get("received_wall_ns"),
                        "liquidity": deepest_payload.get("liquidity"),
                        "priceUsd": deepest_payload.get("priceUsd"),
                        "txns": deepest_payload.get("txns"),
                        "volume": deepest_payload.get("volume"),
                        "priceChange": deepest_payload.get("priceChange"),
                        "pairCreatedAt": deepest_payload.get("pairCreatedAt"),
                        "boosts": deepest_payload.get("boosts"),
                    }
                    if isinstance(deepest_payload, dict)
                    else {"available": False, "pair_count": 0}
                ),
                "causal_for_source_shadow": False,
                "economic_edge_evaluated": False,
            }
        )

    _write_jsonl(per_mint_out, output_rows)
    total = len(native_mints)

    def pct(value: int) -> float:
        return 0.0 if total == 0 else 100.0 * value / total

    return {
        "type": "external_market_evidence_comparison_report",
        "version": VERSION,
        "native_adapted_mints": total,
        "jupiter_exact_mints": len(jupiter_mints),
        "dexscreener_exact_mints": len(dex_mints),
        "both_external_sources": len(both),
        "jupiter_only": len(jupiter_mints - dex_mints),
        "dexscreener_only": len(dex_mints - jupiter_mints),
        "neither_external_source": len(neither),
        "jupiter_coverage_pct": pct(len(jupiter_mints)),
        "dexscreener_coverage_pct": pct(len(dex_mints)),
        "both_coverage_pct": pct(len(both)),
        "jupiter_duplicate_mint_rows_rejected": jupiter_duplicates,
        "valid_comparison": total > 0 and jupiter_duplicates == 0,
        "causal_for_source_shadow": False,
        "economic_edge_evaluated": False,
        "score_or_recommendation_created": False,
        "notes": [
            "This compares evidence availability/coverage only; it is not a predictive evaluation.",
            "Jupiter provider-derived scores and DexScreener pair metrics remain provider-native.",
            "The deepest DexScreener pair is selected transparently by reported USD liquidity; pair metrics are not summed across venues.",
            "All external observations are post-shadow unless collected prospectively in a future episode pipeline.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare native adapted mints with Jupiter and DexScreener evidence coverage"
    )
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--jupiter", type=Path, required=True)
    parser.add_argument("--dexscreener", type=Path, required=True)
    parser.add_argument("--per-mint-out", type=Path, required=True)
    args = parser.parse_args()

    report = compare_external_market_evidence(
        adapter_path=args.adapter_output,
        jupiter_path=args.jupiter,
        dexscreener_path=args.dexscreener,
        per_mint_out=args.per_mint_out,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_comparison"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
