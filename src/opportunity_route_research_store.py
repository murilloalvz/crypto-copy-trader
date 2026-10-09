from __future__ import annotations

from dataclasses import dataclass
import threading

from src import database
from src.causal_quote_store import load_causal_quotes
from src.jupiter_research_entry_route import (
    JUPITER_RESEARCH_ENTRY_PROVIDER,
    JUPITER_RESEARCH_ENTRY_PURPOSE,
)
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_onchain_hazard import ONCHAIN_HAZARD_PROVIDER, ONCHAIN_HAZARD_PURPOSE
from src.opportunity_provider_attempt_store import OpportunityProviderAttempt
from src.database import connection


ROUTE_RESEARCH_VERSION = "route_only_forward_research_v1"
ROUTE_RESEARCH_HORIZONS_SECONDS = (300, 900, 3600)
ROUTE_RESEARCH_FINAL_STATUSES = {"AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"}


@dataclass(frozen=True)
class RouteResearchDecision:
    decision_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    episode_t0: int
    research_decision_as_of: int
    entry_quote_key: str
    hazard_attempt_key: str
    method_version: str


@dataclass(frozen=True)
class RouteResearchForwardOutcome:
    outcome_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    research_decision_as_of: int
    horizon_seconds: int
    target_at: int
    status: str
    observed_at: int | None
    quote_key: str | None
    error_type: str | None
    error_message: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_route_research_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    episode_t0 INTEGER NOT NULL,
    research_decision_as_of INTEGER NOT NULL,
    entry_quote_key TEXT NOT NULL,
    hazard_attempt_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key)
);

CREATE INDEX IF NOT EXISTS idx_route_research_decision_run_time
ON opportunity_route_research_decisions(acquisition_run_key, research_decision_as_of, id);

CREATE TABLE IF NOT EXISTS opportunity_route_research_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    research_decision_as_of INTEGER NOT NULL,
    horizon_seconds INTEGER NOT NULL,
    target_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    observed_at INTEGER,
    quote_key TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key, horizon_seconds)
);

CREATE INDEX IF NOT EXISTS idx_route_research_outcome_due
ON opportunity_route_research_outcomes(status, target_at, acquisition_run_key, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_route_research_schema() -> None:
    key = _database_cache_key()
    if key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(key)


def _decision_key(episode: MarketOpportunityEpisode) -> str:
    return f"route-research-decision:v1:{episode.acquisition_run_key}:{episode.episode_key}"


def _outcome_key(decision: RouteResearchDecision, horizon_seconds: int) -> str:
    return (
        f"route-research-outcome:v1:{decision.acquisition_run_key}:"
        f"{decision.episode_key}:{int(horizon_seconds)}s"
    )


def _row_to_decision(row) -> RouteResearchDecision:
    return RouteResearchDecision(
        decision_key=str(row["decision_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        token_mint=str(row["token_mint"]),
        episode_t0=int(row["episode_t0"]),
        research_decision_as_of=int(row["research_decision_as_of"]),
        entry_quote_key=str(row["entry_quote_key"]),
        hazard_attempt_key=str(row["hazard_attempt_key"]),
        method_version=str(row["method_version"]),
    )


def _row_to_outcome(row) -> RouteResearchForwardOutcome:
    return RouteResearchForwardOutcome(
        outcome_key=str(row["outcome_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        token_mint=str(row["token_mint"]),
        research_decision_as_of=int(row["research_decision_as_of"]),
        horizon_seconds=int(row["horizon_seconds"]),
        target_at=int(row["target_at"]),
        status=str(row["status"]),
        observed_at=(int(row["observed_at"]) if row["observed_at"] is not None else None),
        quote_key=(str(row["quote_key"]) if row["quote_key"] is not None else None),
        error_type=(str(row["error_type"]) if row["error_type"] is not None else None),
        error_message=(str(row["error_message"]) if row["error_message"] is not None else None),
    )


def _load_decision_row(conn, *, acquisition_run_key: str, episode_key: str):
    return conn.execute(
        """SELECT decision_key, acquisition_run_key, episode_key, token_mint,
            episode_t0, research_decision_as_of, entry_quote_key, hazard_attempt_key,
            method_version
        FROM opportunity_route_research_decisions
        WHERE acquisition_run_key=? AND episode_key=?""",
        (acquisition_run_key, episode_key),
    ).fetchone()


def freeze_route_research_decision(
    *,
    episode: MarketOpportunityEpisode,
    entry_attempt: OpportunityProviderAttempt,
    hazard_attempt: OpportunityProviderAttempt,
    horizons_seconds: tuple[int, ...] = ROUTE_RESEARCH_HORIZONS_SECONDS,
) -> RouteResearchDecision:
    """Freeze a research-only causal decision clock without touching official ``decision_as_of``.

    The entry artifact must be a non-executable route-only BUY. Hazard must be the frozen v37
    on-chain provider. This decision is for paper causal research only and cannot satisfy the
    official funded executable-entry gate.
    """

    if entry_attempt.episode_key != episode.episode_key:
        raise ValueError("research entry attempt episode mismatch")
    if (entry_attempt.provider, entry_attempt.purpose) != (
        JUPITER_RESEARCH_ENTRY_PROVIDER,
        JUPITER_RESEARCH_ENTRY_PURPOSE,
    ):
        raise ValueError("wrong research entry provider/purpose")
    if entry_attempt.status != "AVAILABLE" or entry_attempt.completed_at is None:
        raise ValueError("research entry route is not terminal AVAILABLE")
    if not bool((entry_attempt.details or {}).get("route_only")):
        raise ValueError("research entry attempt is not explicitly route-only")
    if bool((entry_attempt.details or {}).get("assembled_transaction_present")):
        raise ValueError("route research entry cannot contain assembled transaction")
    entry_quote_key = str(entry_attempt.artifact_key or "").strip()
    if not entry_quote_key:
        raise ValueError("research entry quote artifact missing")
    entry_rows = load_causal_quotes(quote_keys=(entry_quote_key,))
    if len(entry_rows) != 1:
        raise ValueError("research entry quote artifact missing or ambiguous")
    entry_quote = entry_rows[0]
    if (
        entry_quote.token_mint != episode.token_mint
        or entry_quote.side != "buy"
        or entry_quote.executable
        or entry_quote.observed_at < episode.first_trigger_observed_at
    ):
        raise ValueError("research entry quote violates route-only causal lineage")

    if hazard_attempt.episode_key != episode.episode_key:
        raise ValueError("hazard attempt episode mismatch")
    if (hazard_attempt.provider, hazard_attempt.purpose) != (
        ONCHAIN_HAZARD_PROVIDER,
        ONCHAIN_HAZARD_PURPOSE,
    ):
        raise ValueError("wrong hazard provider/purpose")
    if hazard_attempt.status != "AVAILABLE" or hazard_attempt.completed_at is None:
        raise ValueError("research decision requires AVAILABLE on-chain hazard core")
    hazard_token = str((hazard_attempt.details or {}).get("token_mint") or "")
    if hazard_token != episode.token_mint:
        raise ValueError("hazard token does not match episode")

    clocks = [
        int(episode.first_trigger_observed_at),
        int(entry_attempt.completed_at),
        int(entry_quote.observed_at),
        int(hazard_attempt.completed_at),
    ]
    hazard_observed = (hazard_attempt.details or {}).get("observed_at")
    if hazard_observed is not None:
        clocks.append(int(hazard_observed))
    decision_as_of = max(clocks)

    horizons = tuple(int(item) for item in horizons_seconds)
    if not horizons or len(set(horizons)) != len(horizons) or any(item <= 0 for item in horizons):
        raise ValueError("research horizons must be unique positive seconds")
    if any(item not in ROUTE_RESEARCH_HORIZONS_SECONDS for item in horizons):
        raise ValueError("research horizon must be one of 300, 900 or 3600 seconds")

    ensure_route_research_schema()
    key = _decision_key(episode)
    with connection() as conn:
        existing = _load_decision_row(
            conn,
            acquisition_run_key=episode.acquisition_run_key,
            episode_key=episode.episode_key,
        )
        if existing is not None:
            stored = _row_to_decision(existing)
            expected = (
                episode.token_mint,
                int(episode.first_trigger_observed_at),
                decision_as_of,
                entry_quote_key,
                hazard_attempt.attempt_key,
                ROUTE_RESEARCH_VERSION,
            )
            actual = (
                stored.token_mint,
                stored.episode_t0,
                stored.research_decision_as_of,
                stored.entry_quote_key,
                stored.hazard_attempt_key,
                stored.method_version,
            )
            if actual != expected:
                raise ValueError("route research decision is already frozen with different lineage")
            decision = stored
        else:
            conn.execute(
                """INSERT INTO opportunity_route_research_decisions(
                    decision_key, acquisition_run_key, episode_key, token_mint,
                    episode_t0, research_decision_as_of, entry_quote_key,
                    hazard_attempt_key, method_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    episode.acquisition_run_key,
                    episode.episode_key,
                    episode.token_mint,
                    int(episode.first_trigger_observed_at),
                    decision_as_of,
                    entry_quote_key,
                    hazard_attempt.attempt_key,
                    ROUTE_RESEARCH_VERSION,
                ),
            )
            decision = RouteResearchDecision(
                decision_key=key,
                acquisition_run_key=episode.acquisition_run_key,
                episode_key=episode.episode_key,
                token_mint=episode.token_mint,
                episode_t0=int(episode.first_trigger_observed_at),
                research_decision_as_of=decision_as_of,
                entry_quote_key=entry_quote_key,
                hazard_attempt_key=hazard_attempt.attempt_key,
                method_version=ROUTE_RESEARCH_VERSION,
            )

        for horizon in horizons:
            target = decision.research_decision_as_of + horizon
            outcome_key = _outcome_key(decision, horizon)
            row = conn.execute(
                """SELECT research_decision_as_of, target_at
                FROM opportunity_route_research_outcomes
                WHERE acquisition_run_key=? AND episode_key=? AND horizon_seconds=?""",
                (decision.acquisition_run_key, decision.episode_key, horizon),
            ).fetchone()
            if row is not None:
                if (
                    int(row["research_decision_as_of"]) != decision.research_decision_as_of
                    or int(row["target_at"]) != target
                ):
                    raise ValueError("route research outcome schedule conflicts with frozen decision")
                continue
            conn.execute(
                """INSERT INTO opportunity_route_research_outcomes(
                    outcome_key, acquisition_run_key, episode_key, token_mint,
                    research_decision_as_of, horizon_seconds, target_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                (
                    outcome_key,
                    decision.acquisition_run_key,
                    decision.episode_key,
                    decision.token_mint,
                    decision.research_decision_as_of,
                    horizon,
                    target,
                ),
            )

    return decision


def load_route_research_decision(
    *, acquisition_run_key: str, episode_key: str
) -> RouteResearchDecision | None:
    run_key = str(acquisition_run_key).strip()
    episode = str(episode_key).strip()
    if not run_key or not episode:
        raise ValueError("run and episode keys are required")
    ensure_route_research_schema()
    with connection() as conn:
        row = _load_decision_row(conn, acquisition_run_key=run_key, episode_key=episode)
    return _row_to_decision(row) if row is not None else None


def load_route_research_outcomes(
    *, acquisition_run_key: str, episode_key: str | None = None
) -> tuple[RouteResearchForwardOutcome, ...]:
    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    ensure_route_research_schema()
    query = """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
        research_decision_as_of, horizon_seconds, target_at, status,
        observed_at, quote_key, error_type, error_message
        FROM opportunity_route_research_outcomes WHERE acquisition_run_key=?"""
    params: list[object] = [run_key]
    if episode_key is not None:
        episode = str(episode_key).strip()
        if not episode:
            raise ValueError("episode_key cannot be empty")
        query += " AND episode_key=?"
        params.append(episode)
    query += " ORDER BY target_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(_row_to_outcome(row) for row in rows)


def load_due_route_research_outcomes(
    *, acquisition_run_key: str, as_of: int, limit: int = 100
) -> tuple[RouteResearchForwardOutcome, ...]:
    run_key = str(acquisition_run_key).strip()
    cutoff = int(as_of)
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    if cutoff < 0 or limit <= 0:
        raise ValueError("invalid due-outcome cutoff/limit")
    ensure_route_research_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
                research_decision_as_of, horizon_seconds, target_at, status,
                observed_at, quote_key, error_type, error_message
            FROM opportunity_route_research_outcomes
            WHERE acquisition_run_key=? AND status='PENDING' AND target_at<=?
            ORDER BY target_at, id LIMIT ?""",
            (run_key, cutoff, int(limit)),
        ).fetchall()
    return tuple(_row_to_outcome(row) for row in rows)


def complete_route_research_outcome(
    *,
    outcome_key: str,
    status: str,
    observed_at: int,
    quote_key: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> RouteResearchForwardOutcome:
    key = str(outcome_key).strip()
    final_status = str(status).strip()
    if not key:
        raise ValueError("outcome_key cannot be empty")
    if final_status not in ROUTE_RESEARCH_FINAL_STATUSES:
        raise ValueError("unsupported route research outcome status")
    observed = int(observed_at)
    normalized_quote = str(quote_key).strip() if quote_key is not None else None
    if normalized_quote == "":
        normalized_quote = None
    normalized_error_type = str(error_type).strip() if error_type is not None else None
    normalized_error_message = str(error_message).strip()[:1000] if error_message is not None else None

    ensure_route_research_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT acquisition_run_key, episode_key, token_mint,
                research_decision_as_of, horizon_seconds, target_at, status,
                observed_at, quote_key, error_type, error_message
            FROM opportunity_route_research_outcomes WHERE outcome_key=?""",
            (key,),
        ).fetchone()
        if row is None:
            raise ValueError("route research outcome was not scheduled")
        target = int(row["target_at"])
        if observed < target:
            raise ValueError("route research outcome cannot precede exact target")

        if final_status == "AVAILABLE":
            if normalized_quote is None:
                raise ValueError("AVAILABLE route research outcome requires quote artifact")
            quotes = load_causal_quotes(quote_keys=(normalized_quote,))
            if len(quotes) != 1:
                raise ValueError("route research SELL quote artifact missing or ambiguous")
            quote = quotes[0]
            if (
                quote.token_mint != str(row["token_mint"])
                or quote.side != "sell"
                or quote.executable
                or quote.observed_at < target
                or quote.observed_at != observed
            ):
                raise ValueError("AVAILABLE route research outcome requires causal non-executable SELL quote")

        existing_status = str(row["status"])
        if existing_status != "PENDING":
            expected = (
                final_status,
                observed,
                normalized_quote,
                normalized_error_type,
                normalized_error_message,
            )
            actual = (
                existing_status,
                int(row["observed_at"]),
                row["quote_key"],
                row["error_type"],
                row["error_message"],
            )
            if actual != expected:
                raise ValueError("completed route research outcome is immutable")
        else:
            conn.execute(
                """UPDATE opportunity_route_research_outcomes
                SET status=?, observed_at=?, quote_key=?, error_type=?, error_message=?,
                    updated_at=CURRENT_TIMESTAMP WHERE outcome_key=?""",
                (
                    final_status,
                    observed,
                    normalized_quote,
                    normalized_error_type,
                    normalized_error_message,
                    key,
                ),
            )

        loaded = conn.execute(
            """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
                research_decision_as_of, horizon_seconds, target_at, status,
                observed_at, quote_key, error_type, error_message
            FROM opportunity_route_research_outcomes WHERE outcome_key=?""",
            (key,),
        ).fetchone()
    if loaded is None:
        raise RuntimeError("route research outcome disappeared after completion")
    return _row_to_outcome(loaded)
