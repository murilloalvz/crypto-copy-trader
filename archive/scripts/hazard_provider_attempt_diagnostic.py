from __future__ import annotations

import argparse
from collections import Counter

from src.opportunity_provider_attempt_store import list_provider_attempts
from src.opportunity_token_hazard import (
    SOLANA_TRACKER_HAZARD_PROVIDER,
    SOLANA_TRACKER_HAZARD_PURPOSE,
)


def _text(value) -> str:
    if value is None:
        return "none"
    normalized = str(value).strip()
    return normalized if normalized else "none"


def _reason_category(error_type: str | None, error_message: str | None) -> str:
    """Classify only from persisted provider evidence; never perform provider I/O here."""

    haystack = f"{_text(error_type)} {_text(error_message)}".lower()
    if "429" in haystack or "rate limit" in haystack or "limite" in haystack:
        return "RATE_LIMIT"
    if "401" in haystack or "403" in haystack or "authentication" in haystack or "api key" in haystack:
        return "AUTH"
    if "404" in haystack or "not found" in haystack:
        return "HTTP_404"
    if "timeout" in haystack or "timed out" in haystack:
        return "TIMEOUT"
    if "ssl" in haystack or "connection reset" in haystack or "10054" in haystack or "urlerror" in haystack:
        return "NETWORK"
    if "http" in haystack:
        return "HTTP_OTHER"
    if _text(error_type) != "none" or _text(error_message) != "none":
        return "OTHER_PROVIDER_ERROR"
    return "NO_PERSISTED_REASON"


def diagnose_run(run_key: str) -> int:
    attempts = list_provider_attempts(
        acquisition_run_key=run_key,
        provider=SOLANA_TRACKER_HAZARD_PROVIDER,
        purpose=SOLANA_TRACKER_HAZARD_PURPOSE,
    )

    print("Crypto Copy Trader — Hazard Provider Attempt Diagnostic")
    print("Mode: READ ONLY — persisted evidence only; no Solana Tracker/RPC calls.")
    print(
        f"run_key={run_key} provider={SOLANA_TRACKER_HAZARD_PROVIDER} "
        f"purpose={SOLANA_TRACKER_HAZARD_PURPOSE}"
    )

    if not attempts:
        print("attempts=0 classification=INCONCLUSIVE_NO_SAMPLE")
        return 2

    statuses = Counter(item.status for item in attempts)
    categories: Counter[str] = Counter()
    exact_reasons: Counter[tuple[str, str, str]] = Counter()
    available_with_observation = 0

    print("\nATTEMPTS")
    for index, attempt in enumerate(attempts, start=1):
        details = attempt.details or {}
        error_type = _text(attempt.error_type)
        error_message = _text(attempt.error_message)
        category = _reason_category(attempt.error_type, attempt.error_message)
        categories[category] += 1
        exact_reasons[(category, error_type, error_message)] += 1
        observed_at = details.get("observed_at")
        if attempt.status == "AVAILABLE" and observed_at is not None:
            available_with_observation += 1
        print(
            f"[{index:02d}] episode={attempt.episode_key} status={attempt.status} "
            f"category={category} error_type={error_type} message={error_message} "
            f"observed_at={_text(observed_at)}"
        )

    print("\nSUMMARY")
    print(f"attempts={len(attempts)} statuses={dict(statuses)}")
    print(f"available_with_observation={available_with_observation}")
    print(f"reason_categories={dict(categories)}")
    print("reason_groups=")
    for (category, error_type, message), count in exact_reasons.most_common():
        print(
            f"  count={count} category={category} error_type={error_type} message={message}"
        )

    if statuses.get("AVAILABLE", 0) > 0:
        classification = "PASS_HAS_AVAILABLE_HAZARD"
    elif statuses.get("PROVIDER_ERROR", 0) == len(attempts):
        if len(categories) == 1:
            category = next(iter(categories))
            classification = f"FAIL_ALL_PROVIDER_ERROR_{category}"
        else:
            classification = "FAIL_ALL_PROVIDER_ERROR_MIXED_CAUSES"
    else:
        classification = "FAIL_MIXED_TERMINAL_RESULTS"
    print(f"classification={classification}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect persisted Solana Tracker hazard attempts without provider I/O"
    )
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args()
    raise SystemExit(diagnose_run(args.run_key))


if __name__ == "__main__":
    main()
