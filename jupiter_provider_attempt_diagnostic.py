from __future__ import annotations

import argparse
from collections import Counter

from src.jupiter_episode_execution import (
    JUPITER_ENTRY_PROVIDER,
    JUPITER_ENTRY_PURPOSE,
)
from src.opportunity_provider_attempt_store import list_provider_attempts


def _text(value) -> str:
    if value is None:
        return "none"
    normalized = str(value).strip()
    return normalized if normalized else "none"


def _reason(attempt) -> tuple[str, str, str]:
    details = attempt.details or {}
    code = _text(details.get("provider_error_code"))
    message = _text(details.get("provider_error_message"))
    if code != "none" or message != "none":
        return (code, message, "provider")
    if attempt.error_type or attempt.error_message:
        return (_text(attempt.error_type), _text(attempt.error_message), "attempt")
    if attempt.status == "UNAVAILABLE":
        return ("none", "assembled transaction absent without provider error", "assembly")
    return ("none", "none", "none")


def diagnose_run(run_key: str) -> int:
    attempts = list_provider_attempts(
        acquisition_run_key=run_key,
        provider=JUPITER_ENTRY_PROVIDER,
        purpose=JUPITER_ENTRY_PURPOSE,
    )

    print("Crypto Copy Trader — Jupiter Provider Attempt Diagnostic")
    print("Mode: READ ONLY — persisted evidence only; no RPC/Jupiter calls, signing or execute.")
    print(f"run_key={run_key} provider={JUPITER_ENTRY_PROVIDER} purpose={JUPITER_ENTRY_PURPOSE}")

    if not attempts:
        print("attempts=0 classification=INCONCLUSIVE_NO_SAMPLE")
        return 2

    statuses = Counter(item.status for item in attempts)
    reasons: Counter[tuple[str, str, str]] = Counter()
    executable = 0
    with_route = 0
    assembled = 0

    print("\nATTEMPTS")
    for index, attempt in enumerate(attempts, start=1):
        details = attempt.details or {}
        code, message, source = _reason(attempt)
        assembled_present = bool(details.get("assembled_transaction_present"))
        route_id = _text(details.get("route_id"))
        router = _text(details.get("router"))
        if assembled_present:
            assembled += 1
            executable += 1
        if route_id != "none":
            with_route += 1
        reasons[(code, message, source)] += 1
        print(
            f"[{index:02d}] episode={attempt.episode_key} status={attempt.status} "
            f"assembled={assembled_present} route_id={route_id} router={router} "
            f"reason_source={source} code={code} message={message}"
        )

    print("\nSUMMARY")
    print(f"attempts={len(attempts)} statuses={dict(statuses)}")
    print(
        f"assembled_transactions={assembled} executable_attempts={executable} "
        f"attempts_with_route_id={with_route}"
    )
    print("reason_groups=")
    for (code, message, source), count in reasons.most_common():
        print(f"  count={count} source={source} code={code} message={message}")

    if statuses.get("AVAILABLE", 0) > 0:
        classification = "PASS_HAS_EXECUTABLE"
    elif statuses.get("UNAVAILABLE", 0) == len(attempts):
        classification = "FAIL_ALL_UNAVAILABLE"
    else:
        classification = "FAIL_MIXED_TERMINAL_RESULTS"
    print(f"classification={classification}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect persisted Jupiter episode quote attempts without provider I/O"
    )
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args()
    raise SystemExit(diagnose_run(args.run_key))


if __name__ == "__main__":
    main()
