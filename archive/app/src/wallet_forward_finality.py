from dataclasses import dataclass


@dataclass(frozen=True)
class WalletForwardFinalitySummary:
    signature_count: int
    finalized_success_count: int
    finalized_error_count: int
    confirmed_count: int
    processed_count: int
    missing_count: int
    unknown_status_count: int
    finalized_share_pct: float


def summarize_wallet_forward_finality(
    statuses: list[dict | None] | tuple[dict | None, ...],
) -> WalletForwardFinalitySummary:
    finalized_success = 0
    finalized_error = 0
    confirmed = 0
    processed = 0
    missing = 0
    unknown = 0

    for status in statuses:
        if status is None:
            missing += 1
            continue
        confirmation = status.get("confirmationStatus")
        error = status.get("err")
        if confirmation == "finalized":
            if error is None:
                finalized_success += 1
            else:
                finalized_error += 1
        elif confirmation == "confirmed":
            confirmed += 1
        elif confirmation == "processed":
            processed += 1
        else:
            unknown += 1

    total = len(statuses)
    finalized_total = finalized_success + finalized_error
    return WalletForwardFinalitySummary(
        signature_count=total,
        finalized_success_count=finalized_success,
        finalized_error_count=finalized_error,
        confirmed_count=confirmed,
        processed_count=processed,
        missing_count=missing,
        unknown_status_count=unknown,
        finalized_share_pct=(100.0 * finalized_total / total if total else 0.0),
    )
