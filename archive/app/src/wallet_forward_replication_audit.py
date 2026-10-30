from dataclasses import asdict, dataclass
from types import SimpleNamespace

from src.causal_quote_store import ensure_causal_quote_schema, load_causal_quotes
from src.database import connection
from src.wallet_economic_replay import (
    EconomicReplayConfig,
    replay_source_wallet,
    summarize_economic_replay,
)
from src.wallet_forward_dependence import (
    WalletForwardDependenceSummary,
    summarize_wallet_forward_dependence,
)
from src.wallet_forward_enrollments import load_wallet_forward_enrollments
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_run_compare import (
    WalletForwardRunCompatibility,
    compare_wallet_forward_run_regimes,
)
from src.wallet_forward_runs import WalletForwardRun, get_wallet_forward_run
from src.wallet_quote_watch import (
    ForwardTradeEvent,
    ensure_quote_attempt_schema,
    load_successful_quote_keys_by_event,
)


@dataclass(frozen=True)
class ReplicationQuoteCoverage:
    expected_buy_probe_count: int
    attempted_buy_probe_count: int
    successful_buy_probe_count: int
    failed_buy_probe_count: int
    missing_buy_probe_count: int
    success_coverage_pct: float


@dataclass(frozen=True)
class ReplicationDelayEconomics:
    delay_seconds: int
    buy_count: int
    closed_count: int
    open_count: int
    censored_count: int
    missing_quote_count: int
    wallet_count: int
    token_count: int
    cluster_count: int
    mean_net_return_pct: float | None
    median_net_return_pct: float | None
    win_rate_pct: float | None
    profit_factor: float | None


@dataclass(frozen=True)
class WalletForwardReplicationRunAudit:
    run_key: str
    status: str
    runtime_version: str
    duration_seconds: int | None
    full_run_action_count: int
    full_run_buy_count: int
    full_run_sell_count: int
    active_wallet_count: int
    active_token_count: int
    enrolled_buy_count: int
    followup_only_buy_count: int
    dependence: WalletForwardDependenceSummary
    quote_coverage: ReplicationQuoteCoverage
    exact_loaded_quote_count: int
    economics: tuple[ReplicationDelayEconomics, ...]
    protocol_flags: tuple[str, ...]
    finality_requires_external_check: bool


@dataclass(frozen=True)
class WalletForwardReplicationAudit:
    mode: str
    compatibility: WalletForwardRunCompatibility
    runs: tuple[WalletForwardReplicationRunAudit, ...]
    automatic_pooling_allowed: bool
    interpretation: str
    interpretation_flags: tuple[str, ...]


def _load_quotes_by_exact_key(quote_keys: tuple[str, ...]) -> dict[str, object]:
    """Load persisted quotes without relying on SELECT row order.

    ``load_causal_quotes`` sorts by observation time, while a caller's quote-key list can be in
    event/target order. Zipping those two sequences can silently attach a quote to the wrong
    event. Loading one unique key at a time is intentionally conservative and cheap for these
    small research runs; correctness matters more than query count in the offline audit.
    """

    result: dict[str, object] = {}
    for key in dict.fromkeys(quote_keys):
        rows = load_causal_quotes(quote_keys=(key,))
        if len(rows) > 1:
            raise ValueError(f"quote_key unexpectedly resolved to multiple quotes: {key}")
        if rows:
            result[key] = rows[0]
    return result


def _load_run_rows(run: WalletForwardRun) -> list[object]:
    if run.end_observation_id is None:
        return []
    ensure_wallet_forward_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, observation_key, wallet_address, token_mint, side,
                chain_time, observed_at, token_delta_raw, token_decimals,
                token_balance_before_raw, token_balance_after_raw,
                token_quantity_flags, source_reduction_fraction
            FROM wallet_forward_observations
            WHERE run_key=? AND id>? AND id<=?
            ORDER BY id""",
            (run.run_key, run.baseline_observation_id, run.end_observation_id),
        ).fetchall()
    return [
        SimpleNamespace(
            id=int(row["id"]),
            observation_key=str(row["observation_key"]),
            address=str(row["wallet_address"]),
            wallet_address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
            token_delta_raw=row["token_delta_raw"],
            token_decimals=row["token_decimals"],
            token_balance_before_raw=row["token_balance_before_raw"],
            token_balance_after_raw=row["token_balance_after_raw"],
            token_quantity_flags=row["token_quantity_flags"],
            source_reduction_fraction=row["source_reduction_fraction"],
        )
        for row in rows
    ]


def _enrollment_dependence(run_key: str) -> WalletForwardDependenceSummary:
    enrollments = load_wallet_forward_enrollments(run_key)
    buys = [
        ForwardTradeEvent(
            id=item.observation_id,
            observation_key=item.observation_key,
            wallet_address=item.wallet_address,
            token_mint=item.token_mint,
            chain_time=item.chain_time,
            observed_at=item.observed_at,
            side="buy",
        )
        for item in enrollments
    ]
    return summarize_wallet_forward_dependence(buys)


def _quote_coverage(
    run: WalletForwardRun,
    enrolled_event_keys: tuple[str, ...],
) -> ReplicationQuoteCoverage:
    expected = len(enrolled_event_keys) * len(run.quote_delays_seconds)
    if not enrolled_event_keys:
        return ReplicationQuoteCoverage(0, 0, 0, 0, 0, 0.0)

    ensure_quote_attempt_schema()
    placeholders = ",".join("?" for _ in enrolled_event_keys)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT status, COUNT(*) AS n
            FROM causal_quote_attempts
            WHERE source_event_key IN ({placeholders}) AND side='buy'
            GROUP BY status""",
            enrolled_event_keys,
        ).fetchall()
    by_status = {str(row["status"]): int(row["n"]) for row in rows}
    successful = by_status.get("success", 0)
    failed = by_status.get("error", 0)
    attempted = successful + failed
    missing = max(0, expected - attempted)
    return ReplicationQuoteCoverage(
        expected_buy_probe_count=expected,
        attempted_buy_probe_count=attempted,
        successful_buy_probe_count=successful,
        failed_buy_probe_count=failed,
        missing_buy_probe_count=missing,
        success_coverage_pct=(100.0 * successful / expected if expected else 0.0),
    )


def build_wallet_forward_replication_run_audit(
    run_key: str,
    *,
    delays: tuple[int, ...] = (0, 15, 30, 60, 120),
    allow_proxy_quotes: bool = True,
    slippage_bps: int = 100,
) -> WalletForwardReplicationRunAudit:
    run = get_wallet_forward_run(run_key)
    if run is None:
        raise ValueError(f"wallet forward run not found: {run_key}")

    rows = _load_run_rows(run)
    enrollments = load_wallet_forward_enrollments(run.run_key)
    enrolled_keys = {item.observation_key for item in enrollments}
    enrolled_event_keys = tuple(item.observation_key for item in enrollments)

    protocol_flags: list[str] = []
    if run.status != "COMPLETED":
        protocol_flags.append("run_not_completed")
    if run.end_observation_id is None:
        protocol_flags.append("missing_end_observation_id")
    if run.enrollment_ends_at is None or run.follow_up_ends_at is None:
        protocol_flags.append("missing_enrollment_followup_protocol")
    if run.enrollment_cutoff_observation_id is None:
        protocol_flags.append("missing_enrollment_cutoff")
    if (
        run.status == "COMPLETED"
        and run.ended_at is not None
        and run.follow_up_ends_at is not None
        and run.ended_at < run.follow_up_ends_at
    ):
        protocol_flags.append("completed_before_followup_target")
    if any(item.wallet_address not in run.cohort for item in rows):
        protocol_flags.append("observation_outside_frozen_cohort")

    expected_enrollment_keys = {
        item.observation_key
        for item in rows
        if item.side == "buy"
        and run.enrollment_cutoff_observation_id is not None
        and item.id <= run.enrollment_cutoff_observation_id
    }
    if run.enrollment_cutoff_observation_id is not None and expected_enrollment_keys != enrolled_keys:
        protocol_flags.append("enrollment_rows_do_not_match_frozen_cutoff")

    actions: list[object] = []
    economic_event_keys: list[str] = []
    followup_only_buy_count = 0
    for item in rows:
        economic_eligible = not (item.side == "buy" and item.observation_key not in enrolled_keys)
        if item.side == "buy" and not economic_eligible:
            followup_only_buy_count += 1
        else:
            economic_event_keys.append(item.observation_key)
        item.economic_eligible = economic_eligible
        actions.append(item)

    grouped_buy = load_successful_quote_keys_by_event(economic_event_keys, side="buy")
    grouped_sell = load_successful_quote_keys_by_event(economic_event_keys, side="sell")
    grouped = {
        event: tuple(dict.fromkeys(grouped_buy.get(event, ()) + grouped_sell.get(event, ())))
        for event in economic_event_keys
    }
    quote_keys = tuple(dict.fromkeys(key for keys in grouped.values() for key in keys))
    ensure_causal_quote_schema()
    quotes_by_key = _load_quotes_by_exact_key(quote_keys)
    quotes = tuple(quotes_by_key[key] for key in quote_keys if key in quotes_by_key)
    quotes_by_event = {
        event: tuple(quotes_by_key[key] for key in keys if key in quotes_by_key)
        for event, keys in grouped.items()
    }

    cfg = EconomicReplayConfig(
        delays=tuple(dict.fromkeys(delays)),
        slippage_bps=slippage_bps,
        notional_usd=run.copy_size_usd,
        require_executable_quote=not allow_proxy_quotes,
    )
    economics: list[ReplicationDelayEconomics] = []
    for delay in cfg.delays:
        trades = replay_source_wallet(
            actions,
            quotes,
            config=cfg,
            delay_seconds=delay,
            quotes_by_event=quotes_by_event,
            run_completed=run.status != "ACTIVE",
        )
        summary = summarize_economic_replay(trades, buy_count=len(enrollments))
        economics.append(
            ReplicationDelayEconomics(
                delay_seconds=delay,
                buy_count=summary.buy_count,
                closed_count=summary.closed_count,
                open_count=summary.open_count,
                censored_count=summary.censored_count,
                missing_quote_count=summary.missing_quote_count,
                wallet_count=summary.wallet_count,
                token_count=summary.token_count,
                cluster_count=summary.cluster_count,
                mean_net_return_pct=summary.mean_net_return_pct,
                median_net_return_pct=summary.median_net_return_pct,
                win_rate_pct=summary.win_rate_pct,
                profit_factor=summary.profit_factor,
            )
        )

    return WalletForwardReplicationRunAudit(
        run_key=run.run_key,
        status=run.status,
        runtime_version=run.runtime_version,
        duration_seconds=(
            run.ended_at - run.started_at
            if run.ended_at is not None
            else None
        ),
        full_run_action_count=len(rows),
        full_run_buy_count=sum(1 for item in rows if item.side == "buy"),
        full_run_sell_count=sum(1 for item in rows if item.side == "sell"),
        active_wallet_count=len({item.wallet_address for item in rows}),
        active_token_count=len({item.token_mint for item in rows}),
        enrolled_buy_count=len(enrollments),
        followup_only_buy_count=followup_only_buy_count,
        dependence=_enrollment_dependence(run.run_key),
        quote_coverage=_quote_coverage(run, enrolled_event_keys),
        exact_loaded_quote_count=len(quotes),
        economics=tuple(economics),
        protocol_flags=tuple(protocol_flags),
        finality_requires_external_check=True,
    )


def build_wallet_forward_replication_audit(
    run_keys: tuple[str, ...] | list[str],
    *,
    delays: tuple[int, ...] = (0, 15, 30, 60, 120),
    allow_proxy_quotes: bool = True,
    slippage_bps: int = 100,
) -> WalletForwardReplicationAudit:
    keys = tuple(dict.fromkeys(item.strip() for item in run_keys if item.strip()))
    if len(keys) < 2:
        raise ValueError("replication audit requires at least two distinct run keys")
    runs = []
    for key in keys:
        run = get_wallet_forward_run(key)
        if run is None:
            raise ValueError(f"wallet forward run not found: {key}")
        runs.append(run)
    compatibility = compare_wallet_forward_run_regimes(runs)
    audits = tuple(
        build_wallet_forward_replication_run_audit(
            key,
            delays=delays,
            allow_proxy_quotes=allow_proxy_quotes,
            slippage_bps=slippage_bps,
        )
        for key in keys
    )

    flags: list[str] = []
    if compatibility.differing_fields:
        flags.append("mixed_technical_regime")
    if any(item.protocol_flags for item in audits):
        flags.append("protocol_integrity_review_required")
    if any(item.enrolled_buy_count == 0 for item in audits):
        flags.append("one_or_more_runs_have_zero_enrolled_buys")
    if sum(item.dependence.wallet_token_cluster_count for item in audits) < 5:
        flags.append("few_independent_wallet_token_clusters")
    if any(item.quote_coverage.missing_buy_probe_count for item in audits):
        flags.append("entry_quote_missingness_present")
    if allow_proxy_quotes:
        flags.append("proxy_quotes_not_executable_fills")
    flags.append("finality_must_be_checked_separately")

    if compatibility.differing_fields:
        interpretation = "COMPARE_AS_SEPARATE_TECHNICAL_REGIMES"
    elif any(item.protocol_flags for item in audits):
        interpretation = "PROTOCOL_REVIEW_BEFORE_ECONOMIC_INTERPRETATION"
    elif sum(item.dependence.wallet_token_cluster_count for item in audits) < 5:
        interpretation = "DESCRIPTIVE_REPLICATION_SAMPLE_STILL_NARROW"
    else:
        interpretation = "COMPARE_RUNS_SEPARATELY_BEFORE_ANY_POOLING"

    return WalletForwardReplicationAudit(
        mode="RESEARCH_READ_ONLY",
        compatibility=compatibility,
        runs=audits,
        automatic_pooling_allowed=False,
        interpretation=interpretation,
        interpretation_flags=tuple(flags),
    )


def replication_audit_as_dict(audit: WalletForwardReplicationAudit) -> dict:
    return asdict(audit)
