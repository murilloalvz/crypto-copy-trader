import json
from dataclasses import dataclass

from src.database import connection


@dataclass(frozen=True)
class ShadowRun:
    id: int
    run_key: str
    strategy_version: str
    activated_at: int
    config_json: str
    status: str
    notes: str | None


@dataclass(frozen=True)
class ShadowDecision:
    decision_key: str
    token_mint: str
    side: str
    decided_at: int
    quote_observed_at: int
    quote_source: str
    market_price_usd: float
    expected_execution_price_usd: float
    notional_usd: float
    reason: str
    context_json: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL UNIQUE,
    strategy_version TEXT NOT NULL,
    activated_at INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shadow_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    decision_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    side TEXT NOT NULL,
    decided_at INTEGER NOT NULL,
    quote_observed_at INTEGER NOT NULL,
    quote_source TEXT NOT NULL,
    market_price_usd REAL NOT NULL,
    expected_execution_price_usd REAL NOT NULL,
    notional_usd REAL NOT NULL,
    reason TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, decision_key),
    FOREIGN KEY (run_id) REFERENCES shadow_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_decisions_run_time
ON shadow_decisions(run_id, decided_at);
"""


def ensure_shadow_execution_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def start_shadow_run(
    *,
    run_key: str,
    strategy_version: str,
    activated_at: int,
    config: dict,
    notes: str | None = None,
) -> ShadowRun:
    if not run_key.strip():
        raise ValueError("run_key cannot be empty")
    if not strategy_version.strip():
        raise ValueError("strategy_version cannot be empty")
    if activated_at < 0:
        raise ValueError("activated_at must be non-negative")
    config_json = _canonical_json(config)

    ensure_shadow_execution_schema()
    with connection() as conn:
        existing = conn.execute(
            """SELECT id, run_key, strategy_version, activated_at, config_json, status, notes
            FROM shadow_runs WHERE run_key=?""",
            (run_key.strip(),),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["strategy_version"]) != strategy_version.strip()
                or int(existing["activated_at"]) != activated_at
                or str(existing["config_json"]) != config_json
            ):
                raise ValueError("existing shadow run cannot be silently reconfigured")
            return ShadowRun(
                id=int(existing["id"]),
                run_key=str(existing["run_key"]),
                strategy_version=str(existing["strategy_version"]),
                activated_at=int(existing["activated_at"]),
                config_json=str(existing["config_json"]),
                status=str(existing["status"]),
                notes=existing["notes"],
            )

        cursor = conn.execute(
            """INSERT INTO shadow_runs(run_key, strategy_version, activated_at, config_json, notes)
            VALUES (?, ?, ?, ?, ?)""",
            (run_key.strip(), strategy_version.strip(), activated_at, config_json, notes),
        )
        run_id = int(cursor.lastrowid)
    return ShadowRun(
        id=run_id,
        run_key=run_key.strip(),
        strategy_version=strategy_version.strip(),
        activated_at=activated_at,
        config_json=config_json,
        status="active",
        notes=notes,
    )


def record_shadow_decision(run_id: int, decision: ShadowDecision) -> bool:
    if run_id < 1:
        raise ValueError("run_id must be >= 1")
    if not decision.decision_key.strip():
        raise ValueError("decision_key cannot be empty")
    if not decision.token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if decision.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if decision.decided_at < 0 or decision.quote_observed_at < 0:
        raise ValueError("decision timestamps must be non-negative")
    if decision.quote_observed_at > decision.decided_at:
        raise ValueError("decision cannot use a quote observed in the future")
    if not decision.quote_source.strip():
        raise ValueError("quote_source cannot be empty")
    if decision.market_price_usd <= 0 or decision.expected_execution_price_usd <= 0:
        raise ValueError("shadow prices must be positive")
    if decision.notional_usd <= 0:
        raise ValueError("notional_usd must be positive")
    if not decision.reason.strip():
        raise ValueError("reason cannot be empty")
    try:
        context = json.loads(decision.context_json)
    except json.JSONDecodeError as exc:
        raise ValueError("context_json must be valid JSON") from exc
    if not isinstance(context, dict):
        raise ValueError("context_json must contain a JSON object")

    ensure_shadow_execution_schema()
    with connection() as conn:
        run = conn.execute(
            "SELECT activated_at, status FROM shadow_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("shadow run not found")
        if str(run["status"]) != "active":
            raise ValueError("shadow run is not active")
        if decision.decided_at < int(run["activated_at"]):
            raise ValueError("decision cannot predate shadow run activation")
        cursor = conn.execute(
            """INSERT OR IGNORE INTO shadow_decisions(
                run_id, decision_key, token_mint, side, decided_at, quote_observed_at,
                quote_source, market_price_usd, expected_execution_price_usd,
                notional_usd, reason, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                decision.decision_key.strip(),
                decision.token_mint.strip(),
                decision.side,
                decision.decided_at,
                decision.quote_observed_at,
                decision.quote_source.strip(),
                decision.market_price_usd,
                decision.expected_execution_price_usd,
                decision.notional_usd,
                decision.reason.strip(),
                _canonical_json(context),
            ),
        )
        return cursor.rowcount == 1


def close_shadow_run(run_id: int) -> None:
    if run_id < 1:
        raise ValueError("run_id must be >= 1")
    ensure_shadow_execution_schema()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE shadow_runs SET status='closed' WHERE id=? AND status='active'",
            (run_id,),
        )
        if cursor.rowcount != 1:
            raise ValueError("active shadow run not found")


def load_shadow_decisions(run_id: int) -> list[ShadowDecision]:
    if run_id < 1:
        raise ValueError("run_id must be >= 1")
    ensure_shadow_execution_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT decision_key, token_mint, side, decided_at, quote_observed_at,
            quote_source, market_price_usd, expected_execution_price_usd,
            notional_usd, reason, context_json
            FROM shadow_decisions WHERE run_id=? ORDER BY decided_at, id""",
            (run_id,),
        ).fetchall()
    return [
        ShadowDecision(
            decision_key=str(row["decision_key"]),
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
            decided_at=int(row["decided_at"]),
            quote_observed_at=int(row["quote_observed_at"]),
            quote_source=str(row["quote_source"]),
            market_price_usd=float(row["market_price_usd"]),
            expected_execution_price_usd=float(row["expected_execution_price_usd"]),
            notional_usd=float(row["notional_usd"]),
            reason=str(row["reason"]),
            context_json=str(row["context_json"]),
        )
        for row in rows
    ]
