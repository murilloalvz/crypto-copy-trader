from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
from typing import Any, Iterable

from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
    identities_available_before_v0,
    load_bootstrap_evidence_v0,
)
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


SHADOW_VERSION = "launch_burst_shadow_v0_evidence_only_multi_horizon"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_SHADOW_V0"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_SHADOW_V0"
DEFAULT_HORIZONS_SECONDS = (5, 10, 30, 60)
SUPPORTED_VENUES = {"pump", "pumpswap"}


@dataclass(frozen=True)
class AdaptedEnvelope:
    token_mint: str
    venue: str
    side: str
    chain_time: int
    observed_wall_ns: int
    event_key: str
    market_surface_key: str
    quote_asset_key: str
    quote_amount_raw: int
    quote_reserve_raw: int
    reserve_kind: str
    wallet_key: str | None
    transaction_key: str | None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
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
    paired.sort(key=lambda pair: (int(pair[1]["first_received_wall_ns"]), str(pair[0]["event_key"])))
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
    return tuple(sorted(output, key=lambda item: (item.observed_wall_ns, item.pool, item.evidence_key)))


def _add_identity(
    identities: dict[str, list[PumpSwapPoolIdentityObservation]],
    identity: PumpSwapPoolIdentityObservation,
) -> None:
    bucket = identities.setdefault(identity.pool, [])
    fingerprint = (identity.observed_wall_ns, identity.evidence_key)
    if any((item.observed_wall_ns, item.evidence_key) == fingerprint for item in bucket):
        return
    bucket.append(identity)
    bucket.sort(key=lambda item: (item.observed_wall_ns, item.observed_slot, item.evidence_key))


def _first_text(row: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = _text(row, name)
        if value is not None:
            return value
    return None


def _first_anchor(
    anchors: dict[tuple[str, str], dict[str, Any]],
    *,
    token_mint: str,
    venue: str,
    chain_t0: int,
    observed_wall_ns: int,
    event_key: str,
) -> None:
    key = (token_mint, venue)
    candidate = {
        "token_mint": token_mint,
        "venue": venue,
        "stratum": "pump_launch" if venue == "pump" else "pumpswap_liquidity_launch",
        "event_key": event_key,
        "chain_t0": chain_t0,
        "observed_t0": observed_wall_ns // 1_000_000_000,
        "observed_wall_ns": observed_wall_ns,
    }
    previous = anchors.get(key)
    if previous is None or (observed_wall_ns, event_key) < (
        int(previous["observed_wall_ns"]), str(previous["event_key"])
    ):
        anchors[key] = candidate


def _envelope(result: Any, row: dict[str, Any], wall_ns: int) -> AdaptedEnvelope | None:
    if result.status != ADAPTED or result.observation is None:
        return None
    obs = result.observation
    return AdaptedEnvelope(
        token_mint=str(obs.token_mint),
        venue=str(obs.venue),
        side=str(obs.side),
        chain_time=int(obs.chain_time),
        observed_wall_ns=wall_ns,
        event_key=str(obs.evidence_key),
        market_surface_key=str(obs.market_surface_key),
        quote_asset_key=str(obs.quote_asset_key),
        quote_amount_raw=int(obs.quote_amount_raw),
        quote_reserve_raw=int(obs.quote_reserve_raw),
        reserve_kind=str(obs.reserve_kind),
        wallet_key=_first_text(row, ("wallet_address", "user", "user_address", "signer")),
        transaction_key=_first_text(
            row,
            ("transaction_key", "transaction_signature", "signature", "tx_signature"),
        ),
    )


def _ratio_signed(row: AdaptedEnvelope) -> float:
    magnitude = float(row.quote_amount_raw) / float(row.quote_reserve_raw)
    return magnitude if row.side == "buy" else -magnitude


def _feature_snapshot(rows: list[AdaptedEnvelope], *, anchor_wall_ns: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: (item.observed_wall_ns, item.event_key))
    buys = sum(item.side == "buy" for item in ordered)
    sells = sum(item.side == "sell" for item in ordered)
    total = len(ordered)
    quote_assets = {item.quote_asset_key for item in ordered}
    surfaces = {
        (item.market_surface_key, item.quote_asset_key, item.reserve_kind)
        for item in ordered
    }
    wallets = {item.wallet_key for item in ordered if item.wallet_key is not None}
    txs = {item.transaction_key for item in ordered if item.transaction_key is not None}
    signed_ratio = sum(_ratio_signed(item) for item in ordered)
    gross_ratio = sum(abs(_ratio_signed(item)) for item in ordered)

    delays_ms = [max(0.0, (item.observed_wall_ns - anchor_wall_ns) / 1_000_000.0) for item in ordered]
    time_to_n_ms = {
        str(n): (delays_ms[n - 1] if len(delays_ms) >= n else None)
        for n in (1, 3, 5, 10)
    }

    signed_raw: int | None = None
    gross_raw: int | None = None
    if len(quote_assets) == 1:
        signed_raw = sum(item.quote_amount_raw if item.side == "buy" else -item.quote_amount_raw for item in ordered)
        gross_raw = sum(item.quote_amount_raw for item in ordered)

    reserve_delta_fraction: float | None = None
    if len(surfaces) == 1 and ordered:
        first_reserve = ordered[0].quote_reserve_raw
        last_reserve = ordered[-1].quote_reserve_raw
        if first_reserve > 0:
            reserve_delta_fraction = (float(last_reserve) - float(first_reserve)) / float(first_reserve)

    return {
        "event_count": total,
        "buy_count": buys,
        "sell_count": sells,
        "buy_sell_count_imbalance": ((buys - sells) / total) if total else None,
        "signed_flow_over_event_reserve": signed_ratio,
        "gross_turnover_over_event_reserve": gross_ratio,
        "signed_quote_amount_raw": signed_raw,
        "gross_quote_amount_raw": gross_raw,
        "raw_quote_amount_aggregation_valid": len(quote_assets) == 1,
        "quote_asset_identity_count": len(quote_assets),
        "market_surface_count": len(surfaces),
        "unique_wallet_count": len(wallets),
        "wallet_identity_coverage_pct": (100.0 * sum(item.wallet_key is not None for item in ordered) / total) if total else None,
        "unique_transaction_count": len(txs),
        "transaction_identity_coverage_pct": (100.0 * sum(item.transaction_key is not None for item in ordered) / total) if total else None,
        "first_trade_delay_ms": delays_ms[0] if delays_ms else None,
        "time_to_n_events_ms": time_to_n_ms,
        "reserve_delta_fraction": reserve_delta_fraction,
    }


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _assert_output_isolated(output: Path, protected_paths: Iterable[Path]) -> None:
    out = output.resolve()
    for protected in protected_paths:
        source = protected.resolve()
        if out == source or (source.is_dir() and source in out.parents):
            raise ValueError(f"output path overlaps read-only source evidence: {output} vs {protected}")


def _load_candidate_parity(path: Path | None, *, acquisition_run_key: str) -> dict[str, Any]:
    if path is None:
        return {
            "mode": "EVIDENCE_ONLY_ANCHOR_LOCK",
            "full_db_processed_parity_provided": False,
            "parity_pass": None,
        }
    payload = _read_json(path)
    expected = "PASS_LAUNCH_BURST_CANDIDATE_PARITY_V0"
    if payload.get("classification") != expected or payload.get("exact_match") is not True:
        raise ValueError("candidate parity report is not an exact PASS")
    if str(payload.get("acquisition_run_key") or "") != acquisition_run_key:
        raise ValueError("candidate parity run key does not match live report")
    return {
        "mode": "DB_PROCESSED_EXACT_PARITY_LOCKED",
        "full_db_processed_parity_provided": True,
        "parity_pass": True,
        "source_report": str(path),
        "exact_match_count": int(payload.get("exact_match_count") or 0),
    }


def run_shadow_v0(
    *,
    live_report_path: Path,
    horizons_seconds: tuple[int, ...] = DEFAULT_HORIZONS_SECONDS,
    candidate_parity_report: Path | None = None,
) -> dict[str, Any]:
    horizons = tuple(sorted(set(int(value) for value in horizons_seconds)))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons_seconds must contain positive integers")

    report_path = Path(live_report_path)
    live = _read_json(report_path)
    run = live.get("run") or {}
    if run.get("status") != "CLOSED":
        raise ValueError("shadow replay requires run.status=CLOSED; never read an active V68 run")
    if live.get("valid_live_discovery") is not True:
        raise ValueError("shadow replay requires valid_live_discovery=True")
    if live.get("bootstrap_validated") is not True:
        raise ValueError("shadow replay requires bootstrap_validated=True")
    acquisition_run_key = str(run.get("acquisition_run_key") or "").strip()
    if not acquisition_run_key:
        raise ValueError("live report has no acquisition_run_key")

    discovery_start = int(live.get("discovery_start_wall_ns") or 0)
    discovery_close = int(live.get("discovery_close_wall_ns") or 0)
    acquisition_end = int((live.get("acquisition") or {}).get("ended_wall_ns") or 0)
    if discovery_start <= 0 or discovery_close <= discovery_start:
        raise ValueError("invalid discovery bounds")
    if acquisition_end < discovery_close:
        raise ValueError("acquisition did not span discovery window")

    artifacts = live.get("artifacts") or {}
    processed_root = _resolve_declared(report_path, artifacts.get("processed_chunks"))
    if not processed_root.is_dir():
        raise ValueError("processed_chunks is not a directory")
    bootstrap_report = _resolve_declared(report_path, (live.get("bootstrap") or {}).get("report_path"))
    bootstrap_evidence = load_bootstrap_evidence_v0(bootstrap_report)
    candidate_correctness = _load_candidate_parity(
        candidate_parity_report,
        acquisition_run_key=acquisition_run_key,
    )

    identities: dict[str, list[PumpSwapPoolIdentityObservation]] = {}
    for identity in bootstrap_evidence.identities:
        _add_identity(identities, identity)

    anchors: dict[tuple[str, str], dict[str, Any]] = {}
    pool_launches: dict[str, tuple[str, int]] = {}
    adapted: list[AdaptedEnvelope] = []
    statuses: Counter[str] = Counter()
    statuses_by_venue: dict[str, Counter[str]] = {"pump": Counter(), "pumpswap": Counter()}
    candidate_trade_statuses: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    pairing_errors: list[str] = []
    decoded_trade_count = 0
    dynamic_identity_count = 0
    chunk_count = 0
    no_target_event_chunk_count = 0

    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        carbon_path = _evidence_file(chunk_dir, "carbon-canonical", required=False)
        if carbon_path is None:
            chunk_report = chunk_dir / "chunk-report.json"
            if not chunk_report.exists() or _read_json(chunk_report).get("status") != "NO_TARGET_EVENTS":
                raise ValueError(f"missing carbon evidence not justified by NO_TARGET_EVENTS: {chunk_dir}")
            no_target_event_chunk_count += 1
            chunk_count += 1
            continue

        manifest_path = _evidence_file(chunk_dir, "target-manifest", required=True)
        assert manifest_path is not None
        ordered, errors = _paired_rows(carbon_path, manifest_path)
        pairing_errors.extend(f"{chunk_dir.name}:{error}" for error in errors)

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
            event_type = _text(row, "event_type")
            event_key = _text(row, "event_key") or ""
            observed_at = wall_ns // 1_000_000_000

            if event_type == "pump_create":
                mint = _text(row, "mint")
                chain_t0 = _nonnegative_int(row, "timestamp")
                if mint is not None and chain_t0 is not None:
                    _first_anchor(
                        anchors,
                        token_mint=mint,
                        venue="pump",
                        chain_t0=chain_t0,
                        observed_wall_ns=wall_ns,
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
                    pool_launches[str(pool)] = (str(base_mint), wall_ns)
                    _first_anchor(
                        anchors,
                        token_mint=str(base_mint),
                        venue="pumpswap",
                        chain_t0=int(chain_t0),
                        observed_wall_ns=wall_ns,
                        event_key=event_key,
                    )
                continue

            result = None
            venue = None
            hint_key: tuple[str, str] | None = None
            if event_type == "pump_trade":
                decoded_trade_count += 1
                venue = "pump"
                mint = _text(row, "mint")
                if mint is not None:
                    hint_key = (mint, venue)
                result = adapt_carbon_pump_trade_v0(row, observed_at=observed_at)
            elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
                decoded_trade_count += 1
                venue = "pumpswap"
                pool = _text(row, "pool") or ""
                launch_hint = pool_launches.get(pool)
                if launch_hint is not None and launch_hint[1] <= wall_ns:
                    hint_key = (launch_hint[0], venue)
                causal = identities_available_before_v0(
                    identities.get(pool, ()),
                    pool=pool,
                    event_wall_ns=wall_ns,
                )
                result = adapt_carbon_pumpswap_trade_v0(
                    row,
                    observed_at=observed_at,
                    observed_wall_ns=wall_ns,
                    pool_observations=(),
                    pool_identity_observations=causal,
                )
            if result is None or venue is None:
                continue

            statuses[result.status] += 1
            statuses_by_venue[venue][result.status] += 1
            env = _envelope(result, row, wall_ns)
            if env is not None:
                adapted.append(env)
                hint_key = (env.token_mint, env.venue)
            if hint_key is not None:
                candidate_trade_statuses[hint_key][result.status] += 1

        dynamic_output = _evidence_file(chunk_dir, "pool-account-output", required=False)
        if dynamic_output is not None:
            for identity in _decoder_identities(dynamic_output):
                _add_identity(identities, identity)
                dynamic_identity_count += 1
        chunk_count += 1

    if pairing_errors:
        raise RuntimeError("processed evidence pairing errors: " + ";".join(pairing_errors[:10]))

    per_launch: list[dict[str, Any]] = []
    right_censored_by_horizon = {str(horizon): 0 for horizon in horizons}
    for key, anchor in sorted(
        anchors.items(), key=lambda item: (int(item[1]["observed_wall_ns"]), item[0][0], item[0][1])
    ):
        horizon_features: dict[str, Any] = {}
        for horizon in horizons:
            cutoff_wall_ns = int(anchor["observed_wall_ns"]) + horizon * 1_000_000_000
            if acquisition_end < cutoff_wall_ns:
                right_censored_by_horizon[str(horizon)] += 1
                horizon_features[str(horizon)] = {"complete": False, "features": None}
                continue
            chain_end = int(anchor["chain_t0"]) + horizon
            rows = [
                item
                for item in adapted
                if item.token_mint == anchor["token_mint"]
                and item.venue == anchor["venue"]
                and int(anchor["observed_wall_ns"]) <= item.observed_wall_ns <= cutoff_wall_ns
                and int(anchor["chain_t0"]) <= item.chain_time <= chain_end
            ]
            horizon_features[str(horizon)] = {
                "complete": True,
                "features": _feature_snapshot(rows, anchor_wall_ns=int(anchor["observed_wall_ns"])),
            }

        status_counter = candidate_trade_statuses.get(key, Counter())
        per_launch.append(
            {
                **anchor,
                "trade_adaptation_statuses": dict(sorted(status_counter.items())),
                "horizons": horizon_features,
            }
        )

    strata: dict[str, Any] = {}
    max_horizon = str(max(horizons))
    for stratum in ("pump_launch", "pumpswap_liquidity_launch"):
        rows = [item for item in per_launch if item["stratum"] == stratum]
        complete = [item for item in rows if item["horizons"][max_horizon]["complete"]]
        with_flow = [
            item for item in complete
            if int(item["horizons"][max_horizon]["features"]["event_count"]) > 0
        ]
        strata[stratum] = {
            "anchor_count": len(rows),
            f"complete_{max_horizon}s_count": len(complete),
            f"with_adapted_flow_{max_horizon}s_count": len(with_flow),
            f"adapted_flow_coverage_{max_horizon}s_pct": _pct(len(with_flow), len(complete)),
        }

    gates = {
        "source_run_closed": True,
        "source_valid_live_discovery": True,
        "bootstrap_validated": True,
        "pairing_errors_zero": True,
        "anchors_present": bool(anchors),
        "candidate_parity_not_failed": candidate_correctness.get("parity_pass") is not False,
        "network_calls_zero_by_design": True,
        "database_reads_zero_by_design": True,
        "database_writes_zero_by_design": True,
    }
    passed = all(gates.values())
    return {
        "type": "launch_burst_shadow",
        "version": SHADOW_VERSION,
        "classification": PASS_CLASSIFICATION if passed else FAIL_CLASSIFICATION,
        "acquisition_run_key": acquisition_run_key,
        "horizons_seconds": list(horizons),
        "safety": {
            "source_mode": "FINALIZED_PROCESSED_EVIDENCE_READ_ONLY",
            "network_calls": 0,
            "database_reads": 0,
            "database_writes": 0,
            "safe_to_run_parallel_with_live_v68": True,
            "requires_source_run_closed": True,
        },
        "gates": gates,
        "candidate_correctness": candidate_correctness,
        "source_integrity": {
            "processed_chunk_count": chunk_count,
            "no_target_event_chunk_count": no_target_event_chunk_count,
            "bootstrap_identity_count": len(bootstrap_evidence.identities),
            "dynamic_identity_count": dynamic_identity_count,
            "pairing_error_count": 0,
        },
        "feature_coverage": {
            "decoded_trade_count": decoded_trade_count,
            "adapted_trade_count": len(adapted),
            "adapted_pct": _pct(len(adapted), decoded_trade_count),
            "statuses": dict(sorted(statuses.items())),
            "statuses_by_venue": {
                venue: dict(sorted(counter.items()))
                for venue, counter in statuses_by_venue.items()
            },
            "right_censored_by_horizon": right_censored_by_horizon,
        },
        "strata": strata,
        "launches": per_launch,
        "economic_coverage": {
            "executable_entry_quotes_loaded": False,
            "executable_exit_quotes_loaded": False,
            "fees_loaded": False,
            "slippage_loaded": False,
            "latency_penalty_loaded": False,
            "net_executable_return_ready": False,
            "status": "FEATURE_RESEARCH_ONLY_NOT_PROFIT_VALIDATION",
        },
        "research_only": {
            "future_outcomes_loaded": False,
            "return_values_reported": False,
            "thresholds_optimized": False,
            "automatic_trade_decision": False,
            "pump_and_pumpswap_strata_kept_separate": True,
            "features_are_cumulative_and_horizon_causal": True,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _parse_horizons(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("horizons must be comma-separated integers") from exc
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("horizons must be positive")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DB-free/network-free causal Launch Burst shadow replay from finalized evidence"
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--horizons", type=_parse_horizons, default=DEFAULT_HORIZONS_SECONDS)
    parser.add_argument("--candidate-parity-report", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/launch_burst_shadow_v0/report.json"),
    )
    args = parser.parse_args()

    live = _read_json(args.live_report)
    processed_root = _resolve_declared(args.live_report, (live.get("artifacts") or {}).get("processed_chunks"))
    bootstrap_report = _resolve_declared(args.live_report, (live.get("bootstrap") or {}).get("report_path"))
    protected = [args.live_report, processed_root, bootstrap_report]
    if args.candidate_parity_report is not None:
        protected.append(args.candidate_parity_report)
    _assert_output_isolated(args.output, protected)

    result = run_shadow_v0(
        live_report_path=args.live_report,
        horizons_seconds=args.horizons,
        candidate_parity_report=args.candidate_parity_report,
    )
    _write_json(args.output, result)
    print(
        f"Launch Burst Shadow V0 classification={result['classification']} "
        f"anchors={sum(item['anchor_count'] for item in result['strata'].values())} "
        f"adapted={result['feature_coverage']['adapted_trade_count']}/"
        f"{result['feature_coverage']['decoded_trade_count']}"
    )
    print(f"output={args.output}")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
