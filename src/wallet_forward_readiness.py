from dataclasses import dataclass


BLOCKING_INTEGRITY_LABELS = {
    "CAUSAL_BOUNDARY_FAILED",
    "STALE_SOURCE_CRITICAL",
}


@dataclass(frozen=True)
class WalletForwardReplayReadiness:
    label: str
    descriptive_replay_allowed: bool
    economic_promotion_allowed: bool
    action_count: int
    buy_event_count: int
    successful_quote_event_count: int
    successful_quote_event_share_pct: float
    expected_attempt_count: int
    attempted_expected_count: int
    attempt_coverage_pct: float
    successful_attempt_count: int
    failed_attempt_count: int
    attempt_success_pct: float
    blockers: tuple[str, ...]
    cautions: tuple[str, ...]
    next_steps: tuple[str, ...]


def summarize_wallet_forward_replay_readiness(
    *,
    run_status: str,
    runtime_version: str,
    quote_mode: str,
    with_jupiter_quotes: bool,
    integrity_label: str,
    action_count: int,
    buy_event_count: int,
    successful_quote_event_count: int,
    expected_attempt_count: int,
    attempted_expected_count: int,
    successful_attempt_count: int,
    failed_attempt_count: int,
    missing_attempt_count: int,
    unexpected_attempt_count: int,
) -> WalletForwardReplayReadiness:
    """Classify whether one frozen forward run can support descriptive causal replay.

    This is deliberately a *data-readiness* gate, not a performance gate. It does not inspect
    returns, win rate or PnL and can never authorize shadow/live or declare economic edge.

    The function avoids inventing a percentage threshold. A fully ready label requires the
    expected causal path to be structurally complete: completed run, non-blocking causal audit,
    at least one BUY, Jupiter enabled, every expected probe attempted, and at least one successful
    quote linked to every BUY. Anything less remains partial or blocked and stays visible.
    """

    counts = {
        "action_count": action_count,
        "buy_event_count": buy_event_count,
        "successful_quote_event_count": successful_quote_event_count,
        "expected_attempt_count": expected_attempt_count,
        "attempted_expected_count": attempted_expected_count,
        "successful_attempt_count": successful_attempt_count,
        "failed_attempt_count": failed_attempt_count,
        "missing_attempt_count": missing_attempt_count,
        "unexpected_attempt_count": unexpected_attempt_count,
    }
    if any(value < 0 for value in counts.values()):
        raise ValueError("readiness counts must be non-negative")
    if successful_quote_event_count > buy_event_count:
        raise ValueError("successful quote events cannot exceed BUY events")
    if attempted_expected_count > expected_attempt_count:
        raise ValueError("attempted expected probes cannot exceed expected probes")
    if missing_attempt_count != expected_attempt_count - attempted_expected_count:
        raise ValueError("missing attempts must reconcile expected minus attempted")
    if successful_attempt_count + failed_attempt_count > attempted_expected_count:
        raise ValueError("success + failure cannot exceed attempted expected probes")

    blockers: list[str] = []
    cautions: list[str] = []
    next_steps: list[str] = []

    if run_status != "COMPLETED":
        blockers.append("run_not_completed")
    if action_count == 0:
        blockers.append("no_forward_actions")
    elif buy_event_count == 0:
        blockers.append("no_forward_buys")
    if integrity_label in BLOCKING_INTEGRITY_LABELS:
        blockers.append(f"integrity:{integrity_label.lower()}")
    if not with_jupiter_quotes:
        blockers.append("jupiter_quotes_disabled")
    elif buy_event_count > 0 and expected_attempt_count == 0:
        blockers.append("quote_expectation_missing")
    if buy_event_count > 0 and successful_quote_event_count == 0:
        blockers.append("no_buy_has_successful_quote")

    if runtime_version == "wallet_forward_runtime_v1_unversioned":
        cautions.append("legacy_runtime_requires_integrity_audit")
    if quote_mode == "proxy":
        cautions.append("quote_only_proxy_not_execution")
    elif quote_mode == "assembled_candidate":
        cautions.append("assembled_transaction_is_not_landing_or_fill")
    if missing_attempt_count:
        cautions.append("missing_quote_probes")
    if failed_attempt_count:
        cautions.append("quote_provider_failures")
    if unexpected_attempt_count:
        cautions.append("unexpected_quote_attempts")
    if 0 < successful_quote_event_count < buy_event_count:
        cautions.append("some_buys_have_no_successful_quote")
    if integrity_label in {"STALE_SOURCE_CAUTION", "PRESTART_CHAIN_CAUTION"}:
        cautions.append(f"integrity:{integrity_label.lower()}")

    if blockers:
        if "no_forward_actions" in blockers or "no_forward_buys" in blockers:
            label = "NO_CAUSAL_SAMPLE"
            next_steps.append("continue_forward_collection_without_changing_the_frozen_cohort")
        elif any(item.startswith("integrity:") for item in blockers):
            label = "DATA_QUALITY_BLOCKED"
            next_steps.append("audit_or_exclude_the_contaminated_run_before_any_economic_claim")
        else:
            label = "QUOTE_PATH_BLOCKED"
            next_steps.append("repair_or_repeat_the_causal_quote_collection_path")
        descriptive_allowed = False
    else:
        structurally_complete = (
            missing_attempt_count == 0
            and successful_quote_event_count == buy_event_count
            and unexpected_attempt_count == 0
        )
        if structurally_complete:
            label = "CAUSAL_REPLAY_SAMPLE_READY"
            descriptive_allowed = True
            next_steps.append("run_event_scoped_causal_replay_and_cost_stress")
        else:
            label = "PARTIAL_CAUSAL_REPLAY_SAMPLE"
            descriptive_allowed = True
            next_steps.append("run_replay_descriptively_with_missingness_visible")
            next_steps.append("continue_collecting_before_any_strategy_promotion")

    # This gate is intentionally incapable of approving economic promotion. That requires a
    # separately frozen strategy hypothesis, outcome measurement, robustness, shadow and later
    # live-readiness gates.
    next_steps.append("do_not_promote_to_shadow_or_live_from_this_gate")

    attempt_coverage = (
        100.0 * attempted_expected_count / expected_attempt_count
        if expected_attempt_count
        else 0.0
    )
    attempt_success = (
        100.0 * successful_attempt_count / attempted_expected_count
        if attempted_expected_count
        else 0.0
    )
    event_quote_share = (
        100.0 * successful_quote_event_count / buy_event_count
        if buy_event_count
        else 0.0
    )

    return WalletForwardReplayReadiness(
        label=label,
        descriptive_replay_allowed=descriptive_allowed,
        economic_promotion_allowed=False,
        action_count=action_count,
        buy_event_count=buy_event_count,
        successful_quote_event_count=successful_quote_event_count,
        successful_quote_event_share_pct=event_quote_share,
        expected_attempt_count=expected_attempt_count,
        attempted_expected_count=attempted_expected_count,
        attempt_coverage_pct=attempt_coverage,
        successful_attempt_count=successful_attempt_count,
        failed_attempt_count=failed_attempt_count,
        attempt_success_pct=attempt_success,
        blockers=tuple(blockers),
        cautions=tuple(cautions),
        next_steps=tuple(next_steps),
    )
