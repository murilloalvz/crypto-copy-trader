from dataclasses import dataclass

from src.database import connection


DEFAULT_EPISODE_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class OpportunityEpisode:
    episode_key: str
    acquisition_run_key: str
    token_mint: str
    first_trigger_observation_key: str
    first_trigger_chain_time: int
    first_trigger_observed_at: int
    episode_closes_at: int
    decision_as_of: int | None


@dataclass(frozen=True)
class OpportunityEpisodeTrigger:
    acquisition_run_key: str
    episode_key: str
    observation_key: str
    wallet_address: str
    token_mint: str
    chain_time: int
    observed_at: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    first_trigger_observation_key TEXT NOT NULL,
    first_trigger_chain_time INTEGER NOT NULL,
    first_trigger_observed_at INTEGER NOT NULL,
    episode_closes_at INTEGER NOT NULL,
    decision_as_of INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, first_trigger_observation_key)
);

CREATE INDEX IF NOT EXISTS idx_opportunity_episodes_run_token_time
ON opportunity_episodes(acquisition_run_key, token_mint, first_trigger_observed_at, id);

CREATE TABLE IF NOT EXISTS opportunity_episode_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    observation_key TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    chain_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, observation_key)
);

CREATE INDEX IF NOT EXISTS idx_opportunity_episode_triggers_episode
ON opportunity_episode_triggers(episode_key, observed_at, id);
"""


def ensure_opportunity_episode_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _row_to_episode(row) -> OpportunityEpisode:
    return OpportunityEpisode(
        episode_key=str(row["episode_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        token_mint=str(row["token_mint"]),
        first_trigger_observation_key=str(row["first_trigger_observation_key"]),
        first_trigger_chain_time=int(row["first_trigger_chain_time"]),
        first_trigger_observed_at=int(row["first_trigger_observed_at"]),
        episode_closes_at=int(row["episode_closes_at"]),
        decision_as_of=(
            int(row["decision_as_of"])
            if row["decision_as_of"] is not None
            else None
        ),
    )


def get_opportunity_episode(episode_key: str) -> OpportunityEpisode | None:
    key = _required(episode_key, "episode_key")
    ensure_opportunity_episode_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_observation_key, first_trigger_chain_time,
                first_trigger_observed_at, episode_closes_at, decision_as_of
            FROM opportunity_episodes WHERE episode_key=?""",
            (key,),
        ).fetchone()
    return _row_to_episode(row) if row is not None else None


def assign_opportunity_trigger(
    *,
    acquisition_run_key: str,
    observation_key: str,
    wallet_address: str,
    token_mint: str,
    chain_time: int,
    observed_at: int,
    episode_window_seconds: int = DEFAULT_EPISODE_WINDOW_SECONDS,
) -> OpportunityEpisode:
    """Persist one raw BUY trigger and deterministically attach it to a live episode.

    Episode membership is based on the bot's causal availability clock (`observed_at`), not on
    future outcomes. A trigger at exactly `episode_closes_at` starts a new episode. Repeating the
    same observation is idempotent. Different acquisition runs can never share an episode.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    obs_key = _required(observation_key, "observation_key")
    wallet = _required(wallet_address, "wallet_address")
    mint = _required(token_mint, "token_mint")
    if chain_time < 0 or observed_at < 0:
        raise ValueError("trigger timestamps must be non-negative")
    if observed_at < chain_time:
        raise ValueError("trigger observed_at cannot precede chain_time")
    if episode_window_seconds <= 0:
        raise ValueError("episode_window_seconds must be positive")

    ensure_opportunity_episode_schema()
    with connection() as conn:
        existing_trigger = conn.execute(
            """SELECT episode_key, wallet_address, token_mint, chain_time, observed_at
            FROM opportunity_episode_triggers
            WHERE acquisition_run_key=? AND observation_key=?""",
            (run_key, obs_key),
        ).fetchone()
        if existing_trigger is not None:
            if (
                str(existing_trigger["wallet_address"]) != wallet
                or str(existing_trigger["token_mint"]) != mint
                or int(existing_trigger["chain_time"]) != chain_time
                or int(existing_trigger["observed_at"]) != observed_at
            ):
                raise ValueError("opportunity trigger already exists with different data")
            row = conn.execute(
                """SELECT episode_key, acquisition_run_key, token_mint,
                    first_trigger_observation_key, first_trigger_chain_time,
                    first_trigger_observed_at, episode_closes_at, decision_as_of
                FROM opportunity_episodes WHERE episode_key=?""",
                (str(existing_trigger["episode_key"]),),
            ).fetchone()
            if row is None:
                raise RuntimeError("trigger references missing opportunity episode")
            return _row_to_episode(row)

        row = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_observation_key, first_trigger_chain_time,
                first_trigger_observed_at, episode_closes_at, decision_as_of
            FROM opportunity_episodes
            WHERE acquisition_run_key=? AND token_mint=?
              AND first_trigger_observed_at<=?
              AND episode_closes_at>?
            ORDER BY first_trigger_observed_at DESC, id DESC
            LIMIT 1""",
            (run_key, mint, observed_at, observed_at),
        ).fetchone()

        if row is None:
            episode_key = f"opportunity:{run_key}:{obs_key}"
            closes_at = observed_at + episode_window_seconds
            conn.execute(
                """INSERT INTO opportunity_episodes(
                    episode_key, acquisition_run_key, token_mint,
                    first_trigger_observation_key, first_trigger_chain_time,
                    first_trigger_observed_at, episode_closes_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    episode_key,
                    run_key,
                    mint,
                    obs_key,
                    chain_time,
                    observed_at,
                    closes_at,
                ),
            )
            row = conn.execute(
                """SELECT episode_key, acquisition_run_key, token_mint,
                    first_trigger_observation_key, first_trigger_chain_time,
                    first_trigger_observed_at, episode_closes_at, decision_as_of
                FROM opportunity_episodes WHERE episode_key=?""",
                (episode_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to persist opportunity episode")

        episode = _row_to_episode(row)
        conn.execute(
            """INSERT INTO opportunity_episode_triggers(
                acquisition_run_key, episode_key, observation_key,
                wallet_address, token_mint, chain_time, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_key,
                episode.episode_key,
                obs_key,
                wallet,
                mint,
                chain_time,
                observed_at,
            ),
        )
        return episode


def freeze_opportunity_decision_as_of(
    episode_key: str,
    *,
    decision_as_of: int,
) -> OpportunityEpisode:
    """Freeze the decision-time information boundary exactly once."""

    if decision_as_of < 0:
        raise ValueError("decision_as_of must be non-negative")
    key = _required(episode_key, "episode_key")
    ensure_opportunity_episode_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_observation_key, first_trigger_chain_time,
                first_trigger_observed_at, episode_closes_at, decision_as_of
            FROM opportunity_episodes WHERE episode_key=?""",
            (key,),
        ).fetchone()
        if row is None:
            raise ValueError(f"opportunity episode not found: {key}")
        episode = _row_to_episode(row)
        if decision_as_of < episode.first_trigger_observed_at:
            raise ValueError("decision_as_of cannot precede first trigger observation")
        if episode.decision_as_of is not None:
            if episode.decision_as_of != decision_as_of:
                raise ValueError("decision_as_of is already frozen with a different value")
            return episode
        conn.execute(
            """UPDATE opportunity_episodes
            SET decision_as_of=?, updated_at=CURRENT_TIMESTAMP
            WHERE episode_key=? AND decision_as_of IS NULL""",
            (decision_as_of, key),
        )

    frozen = get_opportunity_episode(key)
    if frozen is None:
        raise RuntimeError("opportunity episode disappeared after freeze")
    return frozen


def load_opportunity_episode_triggers(
    episode_key: str,
    *,
    as_of: int | None = None,
) -> tuple[OpportunityEpisodeTrigger, ...]:
    """Load raw triggers, optionally enforcing a causal availability cutoff."""

    key = _required(episode_key, "episode_key")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")
    ensure_opportunity_episode_schema()
    query = """SELECT acquisition_run_key, episode_key, observation_key,
        wallet_address, token_mint, chain_time, observed_at
        FROM opportunity_episode_triggers WHERE episode_key=?"""
    params: list[object] = [key]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(as_of)
    query += " ORDER BY observed_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(
        OpportunityEpisodeTrigger(
            acquisition_run_key=str(row["acquisition_run_key"]),
            episode_key=str(row["episode_key"]),
            observation_key=str(row["observation_key"]),
            wallet_address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
        )
        for row in rows
    )
