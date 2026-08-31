from collections import Counter
from dataclasses import dataclass
from statistics import median

from src.causal_quote_store import ensure_causal_quote_schema
from src.database import connection
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_quote_watch import ensure_quote_attempt_schema


@dataclass(frozen=True)
class QuoteDelayMetrics:
    delay_seconds: int
    attempt_count: int
    success_count: int
    failure_count: int
    success_pct: float
    executable_count: int
    proxy_count: int
    median_request_lag_seconds: float | None
    p95_request_lag_seconds: float | None
    median_completion_lag_seconds: float | None
    p95_completion_lag_seconds: float | None
    errors: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class WalletQuoteMetrics:
    attempt_count: int
    success_count: int
    failure_count: int
    success_pct: float
    executable_count: int
    proxy_count: int
    wallet_count: int
    token_count: int
    delays: tuple[QuoteDelayMetrics, ...]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _load_rows(
    *,
    wallet_addresses: tuple[str, ...] | list[str] | None = None,
    source_event_keys: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    ensure_wallet_forward_observation_schema()
    ensure_quote_attempt_schema()
    ensure_causal_quote_schema()
    addresses = tuple(
        dict.fromkeys(item.strip() for item in (wallet_addresses or []) if item.strip())
    )
    normalized_event_keys: tuple[str, ...] | None = None
    if source_event_keys is not None:
        normalized_event_keys = tuple(
            dict.fromkeys(
                str(item).strip() for item in source_event_keys if str(item).strip()
            )
        )
        if not normalized_event_keys:
            return []

    query = """SELECT
        a.wallet_address,
        a.token_mint,
        a.target_at,
        a.requested_at,
        a.completed_at,
        a.status,
        a.error_class,
        a.error_message,
        a.source_event_key,
        w.observed_at AS wallet_observed_at,
        q.executable AS quote_executable
    FROM causal_quote_attempts a
    LEFT JOIN wallet_forward_observations w
        ON w.observation_key = a.source_event_key
    LEFT JOIN causal_quote_observations q
        ON q.quote_key = a.quote_key
    WHERE a.side='buy'"""
    params: list[object] = []
    if addresses:
        placeholders = ",".join("?" for _ in addresses)
        query += f" AND a.wallet_address IN ({placeholders})"
        params.extend(addresses)
    if normalized_event_keys is not None:
        placeholders = ",".join("?" for _ in normalized_event_keys)
        query += f" AND a.source_event_key IN ({placeholders})"
        params.extend(normalized_event_keys)
    query += " ORDER BY a.target_at, a.id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def summarize_wallet_quote_metrics(
    *,
    wallet_addresses: tuple[str, ...] | list[str] | None = None,
    source_event_keys: tuple[str, ...] | list[str] | None = None,
) -> WalletQuoteMetrics:
    rows = _load_rows(
        wallet_addresses=wallet_addresses,
        source_event_keys=source_event_keys,
    )
    success = [row for row in rows if row["status"] == "success"]
    failure = [row for row in rows if row["status"] == "error"]

    grouped: dict[int, list[dict]] = {}
    for row in rows:
        wallet_observed_at = row.get("wallet_observed_at")
        if wallet_observed_at is None:
            continue
        delay = int(row["target_at"]) - int(wallet_observed_at)
        grouped.setdefault(delay, []).append(row)

    delays: list[QuoteDelayMetrics] = []
    for delay, group in sorted(grouped.items()):
        group_success = [row for row in group if row["status"] == "success"]
        group_failure = [row for row in group if row["status"] == "error"]
        request_lags = [
            float(int(row["requested_at"]) - int(row["target_at"])) for row in group
        ]
        completion_lags = [
            float(int(row["completed_at"]) - int(row["target_at"])) for row in group
        ]
        error_counts = Counter(
            str(row["error_class"] or "unknown_error") for row in group_failure
        )
        delays.append(
            QuoteDelayMetrics(
                delay_seconds=delay,
                attempt_count=len(group),
                success_count=len(group_success),
                failure_count=len(group_failure),
                success_pct=(100.0 * len(group_success) / len(group) if group else 0.0),
                executable_count=sum(
                    row.get("quote_executable") == 1 for row in group_success
                ),
                proxy_count=sum(
                    row.get("quote_executable") == 0 for row in group_success
                ),
                median_request_lag_seconds=(median(request_lags) if request_lags else None),
                p95_request_lag_seconds=_percentile(request_lags, 0.95),
                median_completion_lag_seconds=(
                    median(completion_lags) if completion_lags else None
                ),
                p95_completion_lag_seconds=_percentile(completion_lags, 0.95),
                errors=tuple(sorted(error_counts.items())),
            )
        )

    return WalletQuoteMetrics(
        attempt_count=len(rows),
        success_count=len(success),
        failure_count=len(failure),
        success_pct=(100.0 * len(success) / len(rows) if rows else 0.0),
        executable_count=sum(row.get("quote_executable") == 1 for row in success),
        proxy_count=sum(row.get("quote_executable") == 0 for row in success),
        wallet_count=len({str(row["wallet_address"]) for row in rows if row["wallet_address"]}),
        token_count=len({str(row["token_mint"]) for row in rows if row["token_mint"]}),
        delays=tuple(delays),
    )
