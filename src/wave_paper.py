import json
import time
from dataclasses import asdict, dataclass

from src.config import settings
from src.database import connection, rows
from src.prices import GeckoTerminalPriceProvider, PriceProviderError
from src.strategy_versions import (
    LEGACY_WAVE_STRATEGY_VERSION,
    WAVE_STRATEGY_VERSION,
    WAVE_V2_STRATEGY_VERSION,
)
from src.wave_radar import WaveRadarResult, volume_windows_are_consistent


PAPER_HORIZONS_MINUTES = (5, 15, 60)
@dataclass(frozen=True)
class WavePaperUpdate:
    created_signals: int
    completed_checks: int
    failed_checks: int
    pending_checks: int
    exit_enrolled_signals: int = 0
    exit_created_positions: int = 0
    exit_observed_signals: int = 0
    exit_closed_positions: int = 0
    exit_failed_positions: int = 0
    exit_open_positions: int = 0
    exit_open_signals: int = 0
    exit_price_failures: int = 0
    persistence_outcomes: tuple["SignalPersistenceOutcome", ...] = ()


@dataclass(frozen=True)
class SignalPersistenceOutcome:
    token_mint: str
    outcome: str
    signal_id: int | None = None


def _snapshot_matches_momentum_strategy(snapshot_json: str) -> bool:
    """Identify historical entries that already satisfied the v2 momentum gate."""
    try:
        snapshot = json.loads(snapshot_json)
        token = snapshot["token"]
        volume_5m = float(token.get("volume_5m_usd") or 0)
        volume_1h = float(token.get("volume_1h_usd") or 0)
        wave_score = float(snapshot.get("wave_score") or 0)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    hourly_five_minute_average = volume_1h / 12
    acceleration = (
        volume_5m / hourly_five_minute_average
        if hourly_five_minute_average > 0
        else 0
    )
    return wave_score >= 55 and acceleration >= 1.2


def backfill_wave_strategy_versions() -> int:
    """Classify pre-versioning signals without deleting or rewriting outcomes."""
    candidates = rows(
        """SELECT id, snapshot_json FROM wave_signals
        WHERE strategy_version=?""",
        (LEGACY_WAVE_STRATEGY_VERSION,),
    )
    momentum_ids = [
        item["id"]
        for item in candidates
        if _snapshot_matches_momentum_strategy(item["snapshot_json"])
    ]
    if not momentum_ids:
        return 0
    with connection() as conn:
        conn.executemany(
            "UPDATE wave_signals SET strategy_version=? WHERE id=?",
            [(WAVE_V2_STRATEGY_VERSION, signal_id) for signal_id in momentum_ids],
        )
    return len(momentum_ids)


def record_paper_signals_with_outcomes(
    results: tuple[WaveRadarResult, ...] | list[WaveRadarResult],
    *,
    detected_at: int | None = None,
    cooldown_minutes: int = 360,
    copy_size_usd: float | None = None,
    slippage_bps: int | None = None,
) -> tuple[int, tuple[SignalPersistenceOutcome, ...]]:
    """Persist approved radar results as local paper-only entries.

    A token cannot create another signal during the cooldown. This prevents a
    token that remains near the top of the radar from inflating the sample.
    """
    detected_at = int(time.time()) if detected_at is None else int(detected_at)
    copy_size = settings.copy_size_usd if copy_size_usd is None else copy_size_usd
    slippage = settings.slippage_bps if slippage_bps is None else slippage_bps
    cutoff = detected_at - max(1, cooldown_minutes) * 60
    created = 0
    outcomes = []

    backfill_wave_strategy_versions()

    with connection() as conn:
        for result in results:
            token = result.token
            if not result.passed:
                outcomes.append(SignalPersistenceOutcome(token.token, "strategy_rejected"))
                continue
            if not volume_windows_are_consistent(token):
                outcomes.append(SignalPersistenceOutcome(token.token, "volume_inconsistent"))
                continue
            if token.price_usd <= 0:
                outcomes.append(SignalPersistenceOutcome(token.token, "invalid_price"))
                continue
            duplicate = conn.execute(
                """SELECT 1 FROM wave_signals
                WHERE token_mint=? AND detected_at>=? LIMIT 1""",
                (token.token, cutoff),
            ).fetchone()
            if duplicate:
                outcomes.append(SignalPersistenceOutcome(token.token, "duplicate"))
                continue

            entry_execution_price = token.price_usd * (1 + slippage / 10_000)
            snapshot = {
                "strategy_version": WAVE_STRATEGY_VERSION,
                "token": asdict(token),
                "wave_score": result.wave_score,
                "score_components": result.score_components,
                "reasons": result.reasons,
                "cautions": result.cautions,
            }
            cursor = conn.execute(
                """INSERT INTO wave_signals
                (token_mint, symbol, name, detected_at, wave_score,
                 entry_market_price_usd, entry_execution_price_usd,
                 copy_size_usd, slippage_bps, strategy_version, status, snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tracking', ?)""",
                (
                    token.token,
                    token.symbol,
                    token.name,
                    detected_at,
                    result.wave_score,
                    token.price_usd,
                    entry_execution_price,
                    copy_size,
                    slippage,
                    WAVE_STRATEGY_VERSION,
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            signal_id = cursor.lastrowid
            conn.executemany(
                """INSERT INTO wave_signal_checks
                (signal_id, horizon_minutes, target_at, status)
                VALUES (?, ?, ?, 'pending')""",
                [
                    (signal_id, horizon, detected_at + horizon * 60)
                    for horizon in PAPER_HORIZONS_MINUTES
                ],
            )
            created += 1
            outcomes.append(SignalPersistenceOutcome(token.token, "created", signal_id))
    return created, tuple(outcomes)


def record_paper_signals(
    results: tuple[WaveRadarResult, ...] | list[WaveRadarResult],
    *,
    detected_at: int | None = None,
    cooldown_minutes: int = 360,
    copy_size_usd: float | None = None,
    slippage_bps: int | None = None,
) -> int:
    created, _ = record_paper_signals_with_outcomes(
        results,
        detected_at=detected_at,
        cooldown_minutes=cooldown_minutes,
        copy_size_usd=copy_size_usd,
        slippage_bps=slippage_bps,
    )
    return created


def update_wave_paper_prices(
    provider: GeckoTerminalPriceProvider | None = None,
    *,
    now: int | None = None,
) -> dict[str, int]:
    """Settle fixed checkpoints and the active forward exit cohort together."""
    from src.exit_engine import update_exit_positions

    now = int(time.time()) if now is None else int(now)
    provider = provider or GeckoTerminalPriceProvider()
    checks = update_due_paper_checks(provider, now=now)
    exits = update_exit_positions(provider, now=now)
    return {
        **checks,
        "exit_observed_signals": exits.observed_signals,
        "exit_closed_positions": exits.closed_positions,
        "exit_failed_positions": exits.failed_positions,
        "exit_open_positions": exits.open_positions,
        "exit_open_signals": exits.open_signals,
        "exit_price_failures": exits.price_failures,
    }


def update_due_paper_checks(
    provider: GeckoTerminalPriceProvider | None = None,
    *,
    now: int | None = None,
    max_attempts: int | None = None,
) -> dict[str, int]:
    """Price every due horizon at its target minute, even after a late rerun."""
    provider = provider or GeckoTerminalPriceProvider()
    now = int(time.time()) if now is None else int(now)
    retry_limit = settings.max_price_retry_attempts if max_attempts is None else max_attempts
    due = rows(
        """SELECT c.*, s.token_mint, s.entry_execution_price_usd,
        s.copy_size_usd, s.slippage_bps
        FROM wave_signal_checks c
        JOIN wave_signals s ON s.id=c.signal_id
        WHERE c.status='pending' AND c.target_at<=?
        ORDER BY c.target_at, c.id""",
        (now,),
    )
    completed = failed = 0
    touched_signals: set[int] = set()
    for check in due:
        touched_signals.add(check["signal_id"])
        try:
            market_price = provider.price_at(
                check["token_mint"],
                check["target_at"],
                max_distance_seconds=120,
            )
            if market_price <= 0:
                raise PriceProviderError("Preço retornado não é positivo.")
        except PriceProviderError as exc:
            retry_count = int(check["retry_count"] or 0) + 1
            retryable = bool(getattr(exc, "retryable", False))
            status = "pending" if retryable and retry_count < retry_limit else "failed"
            with connection() as conn:
                conn.execute(
                    """UPDATE wave_signal_checks SET status=?, error=?, error_code=?,
                    retry_count=? WHERE id=?""",
                    (
                        status,
                        str(exc),
                        str(getattr(exc, "code", "provider_error")),
                        retry_count,
                        check["id"],
                    ),
                )
            failed += status == "failed"
            continue

        exit_execution_price = market_price * (1 - check["slippage_bps"] / 10_000)
        return_pct = (
            exit_execution_price / check["entry_execution_price_usd"] - 1
        ) * 100
        pnl_usd = check["copy_size_usd"] * return_pct / 100
        with connection() as conn:
            conn.execute(
                """UPDATE wave_signal_checks
                SET observed_at=?, market_price_usd=?, execution_price_usd=?,
                return_pct=?, pnl_usd=?, status='completed', error=NULL,
                error_code=NULL
                WHERE id=?""",
                (
                    now,
                    market_price,
                    exit_execution_price,
                    return_pct,
                    pnl_usd,
                    check["id"],
                ),
            )
        completed += 1

    with connection() as conn:
        for signal_id in touched_signals:
            counts = conn.execute(
                """SELECT
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
                FROM wave_signal_checks WHERE signal_id=?""",
                (signal_id,),
            ).fetchone()
            if counts["pending"] == 0:
                status = "completed_with_errors" if counts["failed"] else "completed"
                conn.execute(
                    "UPDATE wave_signals SET status=? WHERE id=?",
                    (status, signal_id),
                )

    pending = rows(
        "SELECT COUNT(*) AS total FROM wave_signal_checks WHERE status='pending'"
    )[0]["total"]
    return {"completed": completed, "failed": failed, "pending": pending}


def latest_paper_signals(limit: int = 10) -> list[dict]:
    backfill_wave_strategy_versions()
    signals = rows(
        """SELECT id, token_mint, symbol, name, detected_at, wave_score,
        entry_market_price_usd, entry_execution_price_usd, copy_size_usd,
        slippage_bps, strategy_version, status
        FROM wave_signals ORDER BY detected_at DESC, id DESC LIMIT ?""",
        (limit,),
    )
    if not signals:
        return []
    signal_ids = [item["id"] for item in signals]
    placeholders = ",".join("?" for _ in signal_ids)
    checks = rows(
        f"""SELECT signal_id, horizon_minutes, target_at, observed_at,
        market_price_usd, return_pct, pnl_usd, status, error, error_code
        FROM wave_signal_checks WHERE signal_id IN ({placeholders})
        ORDER BY horizon_minutes""",
        tuple(signal_ids),
    )
    by_signal: dict[int, list[dict]] = {signal_id: [] for signal_id in signal_ids}
    for check in checks:
        by_signal[check["signal_id"]].append(check)
    for signal in signals:
        signal["checks"] = by_signal[signal["id"]]
    return signals


def run_wave_paper_cycle(
    results: tuple[WaveRadarResult, ...] | list[WaveRadarResult],
    provider: GeckoTerminalPriceProvider | None = None,
    *,
    now: int | None = None,
) -> WavePaperUpdate:
    from src.exit_engine import ensure_exit_experiment, enroll_forward_signals

    now = int(time.time()) if now is None else int(now)
    experiment = ensure_exit_experiment(activated_at=now)
    created, outcomes = record_paper_signals_with_outcomes(results, detected_at=now)
    enrollment = enroll_forward_signals(experiment["id"])
    check_result = update_wave_paper_prices(provider, now=now)
    return WavePaperUpdate(
        created_signals=created,
        completed_checks=check_result["completed"],
        failed_checks=check_result["failed"],
        pending_checks=check_result["pending"],
        exit_enrolled_signals=enrollment.enrolled_signals,
        exit_created_positions=enrollment.created_positions,
        exit_observed_signals=check_result["exit_observed_signals"],
        exit_closed_positions=check_result["exit_closed_positions"],
        exit_failed_positions=check_result["exit_failed_positions"],
        exit_open_positions=check_result["exit_open_positions"],
        exit_open_signals=check_result["exit_open_signals"],
        exit_price_failures=check_result["exit_price_failures"],
        persistence_outcomes=outcomes,
    )
