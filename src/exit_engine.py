import json
import time
from dataclasses import dataclass

from src.config import settings
from src.database import connection, rows
from src.prices import GeckoTerminalPriceProvider, PriceProviderError
from src.strategy_versions import WAVE_STRATEGY_VERSION


EXIT_ENGINE_VERSION = "exit_engine_v1"
DEFAULT_OBSERVATION_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class ExitPolicyDefinition:
    version: str
    policy_type: str
    parameters: dict[str, float | int]


@dataclass(frozen=True)
class ExitEnrollment:
    experiment_id: int
    enrolled_signals: int
    created_positions: int


@dataclass(frozen=True)
class ExitEngineUpdate:
    observed_signals: int
    closed_positions: int
    failed_positions: int
    open_positions: int
    open_signals: int
    price_failures: int


EXIT_POLICIES = (
    ExitPolicyDefinition(
        "fixed_15m_v1", "fixed_time", {"max_duration_seconds": 15 * 60}
    ),
    ExitPolicyDefinition(
        "fixed_60m_v1", "fixed_time", {"max_duration_seconds": 60 * 60}
    ),
    ExitPolicyDefinition(
        "stop_loss_10_v1",
        "stop_loss",
        {"threshold_pct": -10.0, "max_duration_seconds": 60 * 60},
    ),
    ExitPolicyDefinition(
        "take_profit_20_v1",
        "take_profit",
        {"threshold_pct": 20.0, "max_duration_seconds": 60 * 60},
    ),
    ExitPolicyDefinition(
        "trailing_stop_10_v1",
        "trailing_stop",
        {"trail_pct": 10.0, "max_duration_seconds": 60 * 60},
    ),
)


def ensure_exit_experiment(
    *,
    activated_at: int | None = None,
    expected_observation_interval_seconds: int = DEFAULT_OBSERVATION_INTERVAL_SECONDS,
) -> dict:
    """Create the forward-only experiment boundary once and return it.

    The signal-id boundary is captured before the radar stores new signals. It is
    therefore impossible for the 19 historical development signals to enter the
    forward cohort, even when timestamps share the same second.
    """
    activated_at = int(time.time()) if activated_at is None else int(activated_at)
    active = rows(
        """SELECT * FROM exit_experiments
        WHERE engine_version=? AND status='active'
        ORDER BY activated_at DESC, id DESC LIMIT 1""",
        (EXIT_ENGINE_VERSION,),
    )
    if active:
        return active[0]

    with connection() as conn:
        frontier = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS signal_id FROM wave_signals"
        ).fetchone()["signal_id"]
        cursor = conn.execute(
            """INSERT INTO exit_experiments
            (engine_version, entry_strategy_version, activated_at,
             start_after_signal_id, expected_observation_interval_seconds,
             status, notes)
            VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (
                EXIT_ENGINE_VERSION,
                WAVE_STRATEGY_VERSION,
                activated_at,
                frontier,
                max(60, int(expected_observation_interval_seconds)),
                (
                    "Forward-only paired exit cohort. Parameters pre-registered; "
                    "historical signals may be used only for infrastructure tests."
                ),
            ),
        )
        experiment_id = int(cursor.lastrowid)
        conn.executemany(
            """INSERT INTO exit_policies
            (experiment_id, policy_version, policy_type, parameters_json)
            VALUES (?, ?, ?, ?)""",
            [
                (
                    experiment_id,
                    policy.version,
                    policy.policy_type,
                    json.dumps(policy.parameters, sort_keys=True, separators=(",", ":")),
                )
                for policy in EXIT_POLICIES
            ],
        )
        row = conn.execute(
            "SELECT * FROM exit_experiments WHERE id=?", (experiment_id,)
        ).fetchone()
        return dict(row)


def enroll_forward_signals(experiment_id: int) -> ExitEnrollment:
    """Pair every eligible post-boundary v3 signal with every policy once."""
    experiment = rows("SELECT * FROM exit_experiments WHERE id=?", (experiment_id,))
    if not experiment:
        raise ValueError(f"Experimento de saída inexistente: {experiment_id}")
    experiment = experiment[0]
    policies = rows(
        "SELECT id FROM exit_policies WHERE experiment_id=? ORDER BY id",
        (experiment_id,),
    )
    signals = rows(
        """SELECT s.* FROM wave_signals s
        WHERE s.id>? AND s.detected_at>=? AND s.strategy_version=?
        AND NOT EXISTS (
            SELECT 1 FROM exit_positions p
            WHERE p.experiment_id=? AND p.signal_id=s.id
        )
        ORDER BY s.id""",
        (
            experiment["start_after_signal_id"],
            experiment["activated_at"],
            experiment["entry_strategy_version"],
            experiment_id,
        ),
    )
    if not signals or not policies:
        return ExitEnrollment(experiment_id, 0, 0)

    values = []
    for signal in signals:
        for policy in policies:
            values.append(
                (
                    experiment_id,
                    policy["id"],
                    signal["id"],
                    signal["strategy_version"],
                    signal["detected_at"],
                    signal["entry_market_price_usd"],
                    signal["entry_execution_price_usd"],
                    signal["copy_size_usd"],
                    signal["slippage_bps"],
                    signal["entry_market_price_usd"],
                    signal["entry_market_price_usd"],
                )
            )
    with connection() as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO exit_positions
            (experiment_id, policy_id, signal_id, entry_strategy_version,
             entry_at, entry_market_price_usd, entry_execution_price_usd,
             copy_size_usd, slippage_bps, highest_market_price_usd,
             lowest_market_price_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        created = conn.total_changes - before
    return ExitEnrollment(experiment_id, len(signals), created)


def _last_completed_minute(now: int) -> int:
    return now - now % 60 - 60


def _policy_exit_reason(
    position: dict,
    *,
    market_price: float,
    highest_price: float,
    observed_at: int,
) -> str | None:
    parameters = json.loads(position["parameters_json"])
    elapsed = observed_at - position["entry_at"]
    max_duration = int(parameters["max_duration_seconds"])
    mark_return_pct = (
        market_price / position["entry_execution_price_usd"] - 1
    ) * 100

    if position["policy_type"] == "fixed_time":
        if elapsed >= max_duration:
            return f"fixed_time_{max_duration // 60}m"
        return None
    if position["policy_type"] == "stop_loss":
        if mark_return_pct <= float(parameters["threshold_pct"]):
            return "stop_loss"
    elif position["policy_type"] == "take_profit":
        if mark_return_pct >= float(parameters["threshold_pct"]):
            return "take_profit"
    elif position["policy_type"] == "trailing_stop":
        drawdown_from_high = (market_price / highest_price - 1) * 100
        if drawdown_from_high <= -float(parameters["trail_pct"]):
            return "trailing_stop"
    else:
        raise ValueError(f"Política de saída desconhecida: {position['policy_type']}")

    if elapsed >= max_duration:
        return f"time_stop_{max_duration // 60}m"
    return None


def _cached_pool_address(token_mint: str, observed_at: int) -> str | None:
    minute_ts = observed_at - observed_at % 60
    cached = rows(
        """SELECT pool_address FROM price_cache
        WHERE token_mint=? AND minute_ts=?""",
        (token_mint, minute_ts),
    )
    return cached[0]["pool_address"] if cached else None


def _record_price_failure(
    experiment_id: int,
    signal: dict,
    *,
    observed_at: int,
    requested_at: int,
    error: PriceProviderError,
    retry_limit: int,
) -> int:
    code = str(getattr(error, "code", "provider_error"))
    with connection() as conn:
        existing = conn.execute(
            """SELECT retry_count FROM exit_price_observations
            WHERE experiment_id=? AND signal_id=? AND observed_at=?""",
            (experiment_id, signal["signal_id"], observed_at),
        ).fetchone()
        observation_retry = int(existing["retry_count"] or 0) + 1 if existing else 1
        conn.execute(
            """INSERT INTO exit_price_observations
            (experiment_id, signal_id, observed_at, requested_at, status,
             error, error_code, retry_count)
            VALUES (?, ?, ?, ?, 'failed', ?, ?, ?)
            ON CONFLICT(experiment_id, signal_id, observed_at) DO UPDATE SET
                requested_at=excluded.requested_at,
                status='failed', error=excluded.error,
                error_code=excluded.error_code,
                retry_count=excluded.retry_count,
                updated_at=CURRENT_TIMESTAMP""",
            (
                experiment_id,
                signal["signal_id"],
                observed_at,
                requested_at,
                str(error),
                code,
                observation_retry,
            ),
        )
        positions = conn.execute(
            """SELECT p.id, p.entry_at, p.retry_count, ep.parameters_json
            FROM exit_positions p
            JOIN exit_policies ep ON ep.id=p.policy_id
            WHERE p.experiment_id=? AND p.signal_id=? AND p.status='open'""",
            (experiment_id, signal["signal_id"]),
        ).fetchall()
        failed = 0
        for position in positions:
            retry_count = int(position["retry_count"] or 0) + 1
            max_duration = int(json.loads(position["parameters_json"])["max_duration_seconds"])
            is_due = observed_at - position["entry_at"] >= max_duration
            status = "failed" if is_due and retry_count >= retry_limit else "open"
            conn.execute(
                """UPDATE exit_positions SET status=?, error=?, error_code=?,
                retry_count=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, str(error), code, retry_count, position["id"]),
            )
            failed += status == "failed"
    return failed


def _apply_observation(
    experiment_id: int,
    signal_id: int,
    *,
    observed_at: int,
    market_price: float,
    policy_id: int | None = None,
    skip_due_fixed: bool = False,
) -> int:
    positions = rows(
        """SELECT p.*, ep.policy_version, ep.policy_type, ep.parameters_json
        FROM exit_positions p
        JOIN exit_policies ep ON ep.id=p.policy_id
        WHERE p.experiment_id=? AND p.signal_id=? AND p.status='open'
        ORDER BY p.id""",
        (experiment_id, signal_id),
    )
    closed = 0
    for position in positions:
        if policy_id is not None and position["policy_id"] != policy_id:
            continue
        if skip_due_fixed and position["policy_type"] == "fixed_time":
            parameters = json.loads(position["parameters_json"])
            if observed_at - position["entry_at"] >= int(
                parameters["max_duration_seconds"]
            ):
                continue
        if position["last_observed_at"] is not None and position["last_observed_at"] >= observed_at:
            continue
        highest = max(float(position["highest_market_price_usd"]), market_price)
        lowest = min(float(position["lowest_market_price_usd"]), market_price)
        excursion_pct = (
            market_price / position["entry_execution_price_usd"] - 1
        ) * 100
        mfe_pct = max(float(position["mfe_pct"]), excursion_pct, 0.0)
        mae_pct = min(float(position["mae_pct"]), excursion_pct, 0.0)
        reason = _policy_exit_reason(
            position,
            market_price=market_price,
            highest_price=highest,
            observed_at=observed_at,
        )
        values = {
            "highest": highest,
            "lowest": lowest,
            "mfe": mfe_pct,
            "mae": mae_pct,
            "observed_at": observed_at,
            "count": int(position["observation_count"] or 0) + 1,
        }
        if reason is None:
            with connection() as conn:
                conn.execute(
                    """UPDATE exit_positions SET highest_market_price_usd=?,
                    lowest_market_price_usd=?, mfe_pct=?, mae_pct=?,
                    last_observed_at=?, observation_count=?, error=NULL,
                    error_code=NULL, retry_count=0, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                    (
                        values["highest"], values["lowest"], values["mfe"],
                        values["mae"], values["observed_at"], values["count"],
                        position["id"],
                    ),
                )
            continue

        exit_execution_price = market_price * (1 - position["slippage_bps"] / 10_000)
        gross_return_pct = (
            market_price / position["entry_market_price_usd"] - 1
        ) * 100
        net_return_pct = (
            exit_execution_price / position["entry_execution_price_usd"] - 1
        ) * 100
        pnl_usd = position["copy_size_usd"] * net_return_pct / 100
        duration_seconds = max(0, observed_at - position["entry_at"])
        with connection() as conn:
            conn.execute(
                """UPDATE exit_positions SET highest_market_price_usd=?,
                lowest_market_price_usd=?, mfe_pct=?, mae_pct=?,
                last_observed_at=?, observation_count=?, exit_at=?,
                exit_market_price_usd=?, exit_execution_price_usd=?,
                gross_return_pct=?, net_return_pct=?, pnl_usd=?, exit_reason=?,
                duration_seconds=?, status='closed', error=NULL, error_code=NULL,
                retry_count=0, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    values["highest"], values["lowest"], values["mfe"],
                    values["mae"], values["observed_at"], values["count"],
                    observed_at, market_price, exit_execution_price,
                    gross_return_pct, net_return_pct, pnl_usd, reason,
                    duration_seconds, position["id"],
                ),
            )
        closed += 1
    return closed


def _update_due_fixed_positions(
    provider: GeckoTerminalPriceProvider,
    *,
    experiment_id: int,
    now: int,
    retry_limit: int,
) -> tuple[int, int, int, int]:
    """Close exact 15m/60m benchmarks at their target candle.

    These calls normally hit the cache populated by wave_signal_checks. Dynamic
    policies still consume only the monitor's forward observations.
    """
    due = rows(
        """SELECT p.*, ep.parameters_json, s.token_mint
        FROM exit_positions p
        JOIN exit_policies ep ON ep.id=p.policy_id
        JOIN wave_signals s ON s.id=p.signal_id
        WHERE p.experiment_id=? AND p.status='open'
          AND ep.policy_type='fixed_time'
        ORDER BY p.signal_id, p.policy_id""",
        (experiment_id,),
    )
    observed = closed = failed_positions = price_failures = 0
    for position in due:
        duration = int(json.loads(position["parameters_json"])["max_duration_seconds"])
        target_at = int(position["entry_at"]) + duration
        if target_at > now:
            continue
        existing = rows(
            """SELECT market_price_usd, status FROM exit_price_observations
            WHERE experiment_id=? AND signal_id=? AND observed_at=?""",
            (experiment_id, position["signal_id"], target_at),
        )
        market_price = None
        if existing and existing[0]["status"] == "completed":
            market_price = float(existing[0]["market_price_usd"])
        else:
            try:
                market_price = provider.price_at(
                    position["token_mint"], target_at, max_distance_seconds=120
                )
                if market_price <= 0:
                    raise PriceProviderError("Preço retornado não é positivo.")
            except PriceProviderError as exc:
                price_failures += 1
                retry_count = int(position["retry_count"] or 0) + 1
                status = "failed" if retry_count >= retry_limit else "open"
                failed_positions += status == "failed"
                with connection() as conn:
                    conn.execute(
                        """INSERT INTO exit_price_observations
                        (experiment_id, signal_id, observed_at, requested_at,
                         status, error, error_code, retry_count)
                        VALUES (?, ?, ?, ?, 'failed', ?, ?, 1)
                        ON CONFLICT(experiment_id, signal_id, observed_at) DO UPDATE SET
                            requested_at=excluded.requested_at, status='failed',
                            error=excluded.error, error_code=excluded.error_code,
                            retry_count=exit_price_observations.retry_count + 1,
                            updated_at=CURRENT_TIMESTAMP""",
                        (
                            experiment_id,
                            position["signal_id"],
                            target_at,
                            now,
                            str(exc),
                            str(getattr(exc, "code", "provider_error")),
                        ),
                    )
                    conn.execute(
                        """UPDATE exit_positions SET status=?, error=?, error_code=?,
                        retry_count=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (
                            status,
                            str(exc),
                            str(getattr(exc, "code", "provider_error")),
                            retry_count,
                            position["id"],
                        ),
                    )
                continue
            with connection() as conn:
                conn.execute(
                    """INSERT INTO exit_price_observations
                    (experiment_id, signal_id, observed_at, requested_at,
                     market_price_usd, pool_address, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'completed')
                    ON CONFLICT(experiment_id, signal_id, observed_at) DO UPDATE SET
                        requested_at=excluded.requested_at,
                        market_price_usd=excluded.market_price_usd,
                        pool_address=excluded.pool_address, status='completed',
                        error=NULL, error_code=NULL, updated_at=CURRENT_TIMESTAMP""",
                    (
                        experiment_id,
                        position["signal_id"],
                        target_at,
                        now,
                        market_price,
                        _cached_pool_address(position["token_mint"], target_at),
                    ),
                )
        observed += 1
        closed += _apply_observation(
            experiment_id,
            position["signal_id"],
            observed_at=target_at,
            market_price=market_price,
            policy_id=position["policy_id"],
        )
    return observed, closed, failed_positions, price_failures


def update_exit_positions(
    provider: GeckoTerminalPriceProvider | None = None,
    *,
    now: int | None = None,
    experiment_id: int | None = None,
    max_attempts: int | None = None,
) -> ExitEngineUpdate:
    """Observe the last completed minute once and react without backfilling gaps."""
    provider = provider or GeckoTerminalPriceProvider()
    now = int(time.time()) if now is None else int(now)
    retry_limit = settings.max_price_retry_attempts if max_attempts is None else max_attempts
    if experiment_id is None:
        active = rows(
            """SELECT id FROM exit_experiments
            WHERE engine_version=? AND status='active'
            ORDER BY activated_at DESC, id DESC LIMIT 1""",
            (EXIT_ENGINE_VERSION,),
        )
        if not active:
            return ExitEngineUpdate(0, 0, 0, 0, 0, 0)
        experiment_id = active[0]["id"]

    observed_at = _last_completed_minute(now)
    (
        fixed_observed,
        fixed_closed,
        fixed_failed,
        fixed_price_failures,
    ) = _update_due_fixed_positions(
        provider,
        experiment_id=experiment_id,
        now=now,
        retry_limit=max(1, int(retry_limit)),
    )
    signals = rows(
        """SELECT DISTINCT p.signal_id, s.token_mint, s.detected_at
        FROM exit_positions p
        JOIN wave_signals s ON s.id=p.signal_id
        WHERE p.experiment_id=? AND p.status='open'
        ORDER BY p.signal_id""",
        (experiment_id,),
    )
    observed_signals = fixed_observed
    closed_positions = fixed_closed
    failed_positions = fixed_failed
    price_failures = fixed_price_failures
    for signal in signals:
        if observed_at <= signal["detected_at"]:
            continue
        existing = rows(
            """SELECT market_price_usd, status FROM exit_price_observations
            WHERE experiment_id=? AND signal_id=? AND observed_at=?""",
            (experiment_id, signal["signal_id"], observed_at),
        )
        market_price = None
        if existing and existing[0]["status"] == "completed":
            market_price = float(existing[0]["market_price_usd"])
        else:
            try:
                market_price = provider.price_at(
                    signal["token_mint"], observed_at, max_distance_seconds=120
                )
                if market_price <= 0:
                    raise PriceProviderError("Preço retornado não é positivo.")
            except PriceProviderError as exc:
                price_failures += 1
                failed_positions += _record_price_failure(
                    experiment_id,
                    signal,
                    observed_at=observed_at,
                    requested_at=now,
                    error=exc,
                    retry_limit=max(1, int(retry_limit)),
                )
                continue
            with connection() as conn:
                conn.execute(
                    """INSERT INTO exit_price_observations
                    (experiment_id, signal_id, observed_at, requested_at,
                     market_price_usd, pool_address, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'completed')
                    ON CONFLICT(experiment_id, signal_id, observed_at) DO UPDATE SET
                        requested_at=excluded.requested_at,
                        market_price_usd=excluded.market_price_usd,
                        pool_address=excluded.pool_address,
                        status='completed', error=NULL, error_code=NULL,
                        updated_at=CURRENT_TIMESTAMP""",
                    (
                        experiment_id,
                        signal["signal_id"],
                        observed_at,
                        now,
                        market_price,
                        _cached_pool_address(signal["token_mint"], observed_at),
                    ),
                )
        observed_signals += 1
        closed_positions += _apply_observation(
            experiment_id,
            signal["signal_id"],
            observed_at=observed_at,
            market_price=market_price,
            skip_due_fixed=True,
        )

    open_positions = rows(
        """SELECT COUNT(*) AS total FROM exit_positions
        WHERE experiment_id=? AND status='open'""",
        (experiment_id,),
    )[0]["total"]
    open_signals = rows(
        """SELECT COUNT(DISTINCT signal_id) AS total FROM exit_positions
        WHERE experiment_id=? AND status='open'""",
        (experiment_id,),
    )[0]["total"]
    return ExitEngineUpdate(
        observed_signals,
        closed_positions,
        failed_positions,
        open_positions,
        open_signals,
        price_failures,
    )
