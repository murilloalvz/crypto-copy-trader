from dataclasses import dataclass

from src.database import connection


RPC_HEALTH_STATUSES = {"FAILURE", "RECOVERED"}
RPC_HEALTH_PHASES = {"bootstrap", "poll"}


@dataclass(frozen=True)
class WalletForwardRpcHealthEvent:
    id: int
    run_key: str
    observed_at: int
    wallet_address: str
    phase: str
    status: str
    rpc_endpoint: str | None
    error_type: str | None
    error_message: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_forward_rpc_health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL,
    observed_at INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    rpc_endpoint TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_forward_rpc_health_run_time
ON wallet_forward_rpc_health_events(run_key, observed_at, id);
"""


def ensure_wallet_forward_rpc_health_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _normalize_required(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _record_event(
    *,
    run_key: str,
    observed_at: int,
    wallet_address: str,
    phase: str,
    status: str,
    rpc_endpoint: str | None = None,
    error: BaseException | None = None,
) -> None:
    key = _normalize_required(run_key, "run_key")
    address = _normalize_required(wallet_address, "wallet_address")
    normalized_phase = _normalize_required(phase, "phase")
    if normalized_phase not in RPC_HEALTH_PHASES:
        raise ValueError("invalid wallet forward RPC health phase")
    normalized_status = _normalize_required(status, "status")
    if normalized_status not in RPC_HEALTH_STATUSES:
        raise ValueError("invalid wallet forward RPC health status")
    if observed_at < 0:
        raise ValueError("observed_at must be non-negative")

    endpoint = str(rpc_endpoint).strip() if rpc_endpoint else None
    error_type = type(error).__name__ if error is not None else None
    error_message = str(error) if error is not None else None
    if normalized_status == "FAILURE" and error is None:
        raise ValueError("FAILURE event requires an error")
    if normalized_status == "RECOVERED" and error is not None:
        raise ValueError("RECOVERED event cannot include an error")

    ensure_wallet_forward_rpc_health_schema()
    with connection() as conn:
        conn.execute(
            """INSERT INTO wallet_forward_rpc_health_events(
                run_key, observed_at, wallet_address, phase, status,
                rpc_endpoint, error_type, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                observed_at,
                address,
                normalized_phase,
                normalized_status,
                endpoint,
                error_type,
                error_message,
            ),
        )


def record_wallet_forward_rpc_failure(
    *,
    run_key: str,
    observed_at: int,
    wallet_address: str,
    phase: str,
    error: BaseException,
) -> None:
    _record_event(
        run_key=run_key,
        observed_at=observed_at,
        wallet_address=wallet_address,
        phase=phase,
        status="FAILURE",
        error=error,
    )


def record_wallet_forward_rpc_recovery(
    *,
    run_key: str,
    observed_at: int,
    wallet_address: str,
    phase: str,
    rpc_endpoint: str | None,
) -> None:
    _record_event(
        run_key=run_key,
        observed_at=observed_at,
        wallet_address=wallet_address,
        phase=phase,
        status="RECOVERED",
        rpc_endpoint=rpc_endpoint,
    )


def list_wallet_forward_rpc_health_events(run_key: str) -> list[WalletForwardRpcHealthEvent]:
    key = _normalize_required(run_key, "run_key")
    ensure_wallet_forward_rpc_health_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, run_key, observed_at, wallet_address, phase, status,
                      rpc_endpoint, error_type, error_message
               FROM wallet_forward_rpc_health_events
               WHERE run_key=?
               ORDER BY observed_at, id""",
            (key,),
        ).fetchall()
    return [
        WalletForwardRpcHealthEvent(
            id=int(row["id"]),
            run_key=str(row["run_key"]),
            observed_at=int(row["observed_at"]),
            wallet_address=str(row["wallet_address"]),
            phase=str(row["phase"]),
            status=str(row["status"]),
            rpc_endpoint=str(row["rpc_endpoint"]) if row["rpc_endpoint"] else None,
            error_type=str(row["error_type"]) if row["error_type"] else None,
            error_message=str(row["error_message"]) if row["error_message"] else None,
        )
        for row in rows
    ]
