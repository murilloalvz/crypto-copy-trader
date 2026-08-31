import math
import statistics
from dataclasses import dataclass

from src.database import connection
from src.causal_quote_store import ensure_causal_quote_schema
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_quote_watch import ensure_quote_attempt_schema


@dataclass(frozen=True)
class WalletQuotePathPoint:
    source_event_key: str
    wallet_address: str
    token_mint: str
    side: str
    wallet_chain_time: int
    wallet_observed_at: int
    delay_seconds: int
    target_at: int
    requested_at: int
    completed_at: int
    quote_observed_at: int
    price_usd: float
    executable: bool
    source: str
    route_id: str | None


@dataclass(frozen=True)
class WalletQuoteDriftObservation:
    source_event_key: str
    wallet_address: str
    token_mint: str
    side: str
    delay_seconds: int
    baseline_price_usd: float
    delayed_price_usd: float
    raw_price_change_pct: float
    adverse_execution_drift_pct: float
    target_request_lag_seconds: int
    wallet_to_quote_seconds: int
    route_changed: bool | None


@dataclass(frozen=True)
class WalletQuoteDriftDelaySummary:
    delay_seconds: int
    baseline_event_count: int
    paired_count: int
    paired_coverage_pct: float
    median_adverse_drift_pct: float | None
    p95_adverse_drift_pct: float | None
    worst_adverse_drift_pct: float | None
    best_adverse_drift_pct: float | None
    median_target_request_lag_seconds: float | None
    median_wallet_to_quote_seconds: float | None
    route_change_share_pct: float | None


@dataclass(frozen=True)
class WalletQuoteDriftSummary:
    baseline_delay_seconds: int
    baseline_event_count: int
    token_count: int
    wallet_count: int
    delays: tuple[WalletQuoteDriftDelaySummary, ...]


def load_successful_quote_path_points(
    *,
    source_event_keys: tuple[str, ...] | list[str],
) -> tuple[WalletQuotePathPoint, ...]:
    """Load successful quotes linked to the exact forward BUY/SELL observations.

    The join is deliberately event-scoped. A quote captured for the same token but a different
    wallet action cannot enter another event's path.
    """

    keys = tuple(
        dict.fromkeys(str(item).strip() for item in source_event_keys if str(item).strip())
    )
    if not keys:
        return ()

    ensure_wallet_forward_observation_schema()
    ensure_quote_attempt_schema()
    ensure_causal_quote_schema()
    placeholders = ",".join("?" for _ in keys)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT
                a.source_event_key,
                COALESCE(a.wallet_address, w.wallet_address) AS wallet_address,
                a.token_mint,
                a.side,
                w.chain_time AS wallet_chain_time,
                w.observed_at AS wallet_observed_at,
                a.target_at,
                a.requested_at,
                a.completed_at,
                q.observed_at AS quote_observed_at,
                q.price_usd,
                q.executable,
                q.source,
                q.route_id
            FROM causal_quote_attempts a
            JOIN wallet_forward_observations w
              ON w.observation_key=a.source_event_key
            JOIN causal_quote_observations q
              ON q.quote_key=a.quote_key
            WHERE a.source_event_key IN ({placeholders})
              AND a.status='success'
              AND a.quote_key IS NOT NULL
              AND q.token_mint=a.token_mint
              AND q.side=a.side
            ORDER BY w.observed_at, w.id, a.target_at, a.id""",
            keys,
        ).fetchall()

    result: list[WalletQuotePathPoint] = []
    for row in rows:
        wallet_observed_at = int(row["wallet_observed_at"])
        target_at = int(row["target_at"])
        delay = target_at - wallet_observed_at
        if delay < 0:
            raise ValueError("quote target cannot precede wallet observation")
        price = float(row["price_usd"])
        if price <= 0 or not math.isfinite(price):
            raise ValueError("quote price must be positive and finite")
        result.append(
            WalletQuotePathPoint(
                source_event_key=str(row["source_event_key"]),
                wallet_address=str(row["wallet_address"]),
                token_mint=str(row["token_mint"]),
                side=str(row["side"]),
                wallet_chain_time=int(row["wallet_chain_time"]),
                wallet_observed_at=wallet_observed_at,
                delay_seconds=delay,
                target_at=target_at,
                requested_at=int(row["requested_at"]),
                completed_at=int(row["completed_at"]),
                quote_observed_at=int(row["quote_observed_at"]),
                price_usd=price,
                executable=bool(row["executable"]),
                source=str(row["source"]),
                route_id=(None if row["route_id"] is None else str(row["route_id"])),
            )
        )
    return tuple(result)


def _adverse_drift(side: str, raw_change_pct: float) -> float:
    if side == "buy":
        return raw_change_pct
    if side == "sell":
        return -raw_change_pct
    raise ValueError("side must be buy or sell")


def build_wallet_quote_drift_observations(
    points: list[WalletQuotePathPoint] | tuple[WalletQuotePathPoint, ...],
    *,
    baseline_delay_seconds: int = 0,
) -> tuple[WalletQuoteDriftObservation, ...]:
    """Pair each later quote with the same event's baseline route price.

    Positive ``adverse_execution_drift_pct`` means the delayed price moved against a copier:
    higher for BUYs or lower for SELLs. This is a route-price latency diagnostic, not token PnL.
    """

    if baseline_delay_seconds < 0:
        raise ValueError("baseline_delay_seconds must be non-negative")

    grouped: dict[str, list[WalletQuotePathPoint]] = {}
    for item in points:
        if not item.source_event_key.strip():
            raise ValueError("source_event_key cannot be empty")
        if item.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if item.price_usd <= 0 or not math.isfinite(item.price_usd):
            raise ValueError("quote price must be positive and finite")
        if item.delay_seconds < 0:
            raise ValueError("quote delay must be non-negative")
        grouped.setdefault(item.source_event_key, []).append(item)

    output: list[WalletQuoteDriftObservation] = []
    for event_key, group in grouped.items():
        baselines = [item for item in group if item.delay_seconds == baseline_delay_seconds]
        if not baselines:
            continue
        # There should be one successful attempt per event/delay. If duplicated external data
        # exists, use the earliest observed quote deterministically and keep analysis stable.
        baseline = min(
            baselines,
            key=lambda item: (item.quote_observed_at, item.completed_at, item.requested_at),
        )
        for item in sorted(
            group,
            key=lambda value: (value.delay_seconds, value.quote_observed_at, value.completed_at),
        ):
            if item.delay_seconds == baseline_delay_seconds:
                continue
            if item.token_mint != baseline.token_mint or item.side != baseline.side:
                raise ValueError("one event cannot mix token or side across quote path")
            raw_change = 100.0 * (item.price_usd / baseline.price_usd - 1.0)
            route_changed = (
                None
                if baseline.route_id is None or item.route_id is None
                else baseline.route_id != item.route_id
            )
            output.append(
                WalletQuoteDriftObservation(
                    source_event_key=event_key,
                    wallet_address=item.wallet_address,
                    token_mint=item.token_mint,
                    side=item.side,
                    delay_seconds=item.delay_seconds,
                    baseline_price_usd=baseline.price_usd,
                    delayed_price_usd=item.price_usd,
                    raw_price_change_pct=raw_change,
                    adverse_execution_drift_pct=_adverse_drift(item.side, raw_change),
                    target_request_lag_seconds=item.requested_at - item.target_at,
                    wallet_to_quote_seconds=item.quote_observed_at - item.wallet_observed_at,
                    route_changed=route_changed,
                )
            )

    return tuple(
        sorted(
            output,
            key=lambda item: (item.delay_seconds, item.source_event_key),
        )
    )


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[index]


def summarize_wallet_quote_drift(
    points: list[WalletQuotePathPoint] | tuple[WalletQuotePathPoint, ...],
    observations: list[WalletQuoteDriftObservation]
    | tuple[WalletQuoteDriftObservation, ...],
    *,
    baseline_delay_seconds: int = 0,
) -> WalletQuoteDriftSummary:
    if baseline_delay_seconds < 0:
        raise ValueError("baseline_delay_seconds must be non-negative")

    baseline_points: dict[str, WalletQuotePathPoint] = {}
    for item in points:
        if item.delay_seconds == baseline_delay_seconds:
            baseline_points.setdefault(item.source_event_key, item)
    baseline_count = len(baseline_points)

    delays: list[WalletQuoteDriftDelaySummary] = []
    for delay in sorted({item.delay_seconds for item in observations}):
        group = [item for item in observations if item.delay_seconds == delay]
        drift_values = [item.adverse_execution_drift_pct for item in group]
        request_lags = [float(item.target_request_lag_seconds) for item in group]
        wallet_to_quote = [float(item.wallet_to_quote_seconds) for item in group]
        known_route_changes = [item.route_changed for item in group if item.route_changed is not None]
        delays.append(
            WalletQuoteDriftDelaySummary(
                delay_seconds=delay,
                baseline_event_count=baseline_count,
                paired_count=len(group),
                paired_coverage_pct=(100.0 * len(group) / baseline_count if baseline_count else 0.0),
                median_adverse_drift_pct=(statistics.median(drift_values) if drift_values else None),
                p95_adverse_drift_pct=_p95(drift_values),
                worst_adverse_drift_pct=(max(drift_values) if drift_values else None),
                best_adverse_drift_pct=(min(drift_values) if drift_values else None),
                median_target_request_lag_seconds=(statistics.median(request_lags) if request_lags else None),
                median_wallet_to_quote_seconds=(statistics.median(wallet_to_quote) if wallet_to_quote else None),
                route_change_share_pct=(
                    100.0 * sum(bool(value) for value in known_route_changes) / len(known_route_changes)
                    if known_route_changes
                    else None
                ),
            )
        )

    return WalletQuoteDriftSummary(
        baseline_delay_seconds=baseline_delay_seconds,
        baseline_event_count=baseline_count,
        token_count=len({item.token_mint for item in baseline_points.values()}),
        wallet_count=len({item.wallet_address for item in baseline_points.values()}),
        delays=tuple(delays),
    )
