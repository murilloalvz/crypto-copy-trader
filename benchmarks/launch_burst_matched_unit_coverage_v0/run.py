from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from typing import Any, Iterable

from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
    identities_available_before_v0,
    load_bootstrap_evidence_v0,
)
from benchmarks.market_first_live_smoke_v0.run import _observed_at_from_wall_ns
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


MATCHED_UNIT_COVERAGE_VERSION = "launch_burst_matched_unit_coverage_v0_processed_evidence"
SUPPORTED_LIFECYCLE_EVENTS = frozenset({"pump_create", "pumpswap_create_pool"})
TRADE_EVENTS = frozenset({"pump_trade", "pumpswap_buy", "pumpswap_sell"})


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSON object required at {path}:{line_number}")
        rows.append(row)
    return rows


def _resolve_declared(report_path: Path, declared: object) -> Path:
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("declared artifact path is missing")
    candidate = Path(declared)
    if candidate.exists():
        return candidate
    sibling = report_path.parent / candidate.name
    if sibling.exists():
        return sibling
    raise ValueError(f"declared artifact path not found: {declared}")


def _evidence_file(chunk_dir: Path, basename: str, *, required: bool) -> Path | None:
    plain = chunk_dir / f"{basename}.jsonl"
    compressed = chunk_dir / f"{basename}.jsonl.gz"
    if plain.exists() and compressed.exists():
        raise ValueError(f"ambiguous evidence files for {chunk_dir}/{basename}")
    if plain.exists():
        return plain
    if compressed.exists():
        return compressed
    if required:
        raise ValueError(f"required evidence file missing: {chunk_dir}/{basename}.jsonl[.gz]")
    return None


def _text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_int(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _paired_rows(carbon_path: Path, manifest_path: Path) -> tuple[list[tuple[dict, dict]], list[str]]:
    manifests = {
        str(row["event_key"]): row
        for row in _read_jsonl(manifest_path)
        if isinstance(row.get("event_key"), str)
    }
    paired: list[tuple[dict, dict]] = []
    errors: list[str] = []
    for row in _read_jsonl(carbon_path):
        if row.get("type") != "carbon_canonical_event":
            continue
        event_key = _text(row, "event_key")
        manifest = manifests.get(event_key or "")
        if event_key is None or manifest is None:
            errors.append(f"canonical_event_missing_manifest:{event_key}")
            continue
        wall_ns = manifest.get("first_received_wall_ns")
        if not isinstance(wall_ns, int) or isinstance(wall_ns, bool) or wall_ns <= 0:
            errors.append(f"canonical_event_invalid_receive_clock:{event_key}")
            continue
        paired.append((row, manifest))
    paired.sort(
        key=lambda pair: (
            int(pair[1]["first_received_wall_ns"]),
            str(pair[0].get("event_key", "")),
        )
    )
    return paired, errors


def _decoder_identities(path: Path) -> tuple[PumpSwapPoolIdentityObservation, ...]:
    output: list[PumpSwapPoolIdentityObservation] = []
    for row in _read_jsonl(path):
        if row.get("type") != "pumpswap_pool_identity_decode" or row.get("status") != ADAPTED:
            continue
        output.append(
            PumpSwapPoolIdentityObservation(
                pool=str(row["pool"]),
                base_mint=str(row["base_mint"]),
                quote_mint=str(row["quote_mint"]),
                observed_wall_ns=int(row["observed_wall_ns"]),
                observed_slot=int(row["observed_slot"]),
                evidence_key=str(row["evidence_key"]),
                source=str(row["source"]),
            )
        )
    output.sort(key=lambda item: (item.observed_wall_ns, item.pool, item.evidence_key))
    return tuple(output)


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _percentile(values: Iterable[int | float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Iterable[int | float]) -> dict[str, float | int | None]:
    data = [float(value) for value in values]
    return {
        "count": len(data),
        "min": min(data) if data else None,
        "p50": _percentile(data, 0.50),
        "p90": _percentile(data, 0.90),
        "p95": _percentile(data, 0.95),
        "max": max(data) if data else None,
    }


def _add_identity(
    identities: dict[str, list[PumpSwapPoolIdentityObservation]],
    identity: PumpSwapPoolIdentityObservation,
) -> None:
    bucket = identities.setdefault(identity.pool, [])
    key = (identity.observed_wall_ns, identity.evidence_key)
    if any((item.observed_wall_ns, item.evidence_key) == key for item in bucket):
        return
    bucket.append(identity)
    bucket.sort(key=lambda item: (item.observed_wall_ns, item.observed_slot, item.evidence_key))


def _first_anchor(
    anchors: dict[tuple[str, str], dict[str, Any]],
    *,
    token_mint: str,
    venue: str,
    chain_t0: int,
    observed_t0: int,
    event_key: str,
) -> None:
    key = (token_mint, venue)
    candidate = {
        "token_mint": token_mint,
        "venue": venue,
        "chain_t0": chain_t0,
        "observed_t0": observed_t0,
        "event_key": event_key,
    }
    previous = anchors.get(key)
    if previous is None or (observed_t0, chain_t0, event_key) < (
        previous["observed_t0"],
        previous["chain_t0"],
        previous["event_key"],
    ):
        anchors[key] = candidate


def run_matched_unit_coverage_audit(
    *,
    live_report_path: Path,
    window_seconds: int = 30,
) -> dict[str, Any]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    report_path = Path(live_report_path)
    live = _read_json(report_path)
    run = live.get("run") or {}
    if run.get("status") != "CLOSED":
        raise ValueError("matched-unit coverage requires an authoritative CLOSED live discovery run")
    if live.get("bootstrap_validated") is not True:
        raise ValueError("live discovery bootstrap was not validated")
    discovery_start = int(live.get("discovery_start_wall_ns") or 0)
    discovery_close = int(live.get("discovery_close_wall_ns") or 0)
    if discovery_start <= 0 or discovery_close <= discovery_start:
        raise ValueError("live discovery report has invalid discovery wall-clock bounds")
    acquisition = live.get("acquisition") or {}
    acquisition_ended_wall_ns = int(acquisition.get("ended_wall_ns") or 0)
    if acquisition_ended_wall_ns < discovery_close:
        raise ValueError("live acquisition did not span the entire discovery window")

    artifacts = live.get("artifacts") or {}
    processed_root = _resolve_declared(report_path, artifacts.get("processed_chunks"))
    if not processed_root.is_dir():
        raise ValueError("processed chunks artifact is not a directory")
    bootstrap = live.get("bootstrap") or {}
    bootstrap_report_path = _resolve_declared(report_path, bootstrap.get("report_path"))
    bootstrap_evidence = load_bootstrap_evidence_v0(bootstrap_report_path)

    identities: dict[str, list[PumpSwapPoolIdentityObservation]] = {}
    for identity in bootstrap_evidence.identities:
        _add_identity(identities, identity)

    anchors: dict[tuple[str, str], dict[str, Any]] = {}
    matched_observations: list[Any] = []
    adaptation_statuses: Counter[str] = Counter()
    adaptation_statuses_by_venue: dict[str, Counter[str]] = {
        "pump": Counter(),
        "pumpswap": Counter(),
    }
    paired_event_count = 0
    decoded_trade_count = 0
    pairing_errors: list[str] = []
    dynamic_identity_count = 0
    create_pool_identity_count = 0
    chunk_count = 0

    chunk_dirs = sorted(path for path in processed_root.iterdir() if path.is_dir())
    for chunk_dir in chunk_dirs:
        carbon_path = _evidence_file(chunk_dir, "carbon-canonical", required=True)
        manifest_path = _evidence_file(chunk_dir, "target-manifest", required=True)
        assert carbon_path is not None and manifest_path is not None
        ordered, errors = _paired_rows(carbon_path, manifest_path)
        pairing_errors.extend(f"{chunk_dir.name}:{item}" for item in errors)
        paired_event_count += len(ordered)

        for row, manifest in ordered:
            wall_ns = int(manifest["first_received_wall_ns"])
            if not event_is_inside_discovery_window_v0(
                wall_ns,
                discovery_start_wall_ns=discovery_start,
                discovery_close_wall_ns=discovery_close,
            ):
                continue
            if row.get("status") != "decoded":
                continue
            observed_at = _observed_at_from_wall_ns(wall_ns)
            event_key = str(row.get("event_key") or "")
            event_type = _text(row, "event_type")

            if event_type == "pump_create":
                mint = _text(row, "mint")
                chain_t0 = _nonnegative_int(row, "timestamp")
                if mint is not None and chain_t0 is not None:
                    _first_anchor(
                        anchors,
                        token_mint=mint,
                        venue="pump",
                        chain_t0=chain_t0,
                        observed_t0=observed_at,
                        event_key=event_key,
                    )
                continue

            if event_type == "pumpswap_create_pool":
                pool = _text(row, "pool")
                base_mint = _text(row, "base_mint")
                quote_mint = _text(row, "quote_mint")
                chain_t0 = _nonnegative_int(row, "timestamp")
                slot = _nonnegative_int(row, "slot")
                if None not in (pool, base_mint, quote_mint, chain_t0, slot):
                    identity = PumpSwapPoolIdentityObservation(
                        pool=str(pool),
                        base_mint=str(base_mint),
                        quote_mint=str(quote_mint),
                        observed_wall_ns=wall_ns,
                        observed_slot=int(slot),
                        evidence_key=event_key,
                        source="carbon_pumpswap_create_pool_event_v0",
                    )
                    _add_identity(identities, identity)
                    create_pool_identity_count += 1
                    _first_anchor(
                        anchors,
                        token_mint=str(base_mint),
                        venue="pumpswap",
                        chain_t0=int(chain_t0),
                        observed_t0=observed_at,
                        event_key=event_key,
                    )
                continue

            if event_type == "pump_trade":
                decoded_trade_count += 1
                matched = adapt_carbon_pump_trade_v0(row, observed_at=observed_at)
                venue = "pump"
            elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
                decoded_trade_count += 1
                pool = _text(row, "pool") or ""
                causal = identities_available_before_v0(
                    identities.get(pool, ()),
                    pool=pool,
                    event_wall_ns=wall_ns,
                )
                matched = adapt_carbon_pumpswap_trade_v0(
                    row,
                    observed_at=observed_at,
                    observed_wall_ns=wall_ns,
                    pool_observations=(),
                    pool_identity_observations=causal,
                )
                venue = "pumpswap"
            else:
                continue

            adaptation_statuses[matched.status] += 1
            adaptation_statuses_by_venue[venue][matched.status] += 1
            if matched.status == ADAPTED and matched.observation is not None:
                matched_observations.append(matched.observation)

        dynamic_output = _evidence_file(chunk_dir, "pool-account-output", required=False)
        if dynamic_output is not None:
            for identity in _decoder_identities(dynamic_output):
                _add_identity(identities, identity)
                dynamic_identity_count += 1
        chunk_count += 1

    if pairing_errors:
        raise RuntimeError("processed evidence pairing errors: " + ";".join(pairing_errors[:10]))

    acquisition_ended_at = acquisition_ended_wall_ns // 1_000_000_000
    complete_anchors: list[dict[str, Any]] = []
    right_censored = 0
    for anchor in anchors.values():
        if acquisition_ended_at < int(anchor["observed_t0"]) + window_seconds:
            right_censored += 1
            continue
        complete_anchors.append(anchor)

    per_launch: list[dict[str, Any]] = []
    for anchor in complete_anchors:
        decision_as_of = int(anchor["observed_t0"]) + window_seconds
        chain_end = int(anchor["chain_t0"]) + window_seconds
        rows = [
            item
            for item in matched_observations
            if item.token_mint == anchor["token_mint"]
            and item.venue == anchor["venue"]
            and item.observed_at <= decision_as_of
            and int(anchor["chain_t0"]) <= item.chain_time <= chain_end
        ]
        surface_keys = {
            (item.market_surface_key, item.quote_asset_key, item.reserve_kind)
            for item in rows
        }
        quote_assets = {item.quote_asset_key for item in rows}
        per_launch.append(
            {
                "stratum": (
                    "pump_launch" if anchor["venue"] == "pump" else "pumpswap_liquidity_launch"
                ),
                "matched_unit_event_count": len(rows),
                "has_matched_unit_evidence": bool(rows),
                "surface_count": len(surface_keys),
                "quote_asset_identity_count": len(quote_assets),
            }
        )

    strata: dict[str, dict[str, Any]] = {}
    for stratum in ("pump_launch", "pumpswap_liquidity_launch"):
        rows = [item for item in per_launch if item["stratum"] == stratum]
        available = sum(bool(item["has_matched_unit_evidence"]) for item in rows)
        strata[stratum] = {
            "complete_launch_count": len(rows),
            "launches_with_matched_unit_evidence": available,
            "launch_coverage_pct": _pct(available, len(rows)),
            "matched_unit_event_count_distribution": _distribution(
                int(item["matched_unit_event_count"]) for item in rows
            ),
            "surface_count_distribution": _distribution(
                int(item["surface_count"]) for item in rows
            ),
            "quote_asset_identity_count_distribution": _distribution(
                int(item["quote_asset_identity_count"]) for item in rows
            ),
        }

    adapted_count = int(adaptation_statuses.get(ADAPTED, 0))
    return {
        "type": "launch_burst_matched_unit_coverage_audit",
        "version": MATCHED_UNIT_COVERAGE_VERSION,
        "source_live_report": str(report_path),
        "acquisition_run_key": str(run.get("acquisition_run_key") or ""),
        "window_seconds": window_seconds,
        "source_integrity": {
            "run_status": str(run.get("status")),
            "bootstrap_validated": True,
            "processed_chunk_count": chunk_count,
            "canonical_manifest_paired_event_count": paired_event_count,
            "pairing_error_count": 0,
            "acquisition_spanned_discovery_window": True,
            "bootstrap_identity_count": len(bootstrap_evidence.identities),
            "create_pool_identity_count": create_pool_identity_count,
            "dynamic_identity_count": dynamic_identity_count,
        },
        "launch_sample": {
            "causal_anchor_count": len(anchors),
            "complete_anchor_count": len(complete_anchors),
            "right_censored_count": right_censored,
        },
        "trade_adaptation": {
            "decoded_trade_count": decoded_trade_count,
            "adapted_count": adapted_count,
            "adapted_pct": _pct(adapted_count, decoded_trade_count),
            "statuses": dict(sorted(adaptation_statuses.items())),
            "statuses_by_venue": {
                venue: dict(sorted(counter.items()))
                for venue, counter in adaptation_statuses_by_venue.items()
            },
        },
        "strata": strata,
        "feature_readiness": {
            "native_quote_amount": "AVAILABLE_WHEN_MATCHED_UNIT_ADAPTED",
            "native_quote_reserve": "AVAILABLE_WHEN_MATCHED_UNIT_ADAPTED",
            "quote_asset_identity": "AVAILABLE_WHEN_MATCHED_UNIT_ADAPTED",
            "market_surface_identity": "AVAILABLE_WHEN_MATCHED_UNIT_ADAPTED",
            "dimensionless_flow_over_reserve": "COMPUTABLE_WHEN_MATCHED_UNIT_ADAPTED",
            "usd_price": "NOT_PROVIDED_BY_THIS_AUDIT",
            "usd_notional": "NOT_PROVIDED_BY_THIS_AUDIT",
        },
        "scientific_lock": {
            "coverage_only": True,
            "raw_quote_amount_values_reported": False,
            "raw_quote_reserve_values_reported": False,
            "flow_over_reserve_values_reported": False,
            "economic_outcomes_loaded": False,
            "future_outcomes_reported": False,
            "return_values_reported": False,
            "candidate_thresholds_defined": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outcome-blind Launch Burst matched-unit coverage audit from processed evidence"
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/launch_burst_matched_unit_coverage_v0/report.json"),
    )
    args = parser.parse_args()
    result = run_matched_unit_coverage_audit(
        live_report_path=args.live_report,
        window_seconds=args.window_seconds,
    )
    _write_json(args.output, result)
    print(
        "Launch Burst Matched-Unit Coverage V0 "
        f"run={result['acquisition_run_key']} "
        f"adapted={result['trade_adaptation']['adapted_count']}/"
        f"{result['trade_adaptation']['decoded_trade_count']}"
    )
    print(f"strata={result['strata']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
