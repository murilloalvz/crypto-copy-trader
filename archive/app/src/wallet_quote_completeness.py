from dataclasses import dataclass

from src.database import connection
from src.wallet_quote_watch import ForwardBuyEvent, ensure_quote_attempt_schema


@dataclass(frozen=True)
class QuoteAttemptCompletenessDelay:
    delay_seconds: int
    expected_count: int
    attempted_count: int
    missing_count: int
    attempt_coverage_pct: float


@dataclass(frozen=True)
class QuoteAttemptCompletenessSummary:
    buy_event_count: int
    delay_count: int
    expected_attempt_count: int
    attempted_expected_count: int
    successful_expected_count: int
    failed_expected_count: int
    missing_attempt_count: int
    unexpected_attempt_count: int
    complete_event_count: int
    incomplete_event_count: int
    complete_event_share_pct: float
    delays: tuple[QuoteAttemptCompletenessDelay, ...]


def summarize_quote_attempt_completeness(
    events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    delays_seconds: tuple[int, ...] | list[int],
) -> QuoteAttemptCompletenessSummary:
    """Compare frozen run expectations against persisted attempts, including missing probes.

    Missing probes are reconstructed from the run's causal BUY events and frozen delay policy.
    They therefore stay in the denominator even though the older quote watcher persisted rows only
    after an HTTP attempt actually started. Success/failure counts below are restricted to the
    *expected* event×delay keys so an accidental extra probe cannot improve or worsen run metrics.
    """

    delays = tuple(dict.fromkeys(int(item) for item in delays_seconds))
    if any(delay < 0 for delay in delays):
        raise ValueError("quote delays must be non-negative")

    event_list = list(events)
    seen_ids: set[int] = set()
    seen_keys: set[str] = set()
    for event in event_list:
        if event.id <= 0:
            raise ValueError("forward buy event id must be positive")
        if event.id in seen_ids or event.observation_key in seen_keys:
            raise ValueError("forward buy events must be unique")
        seen_ids.add(event.id)
        seen_keys.add(event.observation_key)

    expected_keys_by_delay: dict[int, set[str]] = {
        delay: {
            f"wallet-forward:{event.id}:buy:+{delay}s:jupiter-v2"
            for event in event_list
        }
        for delay in delays
    }
    expected_all = set().union(*expected_keys_by_delay.values()) if delays else set()

    ensure_quote_attempt_schema()
    actual_expected: set[str] = set()
    successful_expected: set[str] = set()
    failed_expected: set[str] = set()
    unexpected = 0
    if event_list:
        source_keys = tuple(event.observation_key for event in event_list)
        placeholders = ",".join("?" for _ in source_keys)
        with connection() as conn:
            rows = conn.execute(
                f"""SELECT attempt_key, source_event_key, status
                FROM causal_quote_attempts
                WHERE source_event_key IN ({placeholders}) AND side='buy'""",
                source_keys,
            ).fetchall()
        for row in rows:
            key = str(row["attempt_key"])
            if key in expected_all:
                actual_expected.add(key)
                status = str(row["status"])
                if status == "success":
                    successful_expected.add(key)
                elif status == "error":
                    failed_expected.add(key)
            else:
                unexpected += 1

    delay_summaries: list[QuoteAttemptCompletenessDelay] = []
    for delay in delays:
        expected = expected_keys_by_delay[delay]
        attempted = len(expected.intersection(actual_expected))
        total = len(expected)
        delay_summaries.append(
            QuoteAttemptCompletenessDelay(
                delay_seconds=delay,
                expected_count=total,
                attempted_count=attempted,
                missing_count=total - attempted,
                attempt_coverage_pct=(100.0 * attempted / total if total else 0.0),
            )
        )

    complete_events = 0
    for event in event_list:
        event_keys = {
            f"wallet-forward:{event.id}:buy:+{delay}s:jupiter-v2" for delay in delays
        }
        if event_keys.issubset(actual_expected):
            complete_events += 1

    expected_count = len(expected_all)
    attempted_count = len(actual_expected)
    event_count = len(event_list)
    return QuoteAttemptCompletenessSummary(
        buy_event_count=event_count,
        delay_count=len(delays),
        expected_attempt_count=expected_count,
        attempted_expected_count=attempted_count,
        successful_expected_count=len(successful_expected),
        failed_expected_count=len(failed_expected),
        missing_attempt_count=expected_count - attempted_count,
        unexpected_attempt_count=unexpected,
        complete_event_count=complete_events,
        incomplete_event_count=event_count - complete_events,
        complete_event_share_pct=(
            100.0 * complete_events / event_count if event_count else 0.0
        ),
        delays=tuple(delay_summaries),
    )
