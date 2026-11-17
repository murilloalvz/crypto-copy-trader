from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from src.jupiter_research_entry_route import (
    JUPITER_RESEARCH_ENTRY_PROVIDER,
    JUPITER_RESEARCH_ENTRY_PURPOSE,
)
from src.jupiter_research_exit_route import (
    JUPITER_RESEARCH_EXIT_PROVIDER,
    JUPITER_RESEARCH_EXIT_PURPOSE_PREFIX,
)
from src.opportunity_onchain_hazard import ONCHAIN_HAZARD_PROVIDER, ONCHAIN_HAZARD_PURPOSE
from src.opportunity_provider_attempt_store import FINAL_PROVIDER_STATUSES, list_provider_attempts
from src.opportunity_route_research_store import (
    load_route_research_decision,
    load_route_research_outcomes,
)


def _one_line(value: object | None, *, limit: int = 320) -> str:
    if value is None:
        return "-"
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return text[:limit] if text else "-"


def _exit_horizon_from_purpose(purpose: str) -> int | None:
    prefix = f"{JUPITER_RESEARCH_EXIT_PURPOSE_PREFIX}_"
    suffix = "s_v1"
    if not purpose.startswith(prefix) or not purpose.endswith(suffix):
        return None
    raw = purpose[len(prefix) : -len(suffix)]
    try:
        return int(raw)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only structural diagnostic for route-research runs. Uses persisted SQLite "
            "evidence only; no RPC/Jupiter calls and no writes."
        )
    )
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args()
    run_key = args.run_key.strip()
    if not run_key:
        raise SystemExit("--run-key cannot be empty")

    hazards = list_provider_attempts(
        acquisition_run_key=run_key,
        provider=ONCHAIN_HAZARD_PROVIDER,
        purpose=ONCHAIN_HAZARD_PURPOSE,
    )
    entries = list_provider_attempts(
        acquisition_run_key=run_key,
        provider=JUPITER_RESEARCH_ENTRY_PROVIDER,
        purpose=JUPITER_RESEARCH_ENTRY_PURPOSE,
    )
    all_jupiter = list_provider_attempts(
        acquisition_run_key=run_key,
        provider=JUPITER_RESEARCH_EXIT_PROVIDER,
    )
    exits = [
        item
        for item in all_jupiter
        if item.purpose.startswith(f"{JUPITER_RESEARCH_EXIT_PURPOSE_PREFIX}_")
    ]

    entry_by_episode = {item.episode_key: item for item in entries}

    print("Crypto Copy Trader — Route Research Structural Diagnostic v41")
    print(
        "Mode: READ ONLY — persisted hazard/Jupiter evidence only; no provider calls, no backfill, no writes."
    )
    print(f"run_key={run_key}")
    print("\nSELECTED / ENTRY ACCOUNTING")

    terminal_hazard_exclusions = 0
    eligible_for_entry = 0
    eligible_entry_terminal = 0
    unexpected_entry_after_hazard_failure = 0
    missing_entry_after_available_hazard = 0
    decisions = 0

    for index, hazard in enumerate(hazards, start=1):
        entry = entry_by_episode.get(hazard.episode_key)
        decision = load_route_research_decision(
            acquisition_run_key=run_key,
            episode_key=hazard.episode_key,
        )
        if decision is not None:
            decisions += 1
        token_mint = str((hazard.details or {}).get("token_mint") or "")

        if hazard.status == "AVAILABLE":
            eligible_for_entry += 1
            if entry is None:
                missing_entry_after_available_hazard += 1
                disposition = "MISSING_ENTRY_AFTER_AVAILABLE_HAZARD"
            elif entry.status in FINAL_PROVIDER_STATUSES:
                eligible_entry_terminal += 1
                disposition = (
                    "DECISION_FROZEN"
                    if decision is not None and entry.status == "AVAILABLE"
                    else f"ENTRY_{entry.status}"
                )
            else:
                disposition = f"ENTRY_{entry.status}"
        else:
            if hazard.status in FINAL_PROVIDER_STATUSES:
                terminal_hazard_exclusions += 1
            if entry is not None:
                unexpected_entry_after_hazard_failure += 1
                disposition = f"UNEXPECTED_ENTRY_AFTER_HAZARD_{hazard.status}"
            else:
                disposition = f"EXPLICIT_HAZARD_{hazard.status}"

        print(
            f"[{index:02d}] episode={hazard.episode_key[-16:]} token={token_mint[-16:] or '-'} "
            f"hazard={hazard.status} entry={(entry.status if entry else 'NOT_ATTEMPTED')} "
            f"decision={'YES' if decision is not None else 'NO'} disposition={disposition}"
        )
        if hazard.status != "AVAILABLE":
            print(
                f"     hazard_error={hazard.error_type or '-'}:{_one_line(hazard.error_message)}"
            )
        if entry is not None and entry.status not in {"AVAILABLE", "STARTED"}:
            print(
                f"     entry_error={entry.error_type or '-'}:{_one_line(entry.error_message)}"
            )

    selected = len(hazards)
    pipeline_terminal = terminal_hazard_exclusions + eligible_entry_terminal
    pipeline_coverage = 100.0 * pipeline_terminal / selected if selected else 0.0
    eligible_entry_coverage = (
        100.0 * eligible_entry_terminal / eligible_for_entry if eligible_for_entry else 0.0
    )

    print("\nENTRY SUMMARY")
    print(
        f"selected_reconstructed_from_v37_hazard_attempts={selected} "
        f"hazard_terminal_exclusions={terminal_hazard_exclusions} "
        f"entry_eligible={eligible_for_entry} entry_attempts={len(entries)} "
        f"entry_terminal_eligible={eligible_entry_terminal} decisions={decisions}"
    )
    print(
        f"selected_terminal_disposition_coverage_pct={pipeline_coverage:.1f}% "
        f"entry_terminal_coverage_among_eligible_pct={eligible_entry_coverage:.1f}% "
        f"missing_entry_after_available_hazard={missing_entry_after_available_hazard} "
        f"unexpected_entry_after_hazard_failure={unexpected_entry_after_hazard_failure}"
    )

    entry_fingerprints: Counter[tuple[str, str]] = Counter()
    for entry in entries:
        if entry.status not in {"AVAILABLE", "STARTED"}:
            entry_fingerprints[(entry.error_type or entry.status, _one_line(entry.error_message))] += 1
    if not entry_fingerprints:
        print("entry_provider_error_fingerprints={}")
    else:
        print("entry_provider_error_fingerprints=")
        for (error_type, message), count in entry_fingerprints.most_common():
            print(f"  count={count} error_type={error_type} message={message}")

    if not selected:
        entry_classification = "INCONCLUSIVE_NO_RECONSTRUCTABLE_SELECTED_SAMPLE"
    elif (
        pipeline_terminal == selected
        and eligible_entry_terminal == eligible_for_entry
        and len(entries) == eligible_for_entry
        and missing_entry_after_available_hazard == 0
        and unexpected_entry_after_hazard_failure == 0
    ):
        entry_classification = "PASS_EXPLICIT_UPSTREAM_EXCLUSION_ACCOUNTING"
    else:
        entry_classification = "FAIL_ENTRY_OR_UPSTREAM_ACCOUNTING"
    print(f"entry_accounting_classification={entry_classification}")
    print(
        "note=historical classifications are not rewritten. This diagnostic distinguishes explicit "
        "upstream/provider missingness from genuinely missing eligible entry plumbing."
    )

    print("\nFORWARD PROVIDER ERRORS")
    outcome_rows = load_route_research_outcomes(acquisition_run_key=run_key)
    outcome_by_identity = {
        (item.episode_key, item.horizon_seconds): item for item in outcome_rows
    }
    fingerprints: Counter[tuple[str, str]] = Counter()
    episode_error_horizons: dict[str, list[int]] = defaultdict(list)
    for attempt in sorted(exits, key=lambda item: (item.episode_key, item.started_at, item.purpose)):
        horizon = _exit_horizon_from_purpose(attempt.purpose)
        if horizon is None:
            continue
        outcome = outcome_by_identity.get((attempt.episode_key, horizon))
        if attempt.status not in {"AVAILABLE", "STARTED"}:
            message = _one_line(attempt.error_message)
            fingerprints[(attempt.error_type or attempt.status, message)] += 1
            episode_error_horizons[attempt.episode_key].append(horizon)
            print(
                f"episode={attempt.episode_key[-16:]} horizon={horizon}s "
                f"provider_status={attempt.status} outcome_status={(outcome.status if outcome else 'MISSING')} "
                f"error={attempt.error_type or '-'}:{message}"
            )

    if not fingerprints:
        print("provider_error_fingerprints={}")
    else:
        print("provider_error_fingerprints=")
        for (error_type, message), count in fingerprints.most_common():
            print(f"  count={count} error_type={error_type} message={message}")

    persistent = {
        episode: sorted(set(horizons))
        for episode, horizons in episode_error_horizons.items()
        if set(horizons) >= {300, 900, 3600}
    }
    print(
        "persistent_same_episode_failures="
        + (
            str({episode[-16:]: horizons for episode, horizons in persistent.items()})
            if persistent
            else "{}"
        )
    )
    print(
        "Interpretation: repeated provider errors are explicit missingness. Forward repeated errors "
        "for the same episode across all horizons are persistent route/provider evidence, not collector plumbing failures."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
