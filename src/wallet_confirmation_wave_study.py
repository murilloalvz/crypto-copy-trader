from dataclasses import dataclass

from src.database import connection
from src.wallet_confirmation_placebo import (
    PlaceboComparison,
    TokenOutcomeObservation,
    WalletConfirmationEvent,
    build_wallet_confirmation_event,
    compare_target_to_placebos,
)
from src.wallet_confirmation_study import load_confirmation_study
from src.wallet_forward_observations import load_wallet_forward_observations


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_confirmation_study_events (
    study_key TEXT NOT NULL,
    signal_id INTEGER NOT NULL,
    token_mint TEXT NOT NULL,
    as_of INTEGER NOT NULL,
    cohort_name TEXT NOT NULL,
    cohort_role TEXT NOT NULL,
    window_seconds INTEGER NOT NULL,
    min_unique_buy_wallets INTEGER NOT NULL,
    buy_action_count INTEGER NOT NULL,
    unique_buy_wallet_count INTEGER NOT NULL,
    first_buy_observed_at INTEGER,
    latest_buy_observed_at INTEGER,
    confirmed INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (study_key, signal_id, cohort_name),
    FOREIGN KEY (study_key) REFERENCES wallet_confirmation_studies(study_key),
    FOREIGN KEY (signal_id) REFERENCES wave_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_wallet_confirmation_events_study
ON wallet_confirmation_study_events(study_key, cohort_name, confirmed, as_of);
"""


@dataclass(frozen=True)
class WaveStudyMaterializationSummary:
    study_key: str
    opportunity_count: int
    expected_event_count: int
    newly_materialized_event_count: int
    existing_event_count: int


@dataclass(frozen=True)
class CohortConfirmationRate:
    cohort_name: str
    cohort_role: str
    opportunity_count: int
    confirmed_count: int
    confirmation_rate_pct: float


@dataclass(frozen=True)
class WaveConfirmationStudyEvaluation:
    study_key: str
    opportunity_count: int
    cohort_rates: tuple[CohortConfirmationRate, ...]
    comparisons: tuple[PlaceboComparison, ...]


def ensure_wave_confirmation_study_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _eligible_wave_signals(study, *, as_of: int) -> list[dict]:
    spec = study.spec
    end = as_of
    if spec.ends_at is not None:
        end = min(end, spec.ends_at - 1)
    if end < spec.starts_at:
        return []
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, token_mint, detected_at
            FROM wave_signals
            WHERE strategy_version=? AND detected_at>=? AND detected_at<=?
            ORDER BY detected_at, id""",
            (spec.wave_strategy_version, spec.starts_at, end),
        ).fetchall()
    return [dict(row) for row in rows]


def materialize_wave_confirmation_events(
    study_key: str,
    *,
    as_of: int,
) -> WaveStudyMaterializationSummary:
    """Freeze confirmation state for every eligible prospective Wave opportunity.

    The function only uses wallet observations whose ``observed_at`` was already available by
    the Wave signal's ``detected_at``. Existing materialized events are never rewritten.
    """

    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    study = load_confirmation_study(study_key)
    if study is None:
        raise ValueError("unknown study_key")
    if study.status not in {"ACTIVE", "CLOSED"}:
        raise ValueError("study must be ACTIVE or CLOSED before materialization")

    ensure_wave_confirmation_study_schema()
    signals = _eligible_wave_signals(study, as_of=as_of)
    cohorts = (study.spec.target, *study.spec.placebos)
    inserted = 0
    for signal in signals:
        signal_as_of = int(signal["detected_at"])
        observations = load_wallet_forward_observations(
            token_mint=str(signal["token_mint"]),
            as_of=signal_as_of,
        )
        for cohort in cohorts:
            event = build_wallet_confirmation_event(
                observations,
                token_mint=str(signal["token_mint"]),
                as_of=signal_as_of,
                cohort=cohort,
                policy=study.spec.policy,
            )
            with connection() as conn:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO wallet_confirmation_study_events(
                        study_key, signal_id, token_mint, as_of, cohort_name, cohort_role,
                        window_seconds, min_unique_buy_wallets, buy_action_count,
                        unique_buy_wallet_count, first_buy_observed_at,
                        latest_buy_observed_at, confirmed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        study_key,
                        int(signal["id"]),
                        event.token_mint,
                        event.as_of,
                        event.cohort_name,
                        event.cohort_role,
                        event.window_seconds,
                        event.min_unique_buy_wallets,
                        event.buy_action_count,
                        event.unique_buy_wallet_count,
                        event.first_buy_observed_at,
                        event.latest_buy_observed_at,
                        int(event.confirmed),
                    ),
                )
                inserted += int(cursor.rowcount > 0)

    expected = len(signals) * len(cohorts)
    with connection() as conn:
        total = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM wallet_confirmation_study_events WHERE study_key=?",
                (study_key,),
            ).fetchone()["n"]
        )
    return WaveStudyMaterializationSummary(
        study_key=study_key,
        opportunity_count=len(signals),
        expected_event_count=expected,
        newly_materialized_event_count=inserted,
        existing_event_count=max(0, total - inserted),
    )


def _load_events(study_key: str) -> list[tuple[int, WalletConfirmationEvent]]:
    ensure_wave_confirmation_study_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT * FROM wallet_confirmation_study_events
            WHERE study_key=? ORDER BY as_of, signal_id, cohort_name""",
            (study_key,),
        ).fetchall()
    return [
        (
            int(row["signal_id"]),
            WalletConfirmationEvent(
                token_mint=str(row["token_mint"]),
                as_of=int(row["as_of"]),
                cohort_name=str(row["cohort_name"]),
                cohort_role=str(row["cohort_role"]),
                window_seconds=int(row["window_seconds"]),
                min_unique_buy_wallets=int(row["min_unique_buy_wallets"]),
                buy_action_count=int(row["buy_action_count"]),
                unique_buy_wallet_count=int(row["unique_buy_wallet_count"]),
                first_buy_observed_at=(
                    None
                    if row["first_buy_observed_at"] is None
                    else int(row["first_buy_observed_at"])
                ),
                latest_buy_observed_at=(
                    None
                    if row["latest_buy_observed_at"] is None
                    else int(row["latest_buy_observed_at"])
                ),
                confirmed=bool(row["confirmed"]),
            ),
        )
        for row in rows
    ]


def _load_wave_outcomes(
    signal_ids: set[int],
    *,
    horizons_minutes: tuple[int, ...],
) -> list[TokenOutcomeObservation]:
    if not signal_ids:
        return []
    placeholders = ",".join("?" for _ in signal_ids)
    horizon_placeholders = ",".join("?" for _ in horizons_minutes)
    params = tuple(sorted(signal_ids)) + tuple(horizons_minutes)
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT s.id AS signal_id, s.token_mint, s.detected_at,
                c.horizon_minutes, c.status, c.return_pct
            FROM wave_signals s
            JOIN wave_signal_checks c ON c.signal_id=s.id
            WHERE s.id IN ({placeholders})
              AND c.horizon_minutes IN ({horizon_placeholders})
            ORDER BY s.id, c.horizon_minutes""",
            params,
        ).fetchall()
    result: list[TokenOutcomeObservation] = []
    for row in rows:
        status = str(row["status"])
        return_pct = (
            float(row["return_pct"])
            if status == "completed" and row["return_pct"] is not None
            else None
        )
        result.append(
            TokenOutcomeObservation(
                token_mint=str(row["token_mint"]),
                as_of=int(row["detected_at"]),
                horizon_minutes=int(row["horizon_minutes"]),
                status=status if status in {"completed", "failed", "pending"} else "pending",
                return_pct=return_pct,
            )
        )
    return result


def evaluate_wave_confirmation_study(study_key: str) -> WaveConfirmationStudyEvaluation:
    study = load_confirmation_study(study_key)
    if study is None:
        raise ValueError("unknown study_key")
    event_rows = _load_events(study_key)
    events = [event for _, event in event_rows]
    signal_ids = {signal_id for signal_id, _ in event_rows}
    outcomes = _load_wave_outcomes(
        signal_ids,
        horizons_minutes=study.spec.horizons_minutes,
    )

    cohort_names = (study.spec.target.name, *(item.name for item in study.spec.placebos))
    rates: list[CohortConfirmationRate] = []
    for cohort_name in cohort_names:
        cohort_events = [item for item in events if item.cohort_name == cohort_name]
        role = (
            cohort_events[0].cohort_role
            if cohort_events
            else "target" if cohort_name == study.spec.target.name else "placebo"
        )
        confirmed = sum(item.confirmed for item in cohort_events)
        rates.append(
            CohortConfirmationRate(
                cohort_name=cohort_name,
                cohort_role=role,
                opportunity_count=len(cohort_events),
                confirmed_count=confirmed,
                confirmation_rate_pct=(
                    100.0 * confirmed / len(cohort_events) if cohort_events else 0.0
                ),
            )
        )

    comparisons = tuple(
        compare_target_to_placebos(
            events,
            outcomes,
            target_cohort_name=study.spec.target.name,
            placebo_cohort_names=tuple(item.name for item in study.spec.placebos),
            horizon_minutes=horizon,
        )
        for horizon in study.spec.horizons_minutes
    )
    opportunity_count = max((item.opportunity_count for item in rates), default=0)
    return WaveConfirmationStudyEvaluation(
        study_key=study_key,
        opportunity_count=opportunity_count,
        cohort_rates=tuple(rates),
        comparisons=comparisons,
    )
