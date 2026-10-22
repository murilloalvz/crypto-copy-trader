from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence
import uuid

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    COVERAGE_CLASSIFICATION,
    SOURCE_PROVIDER,
    collect_shadow,
    redact_secret,
)
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.market_activity_dynamics_v0 import build_market_activity_dynamics_v0
from src.market_first_prospective_coordinator import prepare_market_first_prospective_episode_v0
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_observation_store import (
    load_market_trades,
    record_market_lifecycle,
    record_market_trade,
)
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_protocol_facts import (
    PumpCurveStateObservation,
    PumpSwapPoolObservation,
    build_market_protocol_facts_v0,
)
from src.market_signal_kernel import IndexedMarketSignalKernel
from src.opportunity_forward_outcome_store import load_opportunity_forward_outcomes
from src.opportunity_snapshot_core import FlowTradeObservation, build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


SMOKE_VERSION = "market_first_live_smoke_v0"
PASS_CLASSIFICATION = "PASS_MARKET_FIRST_LIVE_SMOKE_V0"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_LIVE_SMOKE_V0"
SMOKE_DURATION_SECONDS = 300
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / SMOKE_VERSION
CARBON_MANIFEST_PATH = Path("benchmarks") / "carbon_decoder_parity_v1" / "rust_runner" / "Cargo.toml"
SOURCE_SCOPE = "helius_standard_wss_pump_pumpswap_logs"


def _epoch_now() -> int:
    return int(time.time())


def _build_identity(*, started_at: int) -> dict[str, object]:
    nonce = uuid.uuid4().hex[:12]
    run_id = f"{SMOKE_VERSION}-{int(started_at)}-{nonce}"
    return {
        "mode": "smoke",
        "smoke_version": SMOKE_VERSION,
        "duration_seconds": SMOKE_DURATION_SECONDS,
        "run_id": run_id,
        "acquisition_run_key": run_id,
        "cohort_id": f"{run_id}:operational-smoke",
        "discovery_registry_used": False,
        "economic_edge_evaluated": False,
    }


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _nonnegative_int(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _observed_at_from_wall_ns(wall_ns: int) -> int:
    if not isinstance(wall_ns, int) or isinstance(wall_ns, bool) or wall_ns <= 0:
        raise ValueError("first_received_wall_ns must be a positive integer")
    return wall_ns // 1_000_000_000


def _coverage_artifact(*, acquisition_run_key: str) -> dict[str, object]:
    return {
        "smoke_version": SMOKE_VERSION,
        "acquisition_run_key": acquisition_run_key,
        "source_provider": SOURCE_PROVIDER,
        "source_scope": SOURCE_SCOPE,
        "coverage_classification": COVERAGE_CLASSIFICATION,
        "chain_complete_coverage_claimed": False,
        "scientific_continuous_coverage_persisted": False,
        "scientific_coverage_interval_count": 0,
        "reason": (
            "Helius Standard WSS activity is operational evidence only. "
            "Connection/subscription uptime is not a chain-complete continuous-coverage assertion."
        ),
    }


def _decoder_footer_valid(
    footer: dict[str, Any],
    *,
    expected_input_events: int,
    process_return_code: int,
) -> bool:
    return bool(
        process_return_code == 0
        and footer.get("type") == "carbon_decoder_footer"
        and footer.get("input_events") == expected_input_events
        and footer.get("output_events") == expected_input_events
        and footer.get("decode_failures") == 0
    )


def _run_carbon_decoder(
    *,
    cargo: str,
    carbon_input_path: Path,
    carbon_output_path: Path,
) -> dict[str, Any]:
    command = [
        cargo,
        "run",
        "--release",
        "--quiet",
        "--manifest-path",
        str(CARBON_MANIFEST_PATH),
        "--",
        str(carbon_input_path),
        str(carbon_output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    rows = _jsonl(carbon_output_path)
    footer = next(
        (row for row in reversed(rows) if row.get("type") == "carbon_decoder_footer"),
        {},
    )
    expected_inputs = sum(
        1 for row in _jsonl(carbon_input_path) if row.get("type") == "carbon_decoder_input"
    )
    return {
        "command": command,
        "process_return_code": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
        "stdout_tail": completed.stdout[-4000:],
        "footer": footer,
        "footer_accounting_valid": _decoder_footer_valid(
            footer,
            expected_input_events=expected_inputs,
            process_return_code=completed.returncode,
        ),
    }


def _flow_observations_for_episode(
    *,
    acquisition_run_key: str,
    episode: MarketOpportunityEpisode,
) -> tuple[FlowTradeObservation, ...]:
    rows = load_market_trades(
        acquisition_run_key=acquisition_run_key,
        token_mint=episode.token_mint,
        as_of=episode.first_trigger_observed_at,
    )
    return tuple(
        FlowTradeObservation(
            token_mint=item.observation.token_mint,
            side=item.observation.side,
            chain_time=item.observation.chain_time,
            observed_at=item.observation.observed_at,
            wallet_address=item.observation.wallet_address,
            notional_usd=item.observation.notional_usd,
            price_usd=item.observation.price_usd,
        )
        for item in rows
    )


def _prepare_t0_for_episode(
    *,
    acquisition_run_key: str,
    episode: MarketOpportunityEpisode,
    pump_curve_observations: Sequence[PumpCurveStateObservation] = (),
    pumpswap_pool_observations: Sequence[PumpSwapPoolObservation] = (),
):
    decision_as_of = int(episode.first_trigger_observed_at)
    chain_as_of = int(episode.first_trigger_chain_time)
    flows = _flow_observations_for_episode(
        acquisition_run_key=acquisition_run_key,
        episode=episode,
    )
    protocol = build_market_protocol_facts_v0(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
        pump_curve_observations=tuple(pump_curve_observations),
        pumpswap_pool_observations=tuple(pumpswap_pool_observations),
        migration_evidence=(),
    )
    core = build_opportunity_snapshot_core_v1(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
        chain_as_of=chain_as_of,
        flow_observations=flows,
        quotes=(),
        flow_windows_seconds=(10, 30, 60, 300),
    )
    baseline = build_market_intelligence_baseline_v0(
        protocol=protocol,
        snapshot=core,
    )
    mode = build_pump_creation_mode_facts_v0(
        token_mint=episode.token_mint,
        as_of=decision_as_of,
        observations=(),
    )
    activity = build_market_activity_dynamics_v0(core)
    return prepare_market_first_prospective_episode_v0(
        episode_key=episode.episode_key,
        decision_as_of=decision_as_of,
        market_intelligence=baseline,
        pump_creation_mode=mode,
        activity_dynamics=activity,
    )


def _canonical_rows_in_receive_order(
    *,
    carbon_output_path: Path,
    target_manifest_path: Path,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[str]]:
    manifests = {
        str(row["event_key"]): row
        for row in _jsonl(target_manifest_path)
        if isinstance(row.get("event_key"), str)
    }
    paired: list[tuple[dict[str, Any], dict[str, Any]]] = []
    errors: list[str] = []
    for row in _jsonl(carbon_output_path):
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


def _append_pump_protocol_observation(
    *,
    row: dict[str, Any],
    observed_at: int,
    out: list[PumpCurveStateObservation],
) -> None:
    event_key = _text(row, "event_key")
    mint = _text(row, "mint")
    chain_time = _nonnegative_int(row, "timestamp")
    if event_key is None or mint is None or chain_time is None:
        return
    out.append(
        PumpCurveStateObservation(
            token_mint=mint,
            chain_time=chain_time,
            observed_at=observed_at,
            evidence_key=event_key,
            source="carbon_pump_trade_event_v0",
            complete=None,
            quote_mint=_text(row, "quote_mint"),
            virtual_quote_reserves=_nonnegative_int(row, "virtual_quote_reserves_raw"),
        )
    )


def _append_pumpswap_protocol_observation(
    *,
    row: dict[str, Any],
    observed_at: int,
    token_mint: str,
    quote_mint: str,
    out: list[PumpSwapPoolObservation],
) -> None:
    event_key = _text(row, "event_key")
    pool = _text(row, "pool")
    chain_time = _nonnegative_int(row, "timestamp")
    if event_key is None or pool is None or chain_time is None:
        return
    out.append(
        PumpSwapPoolObservation(
            token_mint=token_mint,
            pool=pool,
            chain_time=chain_time,
            observed_at=observed_at,
            evidence_key=event_key,
            source="carbon_pumpswap_trade_event_v0",
            base_mint=token_mint,
            quote_mint=quote_mint,
            pool_index=None,
            pool_base_token_reserves=_nonnegative_int(row, "pool_base_token_reserves_raw"),
            pool_quote_token_reserves=_nonnegative_int(row, "pool_quote_token_reserves_raw"),
            virtual_quote_reserves=None,
        )
    )


def _process_carbon_output(
    *,
    acquisition_run_key: str,
    carbon_output_path: Path,
    target_manifest_path: Path,
) -> dict[str, Any]:
    ordered, pairing_errors = _canonical_rows_in_receive_order(
        carbon_output_path=carbon_output_path,
        target_manifest_path=target_manifest_path,
    )
    kernel = IndexedMarketSignalKernel()
    pool_identities: list[PumpSwapPoolIdentityObservation] = []
    pump_curve_observations: list[PumpCurveStateObservation] = []
    pumpswap_pool_observations: list[PumpSwapPoolObservation] = []

    decoded_events = 0
    decode_failures = 0
    lifecycle_events = 0
    matched_statuses: dict[str, int] = {}
    market_trade_statuses: dict[str, int] = {}
    market_trade_adapted_events = 0
    triggers_emitted = 0
    first_trigger_episodes = 0
    grouped_triggers = 0
    t0_snapshots_persisted = 0
    forward_outcomes_scheduled = 0
    t0_errors: list[str] = []
    persistence_errors: list[str] = []
    semantic_errors: list[str] = list(pairing_errors)

    for row, manifest in ordered:
        event_key = str(row["event_key"])
        if row.get("status") != "decoded":
            decode_failures += 1
            continue
        decoded_events += 1
        observed_wall_ns = int(manifest["first_received_wall_ns"])
        observed_at = _observed_at_from_wall_ns(observed_wall_ns)
        event_type = _text(row, "event_type")

        if event_type == "pump_create":
            mint = _text(row, "mint")
            chain_time = _nonnegative_int(row, "timestamp")
            if mint is None or chain_time is None:
                semantic_errors.append(f"invalid_pump_create:{event_key}")
                continue
            lifecycle = MarketLifecycleObservation(
                token_mint=mint,
                market_started_at=chain_time,
                observed_at=observed_at,
                venue="pump",
            )
            try:
                record_market_lifecycle(
                    acquisition_run_key=acquisition_run_key,
                    event_key=event_key,
                    source_provider=SOURCE_PROVIDER,
                    observation=lifecycle,
                )
                kernel.ingest_lifecycle(lifecycle)
                lifecycle_events += 1
            except Exception as exc:
                persistence_errors.append(
                    f"{event_key}:pump_lifecycle:{type(exc).__name__}:{exc}"
                )
            continue

        if event_type == "pumpswap_create_pool":
            pool = _text(row, "pool")
            base_mint = _text(row, "base_mint")
            quote_mint = _text(row, "quote_mint")
            chain_time = _nonnegative_int(row, "timestamp")
            slot = _nonnegative_int(row, "slot")
            if (
                pool is None
                or base_mint is None
                or quote_mint is None
                or chain_time is None
                or slot is None
            ):
                semantic_errors.append(f"invalid_pumpswap_create_pool:{event_key}")
                continue
            identity = PumpSwapPoolIdentityObservation(
                pool=pool,
                base_mint=base_mint,
                quote_mint=quote_mint,
                observed_wall_ns=observed_wall_ns,
                observed_slot=slot,
                evidence_key=event_key,
                source="carbon_pumpswap_create_pool_event_v0",
            )
            pool_identities.append(identity)
            lifecycle = MarketLifecycleObservation(
                token_mint=base_mint,
                market_started_at=chain_time,
                observed_at=observed_at,
                venue="pumpswap",
            )
            try:
                record_market_lifecycle(
                    acquisition_run_key=acquisition_run_key,
                    event_key=event_key,
                    source_provider=SOURCE_PROVIDER,
                    observation=lifecycle,
                )
                kernel.ingest_lifecycle(lifecycle)
                lifecycle_events += 1
            except Exception as exc:
                persistence_errors.append(
                    f"{event_key}:pumpswap_lifecycle:{type(exc).__name__}:{exc}"
                )
            continue

        if event_type == "pump_trade":
            matched = adapt_carbon_pump_trade_v0(row, observed_at=observed_at)
            _append_pump_protocol_observation(
                row=row,
                observed_at=observed_at,
                out=pump_curve_observations,
            )
        elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
            matched = adapt_carbon_pumpswap_trade_v0(
                row,
                observed_at=observed_at,
                observed_wall_ns=observed_wall_ns,
                pool_observations=tuple(pumpswap_pool_observations),
                pool_identity_observations=tuple(pool_identities),
            )
        else:
            continue

        matched_statuses[matched.status] = matched_statuses.get(matched.status, 0) + 1
        market_trade = adapt_carbon_matched_unit_to_market_trade_v0(row, matched)
        market_trade_statuses[market_trade.status] = (
            market_trade_statuses.get(market_trade.status, 0) + 1
        )
        if market_trade.status != ADAPTED or market_trade.observation is None:
            continue

        observation: MarketTradeObservation = market_trade.observation
        if event_type in {"pumpswap_buy", "pumpswap_sell"} and matched.observation is not None:
            _append_pumpswap_protocol_observation(
                row=row,
                observed_at=observed_at,
                token_mint=matched.observation.token_mint,
                quote_mint=matched.observation.quote_asset_key,
                out=pumpswap_pool_observations,
            )

        try:
            record_market_trade(
                acquisition_run_key=acquisition_run_key,
                event_key=event_key,
                source_provider=SOURCE_PROVIDER,
                observation=observation,
            )
            trigger = kernel.ingest_trade(observation)
            market_trade_adapted_events += 1
        except Exception as exc:
            persistence_errors.append(
                f"{event_key}:market_trade_or_kernel:{type(exc).__name__}:{exc}"
            )
            continue

        if trigger is None:
            continue
        triggers_emitted += 1
        chain_as_of = trigger.features.chain_as_of
        if chain_as_of is None:
            semantic_errors.append(f"{event_key}:trigger_missing_chain_as_of")
            continue
        trigger_key = f"{event_key}:market-radar:{trigger.trigger_kind}"
        try:
            episode = assign_market_opportunity_trigger(
                acquisition_run_key=acquisition_run_key,
                trigger_key=trigger_key,
                token_mint=trigger.token_mint,
                trigger_kind=trigger.trigger_kind,
                direction=trigger.direction,
                chain_time=int(chain_as_of),
                observed_at=int(trigger.as_of),
                method_version=trigger.method_version,
                venue=observation.venue,
            )
        except Exception as exc:
            persistence_errors.append(
                f"{event_key}:episode_assignment:{type(exc).__name__}:{exc}"
            )
            continue

        if episode.first_trigger_key != trigger_key:
            grouped_triggers += 1
            continue

        first_trigger_episodes += 1
        try:
            preparation = _prepare_t0_for_episode(
                acquisition_run_key=acquisition_run_key,
                episode=episode,
                pump_curve_observations=tuple(pump_curve_observations),
                pumpswap_pool_observations=tuple(pumpswap_pool_observations),
            )
            if preparation.snapshot.decision_as_of != episode.first_trigger_observed_at:
                raise RuntimeError("T0 snapshot moved past first trigger")
            if preparation.snapshot.market_intelligence.chain_as_of != episode.first_trigger_chain_time:
                raise RuntimeError("T0 chain anchor moved from first trigger")
            if any(item.status != "PENDING" for item in preparation.forward_outcomes):
                raise RuntimeError("future outcomes were completed during T0 preparation")
            t0_snapshots_persisted += 1
            forward_outcomes_scheduled += len(preparation.forward_outcomes)
        except Exception as exc:
            t0_errors.append(f"{event_key}:{type(exc).__name__}:{exc}")

    stats = kernel.stats()
    persisted_outcomes = load_opportunity_forward_outcomes(
        acquisition_run_key=acquisition_run_key
    )
    return {
        "canonical_events_paired": len(ordered),
        "decoded_events": decoded_events,
        "decode_failures_seen_in_processing": decode_failures,
        "lifecycle_events_ingested": lifecycle_events,
        "matched_unit_statuses": dict(sorted(matched_statuses.items())),
        "market_trade_statuses": dict(sorted(market_trade_statuses.items())),
        "market_trade_adapted_events": market_trade_adapted_events,
        "kernel_trade_events_ingested": stats.trade_events_ingested,
        "kernel_retained_trade_rows": stats.retained_trade_rows,
        "kernel_tracked_assets": stats.tracked_assets,
        "kernel_triggers_emitted": triggers_emitted,
        "first_trigger_episodes": first_trigger_episodes,
        "grouped_trigger_count": grouped_triggers,
        "t0_snapshots_persisted": t0_snapshots_persisted,
        "forward_outcomes_scheduled": forward_outcomes_scheduled,
        "persisted_forward_outcome_count": len(persisted_outcomes),
        "persisted_forward_outcome_statuses": {
            status: sum(1 for item in persisted_outcomes if item.status == status)
            for status in sorted({item.status for item in persisted_outcomes})
        },
        "pool_identity_observations": len(pool_identities),
        "pump_protocol_observations": len(pump_curve_observations),
        "pumpswap_protocol_observations": len(pumpswap_pool_observations),
        "semantic_errors": semantic_errors,
        "persistence_errors": persistence_errors,
        "t0_errors": t0_errors,
        "economic_edge_evaluated": False,
    }


def _operational_gates(report: dict[str, Any]) -> dict[str, bool]:
    identity = report.get("identity") or {}
    acquisition = report.get("acquisition") or {}
    reducer = report.get("reducer") or {}
    decoder = report.get("decoder") or {}
    pipeline = report.get("pipeline") or {}
    coverage = report.get("coverage") or {}
    adapted = int(pipeline.get("market_trade_adapted_events") or 0)
    ingested = int(pipeline.get("kernel_trade_events_ingested") or 0)

    return {
        "fixed_300s_smoke_mode": (
            identity.get("mode") == "smoke"
            and identity.get("duration_seconds") == SMOKE_DURATION_SECONDS
            and identity.get("discovery_registry_used") is False
        ),
        "wss_operational_shadow_active": acquisition.get("valid_operational_shadow") is True,
        "wss_full_duration_elapsed": acquisition.get("stop_reason") == "duration_elapsed",
        "reducer_valid_for_carbon_decode": reducer.get("valid_for_carbon_decode") is True,
        "carbon_decoder_accounting_valid": decoder.get("footer_accounting_valid") is True,
        "canonical_trade_reached_kernel": adapted > 0 and ingested == adapted,
        "research_plane_persistence_healthy": not pipeline.get("persistence_errors"),
        "t0_pipeline_healthy_when_triggered": not pipeline.get("t0_errors"),
        "canonical_pairing_semantics_healthy": not pipeline.get("semantic_errors"),
        "coverage_claim_is_operational_only": (
            coverage.get("coverage_classification") == COVERAGE_CLASSIFICATION
            and coverage.get("chain_complete_coverage_claimed") is False
            and coverage.get("scientific_continuous_coverage_persisted") is False
            and coverage.get("scientific_coverage_interval_count") == 0
        ),
        "clean_shutdown": report.get("clean_shutdown") is True,
        "no_fatal_stage_error": not bool(report.get("fatal_error")),
        "no_economic_verdict": report.get("economic_edge_evaluated") is False,
    }


def classify_operational_smoke(report: dict[str, Any]) -> str:
    gates = _operational_gates(report)
    return PASS_CLASSIFICATION if all(gates.values()) else FAIL_CLASSIFICATION


def run_live_smoke(
    *,
    api_key: str,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
    cargo: str = "cargo",
) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("HELIUS_API_KEY cannot be blank")

    started_at = _epoch_now()
    identity = _build_identity(started_at=started_at)
    run_id = str(identity["run_id"])
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    trace_path = run_dir / "wss-trace.jsonl"
    carbon_input_path = run_dir / "carbon-input.jsonl"
    target_manifest_path = run_dir / "wss-target-manifest.jsonl"
    carbon_output_path = run_dir / "carbon-canonical.jsonl"
    coverage_path = run_dir / "coverage.json"
    report_path = run_dir / "report.json"

    coverage = _coverage_artifact(
        acquisition_run_key=str(identity["acquisition_run_key"])
    )
    _write_json(coverage_path, coverage)

    report: dict[str, Any] = {
        "type": "market_first_live_smoke",
        "smoke_version": SMOKE_VERSION,
        "identity": identity,
        "artifacts": {
            "run_dir": str(run_dir),
            "trace": str(trace_path),
            "carbon_input": str(carbon_input_path),
            "target_manifest": str(target_manifest_path),
            "carbon_output": str(carbon_output_path),
            "coverage": str(coverage_path),
            "report": str(report_path),
        },
        "coverage": coverage,
        "economic_edge_evaluated": False,
        "clean_shutdown": False,
    }

    try:
        acquisition = asyncio.run(
            collect_shadow(
                api_key=api_key,
                out_path=trace_path,
                duration_seconds=float(SMOKE_DURATION_SECONDS),
                max_log_notifications=0,
                max_reconnects=5,
                ack_timeout_seconds=20.0,
                reconnect_delay_seconds=2.0,
            )
        )
        report["acquisition"] = acquisition

        reducer = reduce_shadow(
            trace_path=trace_path,
            carbon_input_path=carbon_input_path,
            manifest_path=target_manifest_path,
        )
        report["reducer"] = reducer

        decoder = _run_carbon_decoder(
            cargo=cargo,
            carbon_input_path=carbon_input_path,
            carbon_output_path=carbon_output_path,
        )
        report["decoder"] = decoder

        report["pipeline"] = _process_carbon_output(
            acquisition_run_key=str(identity["acquisition_run_key"]),
            carbon_output_path=carbon_output_path,
            target_manifest_path=target_manifest_path,
        )
    except Exception as exc:
        report["fatal_error"] = (
            f"{type(exc).__name__}:{redact_secret(str(exc), api_key)}"
        )
    finally:
        report["ended_at"] = _epoch_now()
        report["clean_shutdown"] = True
        report["gates"] = _operational_gates(report)
        report["classification"] = classify_operational_smoke(report)
        report["valid_smoke"] = report["classification"] == PASS_CLASSIFICATION
        _write_json(report_path, report)

    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SMOKE_VERSION,
        description=(
            "Fixed 300-second Market-First LIVE operational smoke. "
            "Operational evidence only; no economic verdict and no discovery-run reuse."
        ),
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=DEFAULT_ARTIFACTS_ROOT,
    )
    parser.add_argument(
        "--cargo",
        default="cargo",
        help="Cargo executable used for the already-pinned Carbon 2.0.0 decoder.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key.strip():
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2

    report = run_live_smoke(
        api_key=api_key,
        artifacts_root=args.artifacts_root,
        cargo=args.cargo,
    )
    print(json.dumps(report, sort_keys=True, indent=2), flush=True)
    return 0 if report.get("valid_smoke") else 1


if __name__ == "__main__":
    raise SystemExit(main())
