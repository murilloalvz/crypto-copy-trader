"""Live paper signal log v0 (RESERVE 1, self-check only -- no live wiring).

Stage 3 of the signal-first roadmap (docs/signal-first-human-execution-roadmap-2026-09-08.md):
"the bot logs real-time signals and measures the outcome WITHOUT trading."

This module never sends a transaction, never holds a private key, and never
places an order. It only persists two append-only, idempotent records per
signal:

1. `record_signal`: written the moment a signal is detected, before any
   outcome is known. Freezes the params that will later be used to measure
   that signal's outcome (entry/exit latency, window, size, exit rule, cost
   model) so they cannot be silently changed after the fact -- same
   discipline as `src/shadow_execution_store.py`'s frozen run config.
2. `record_outcome`: written later, once real trades are available, by
   calling `evaluate_paper_signal_outcome` which is a thin wrapper around the
   existing causal F2 primitives in `src/opportunity_path_metrics_v0.py`
   (`find_causal_entry`, `first_barrier_touch`, `simulate_exit`). The first
   persisted outcome is canonical (systems invariant 7); a second call with
   the same signal_id is ignored, never overwritten.

Deliberately out of scope here (future, separately authorized work): wiring
this to a real-time detector/RPC feed. There is no "run live" entrypoint in
this file on purpose -- the only way to exercise it is `--self-check`, which
uses synthetic trades and never touches the network.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Sequence

from src.database import connection
from src.opportunity_path_metrics_v0 import (
    CostModel,
    PathTrade,
    find_causal_entry,
    first_barrier_touch,
    simulate_exit,
)

VERSION = "live_paper_log_v0"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sig_fast_live_paper_signal_v0 (
    signal_id TEXT PRIMARY KEY,
    token_mint TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    decision_as_of INTEGER NOT NULL,
    strategy_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sig_fast_live_paper_outcome_v0 (
    signal_id TEXT PRIMARY KEY,
    measured_at INTEGER NOT NULL,
    barrier_result TEXT NOT NULL,
    exit_rule_id TEXT NOT NULL,
    gross_return_pct REAL,
    net_return_pct REAL,
    missing_reason TEXT,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES sig_fast_live_paper_signal_v0(signal_id)
);
"""


def ensure_live_paper_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class PaperSignal:
    signal_id: str
    token_mint: str
    detected_at: int
    decision_as_of: int
    strategy_version: str
    config: dict
    context: dict


@dataclass(frozen=True)
class PaperOutcome:
    signal_id: str
    measured_at: int
    barrier_result: str
    exit_rule_id: str
    gross_return_pct: float | None
    net_return_pct: float | None
    missing_reason: str | None


def record_signal(signal: PaperSignal) -> bool:
    """Persist a signal at detection time. Returns True if newly inserted,
    False if an identical signal_id already existed. Raises if the same
    signal_id is replayed with different content (no silent reconfiguration,
    mirrors shadow_execution_store's frozen-run guard)."""

    if not signal.signal_id.strip():
        raise ValueError("signal_id cannot be empty")
    if not signal.token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if signal.detected_at < 0 or signal.decision_as_of < 0:
        raise ValueError("timestamps must be non-negative")
    if signal.decision_as_of < signal.detected_at:
        raise ValueError("decision_as_of cannot predate detected_at (no lookahead)")
    if not signal.strategy_version.strip():
        raise ValueError("strategy_version cannot be empty")
    config_json = _canonical_json(signal.config)
    context_json = _canonical_json(signal.context)

    ensure_live_paper_schema()
    with connection() as conn:
        existing = conn.execute(
            """SELECT token_mint, detected_at, decision_as_of, strategy_version,
            config_json, context_json
            FROM sig_fast_live_paper_signal_v0 WHERE signal_id=?""",
            (signal.signal_id,),
        ).fetchone()
        if existing is not None:
            unchanged = (
                str(existing["token_mint"]) == signal.token_mint
                and int(existing["detected_at"]) == signal.detected_at
                and int(existing["decision_as_of"]) == signal.decision_as_of
                and str(existing["strategy_version"]) == signal.strategy_version
                and str(existing["config_json"]) == config_json
                and str(existing["context_json"]) == context_json
            )
            if not unchanged:
                raise ValueError("existing paper signal cannot be silently reconfigured")
            return False

        conn.execute(
            """INSERT INTO sig_fast_live_paper_signal_v0(
                signal_id, token_mint, detected_at, decision_as_of,
                strategy_version, config_json, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.signal_id,
                signal.token_mint,
                signal.detected_at,
                signal.decision_as_of,
                signal.strategy_version,
                config_json,
                context_json,
            ),
        )
    return True


def load_signal(signal_id: str) -> PaperSignal | None:
    ensure_live_paper_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT signal_id, token_mint, detected_at, decision_as_of,
            strategy_version, config_json, context_json
            FROM sig_fast_live_paper_signal_v0 WHERE signal_id=?""",
            (signal_id,),
        ).fetchone()
    if row is None:
        return None
    return PaperSignal(
        signal_id=str(row["signal_id"]),
        token_mint=str(row["token_mint"]),
        detected_at=int(row["detected_at"]),
        decision_as_of=int(row["decision_as_of"]),
        strategy_version=str(row["strategy_version"]),
        config=json.loads(row["config_json"]),
        context=json.loads(row["context_json"]),
    )


def evaluate_paper_signal_outcome(
    trades: Sequence[PathTrade],
    *,
    signal: PaperSignal,
    measured_at: int,
) -> PaperOutcome:
    """Pure function: measures what happened after `signal`, using only the
    causal F2 primitives. Never places a trade; `trades` is whatever has
    actually been observed on-chain by `measured_at`. If not enough time/
    trades have accumulated yet, this surfaces as an explicit missing_reason
    (from F2 itself), never as a fabricated return."""

    config = signal.config
    cost_model = CostModel(
        venue_fee_pct=config["venue_fee_pct"],
        terminal_fee_pct=config["terminal_fee_pct"],
        network_fee_sol=config.get("network_fee_sol", 0.0003),
        ata_fee_sol=config.get("ata_fee_sol", 0.0),
    )

    entry = find_causal_entry(
        trades,
        signal_time=signal.decision_as_of,
        entry_latency_seconds=config["entry_latency_seconds"],
        size_sol=config["size_sol"],
        cost_model=cost_model,
    )
    if entry.execution_price_sol is None:
        return PaperOutcome(
            signal_id=signal.signal_id,
            measured_at=measured_at,
            barrier_result="NOT_AVAILABLE",
            exit_rule_id=config["exit_rule_id"],
            gross_return_pct=None,
            net_return_pct=None,
            missing_reason=entry.missing_reason or "entry_unavailable",
        )

    barrier = first_barrier_touch(
        trades,
        entry_chain_time=entry.trade_chain_time,
        entry_execution_price_sol=entry.execution_price_sol,
        window_seconds=config["window_seconds"],
        target_pct=config["target_pct"],
        stop_pct=config["stop_pct"],
    )
    exit_result = simulate_exit(
        trades,
        rule_id=config["exit_rule_id"],
        entry_chain_time=entry.trade_chain_time,
        entry_execution_price_sol=entry.execution_price_sol,
        size_sol=config["size_sol"],
        window_seconds=config["window_seconds"],
        exit_latency_seconds=config["exit_latency_seconds"],
        cost_model=cost_model,
    )
    return PaperOutcome(
        signal_id=signal.signal_id,
        measured_at=measured_at,
        barrier_result=barrier,
        exit_rule_id=exit_result.rule_id,
        gross_return_pct=exit_result.gross_return_pct,
        net_return_pct=exit_result.net_return_pct,
        missing_reason=exit_result.missing_reason,
    )


def record_outcome(outcome: PaperOutcome) -> bool:
    """Idempotent: the first persisted outcome for a signal_id is canonical.
    Returns True if newly inserted, False if one already existed (never
    overwritten, regardless of content)."""

    if outcome.measured_at < 0:
        raise ValueError("measured_at must be non-negative")

    ensure_live_paper_schema()
    with connection() as conn:
        signal_row = conn.execute(
            "SELECT decision_as_of FROM sig_fast_live_paper_signal_v0 WHERE signal_id=?",
            (outcome.signal_id,),
        ).fetchone()
        if signal_row is None:
            raise ValueError("outcome references a signal that was never recorded")
        if outcome.measured_at < int(signal_row["decision_as_of"]):
            raise ValueError("outcome cannot be measured before its own signal's decision_as_of")

        raw_json = _canonical_json(
            {
                "signal_id": outcome.signal_id,
                "measured_at": outcome.measured_at,
                "barrier_result": outcome.barrier_result,
                "exit_rule_id": outcome.exit_rule_id,
                "gross_return_pct": outcome.gross_return_pct,
                "net_return_pct": outcome.net_return_pct,
                "missing_reason": outcome.missing_reason,
            }
        )
        cursor = conn.execute(
            """INSERT OR IGNORE INTO sig_fast_live_paper_outcome_v0(
                signal_id, measured_at, barrier_result, exit_rule_id,
                gross_return_pct, net_return_pct, missing_reason, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                outcome.signal_id,
                outcome.measured_at,
                outcome.barrier_result,
                outcome.exit_rule_id,
                outcome.gross_return_pct,
                outcome.net_return_pct,
                outcome.missing_reason,
                raw_json,
            ),
        )
        return cursor.rowcount == 1


def load_outcome(signal_id: str) -> PaperOutcome | None:
    ensure_live_paper_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT signal_id, measured_at, barrier_result, exit_rule_id,
            gross_return_pct, net_return_pct, missing_reason
            FROM sig_fast_live_paper_outcome_v0 WHERE signal_id=?""",
            (signal_id,),
        ).fetchone()
    if row is None:
        return None
    return PaperOutcome(
        signal_id=str(row["signal_id"]),
        measured_at=int(row["measured_at"]),
        barrier_result=str(row["barrier_result"]),
        exit_rule_id=str(row["exit_rule_id"]),
        gross_return_pct=row["gross_return_pct"],
        net_return_pct=row["net_return_pct"],
        missing_reason=row["missing_reason"],
    )


_SELF_CHECK_CONFIG = {
    "entry_latency_seconds": 30,
    "exit_latency_seconds": 30,
    "window_seconds": 900,
    "size_sol": 0.15,
    "target_pct": 50.0,
    "stop_pct": -30.0,
    "exit_rule_id": "hold_until_window_end_v0",
    "venue_fee_pct": 1.0,
    "terminal_fee_pct": 1.0,
}


def _entry_event(chain_time: int, quote_reserves: int) -> PathTrade:
    return PathTrade(
        chain_time=chain_time,
        venue="pumpswap",
        base_reserves_raw=1_000_000 * 10**6,
        quote_reserves_raw=quote_reserves,
    )


def _path_event(chain_time: int, executed_price_sol: float) -> PathTrade:
    # Post-entry path tracking (barrier/exit trigger) reads the trade's own
    # EXECUTED price, never reserves -- see opportunity_path_metrics_v0's
    # module docstring. Reserves at the SAME implied mid price are also
    # attached (a large pool, so AMM slippage on the self-check's small
    # trade size is negligible) so this same event can double as the causal
    # EXIT FILL: simulate_exit resolves the exit trade by chain_time alone,
    # then prices it off *its* reserves, independent of the trigger scan.
    base_amount_raw = 1_000_000
    quote_amount_raw = round(executed_price_sol * 10**9 * base_amount_raw / 10**6)
    base_reserves_raw = 1_000_000 * 10**6
    quote_reserves_raw = round(executed_price_sol * (base_reserves_raw / 10**6) * 10**9)
    return PathTrade(
        chain_time=chain_time,
        venue="pumpswap",
        base_amount_raw=base_amount_raw,
        quote_amount_raw=quote_amount_raw,
        base_reserves_raw=base_reserves_raw,
        quote_reserves_raw=quote_reserves_raw,
    )


def _self_check_signal_is_frozen_and_idempotent(db_path) -> None:
    from src import database as database_module
    from types import SimpleNamespace
    from unittest.mock import patch

    with patch.object(database_module, "settings", SimpleNamespace(database_path=db_path)):
        signal = PaperSignal(
            signal_id="sig-1",
            token_mint="MINT1",
            detected_at=1000,
            decision_as_of=1000,
            strategy_version="sig_fast_v0",
            config=_SELF_CHECK_CONFIG,
            context={"flow60_buy_share_pct": 72.0},
        )
        assert record_signal(signal) is True
        assert record_signal(signal) is False  # idempotent replay

        reconfigured = PaperSignal(
            signal_id="sig-1",
            token_mint="MINT1",
            detected_at=1000,
            decision_as_of=1000,
            strategy_version="sig_fast_v0",
            config={**_SELF_CHECK_CONFIG, "size_sol": 0.30},
            context={"flow60_buy_share_pct": 72.0},
        )
        try:
            record_signal(reconfigured)
            raise AssertionError("expected ValueError on silent reconfiguration")
        except ValueError:
            pass

        loaded = load_signal("sig-1")
        assert loaded is not None and loaded.config["size_sol"] == 0.15

        try:
            record_signal(
                PaperSignal(
                    signal_id="sig-lookahead",
                    token_mint="MINT2",
                    detected_at=1000,
                    decision_as_of=999,
                    strategy_version="sig_fast_v0",
                    config=_SELF_CHECK_CONFIG,
                    context={},
                )
            )
            raise AssertionError("expected ValueError on decision_as_of < detected_at")
        except ValueError:
            pass


def _self_check_outcome_evaluation_and_canonical_first_write(db_path) -> None:
    from src import database as database_module
    from types import SimpleNamespace
    from unittest.mock import patch

    with patch.object(database_module, "settings", SimpleNamespace(database_path=db_path)):
        signal = PaperSignal(
            signal_id="sig-2",
            token_mint="MINT2",
            detected_at=2000,
            decision_as_of=2000,
            strategy_version="sig_fast_v0",
            config=_SELF_CHECK_CONFIG,
            context={},
        )
        record_signal(signal)

        # Entry trade at decision_as_of+30, then a path that rises +80% (touches
        # the +50% target barrier) before settling back for the window-end exit.
        trades = [
            _entry_event(2030, quote_reserves=100 * 10**9),
            _path_event(2060, executed_price_sol=0.00018),  # +80% vs entry mid 0.0001
            _path_event(2900, executed_price_sol=0.00013),  # settles, still positive
            _path_event(2935, executed_price_sol=0.00013),  # exit fill, latency+30s after trigger
        ]
        outcome = evaluate_paper_signal_outcome(trades, signal=signal, measured_at=3000)
        assert outcome.barrier_result == "UP", outcome
        assert outcome.missing_reason is None, outcome
        assert outcome.net_return_pct is not None and outcome.net_return_pct > 0, outcome

        assert record_outcome(outcome) is True
        # A second, different-looking measurement must never overwrite the first.
        later = evaluate_paper_signal_outcome(
            [*trades, _path_event(3500, executed_price_sol=0.00005)],
            signal=signal,
            measured_at=4000,
        )
        assert record_outcome(later) is False
        canonical = load_outcome("sig-2")
        assert canonical is not None
        assert canonical.net_return_pct == outcome.net_return_pct, (canonical, outcome)


def _self_check_missing_data_is_explicit_never_fabricated(db_path) -> None:
    from src import database as database_module
    from types import SimpleNamespace
    from unittest.mock import patch

    with patch.object(database_module, "settings", SimpleNamespace(database_path=db_path)):
        signal = PaperSignal(
            signal_id="sig-3",
            token_mint="MINT3",
            detected_at=5000,
            decision_as_of=5000,
            strategy_version="sig_fast_v0",
            config=_SELF_CHECK_CONFIG,
            context={},
        )
        record_signal(signal)

        # No trades at all yet (e.g. measured right after decision_as_of).
        outcome = evaluate_paper_signal_outcome([], signal=signal, measured_at=5001)
        assert outcome.barrier_result == "NOT_AVAILABLE"
        assert outcome.gross_return_pct is None and outcome.net_return_pct is None
        assert outcome.missing_reason == "no_trade_at_or_after_entry_time"

        try:
            record_outcome(
                PaperOutcome(
                    signal_id="sig-3",
                    measured_at=4999,  # before decision_as_of
                    barrier_result="NOT_AVAILABLE",
                    exit_rule_id="hold_until_window_end_v0",
                    gross_return_pct=None,
                    net_return_pct=None,
                    missing_reason="no_trade_at_or_after_entry_time",
                )
            )
            raise AssertionError("expected ValueError: outcome before decision_as_of")
        except ValueError:
            pass

        try:
            record_outcome(
                PaperOutcome(
                    signal_id="sig-does-not-exist",
                    measured_at=5001,
                    barrier_result="NOT_AVAILABLE",
                    exit_rule_id="hold_until_window_end_v0",
                    gross_return_pct=None,
                    net_return_pct=None,
                    missing_reason="x",
                )
            )
            raise AssertionError("expected ValueError: unknown signal_id")
        except ValueError:
            pass


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "live_paper.db"
        _self_check_signal_is_frozen_and_idempotent(db_path)
        _self_check_outcome_evaluation_and_canonical_first_write(db_path)
        _self_check_missing_data_is_explicit_never_fabricated(db_path)
    print(f"{VERSION}: self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", required=True)
    parser.parse_args()
    _self_check()


if __name__ == "__main__":
    main()
