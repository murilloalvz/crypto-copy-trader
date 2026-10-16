"""Checkpoint da Parte A em SQLite (fonte da verdade; retomavel a qualquer momento)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS windows (
    period TEXT NOT NULL, ord INTEGER NOT NULL, start_ts INTEGER NOT NULL, end_ts INTEGER NOT NULL,
    launchpad TEXT NOT NULL, status TEXT NOT NULL, n_grad INTEGER, info TEXT,
    PRIMARY KEY (period, ord, launchpad)
);
CREATE TABLE IF NOT EXISTS graduations (
    pool TEXT PRIMARY KEY, mint TEXT, quote TEXT, launchpad TEXT NOT NULL, grad_ts INTEGER NOT NULL,
    signature TEXT, period TEXT NOT NULL, ord INTEGER NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage1 (
    pool TEXT PRIMARY KEY, status TEXT NOT NULL, max_mc REAL, runner INTEGER, l_bc REAL, supply REAL, info TEXT,
    created_ts REAL
);
CREATE TABLE IF NOT EXISTS stage2 (
    pool TEXT NOT NULL, tf TEXT NOT NULL, status TEXT NOT NULL, n_bars INTEGER, holes INTEGER, info TEXT,
    PRIMARY KEY (pool, tf)
);
CREATE TABLE IF NOT EXISTS setups (
    pool TEXT NOT NULL, tf TEXT NOT NULL, n INTEGER NOT NULL, primary_flag INTEGER NOT NULL, ts INTEGER NOT NULL,
    event TEXT NOT NULL, PRIMARY KEY (pool, tf, n)
);
CREATE TABLE IF NOT EXISTS trades (
    pool TEXT NOT NULL, tf TEXT NOT NULL, n INTEGER NOT NULL, variant TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, net_ret REAL, gross_ret REAL, r_mult REAL, hit_tp INTEGER, bars_held INTEGER,
    reason TEXT, info TEXT, PRIMARY KEY (pool, tf, n, variant, kind)
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- meta -------------------------------------------------------------------
    def get(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def require(self, key: str, value: str) -> None:
        """Grava na 1a vez; depois exige o MESMO valor (config/plano nao mudam no meio de uma coleta)."""
        old = self.get(key)
        if old is None:
            self.set(key, value)
        elif old != value:
            raise RuntimeError(f"{key} mudou no meio da coleta ({old} -> {value}): use outro arquivo de checkpoint")

    # -- janelas e graduacoes ---------------------------------------------------------
    def window_done(self, period: str, ord_: int, launchpad: str) -> bool:
        row = self.db.execute("SELECT status FROM windows WHERE period=? AND ord=? AND launchpad=?", (period, ord_, launchpad)).fetchone()
        return bool(row and row[0] == "ok")

    def save_window(self, period: str, ord_: int, start: int, end: int, launchpad: str, status: str, grads: Iterable[Any], info: dict) -> None:
        grads = list(grads)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?)",
                            (period, ord_, start, end, launchpad, status, len(grads), json.dumps(info)))
            for g in grads:
                if not g.pool:
                    continue
                self.db.execute("INSERT OR IGNORE INTO graduations VALUES (?,?,?,?,?,?,?,?,?)",
                                (g.pool, g.mint, g.quote_mint, g.launchpad, g.block_time, g.signature, period, ord_, g.status))

    def graduations(self, period: str, max_ord: Optional[int] = None) -> list[sqlite3.Row]:
        self.db.row_factory = sqlite3.Row
        q = "SELECT * FROM graduations WHERE period=?" + (" AND ord<=?" if max_ord is not None else "") + " ORDER BY ord, grad_ts, pool"
        args: tuple = (period, max_ord) if max_ord is not None else (period,)
        rows = self.db.execute(q, args).fetchall()
        self.db.row_factory = None
        return rows

    # -- estagios -----------------------------------------------------------------------
    def stage1(self, pool: str) -> Optional[tuple]:
        """(status, max_mc, runner, l_bc, supply, info, created_ts) — created_ts = criacao do token (so runners)."""
        return self.db.execute("SELECT status, max_mc, runner, l_bc, supply, info, created_ts FROM stage1 WHERE pool=?", (pool,)).fetchone()

    def save_stage1(self, pool: str, status: str, max_mc: Optional[float], runner: Optional[bool], l_bc: Optional[float],
                    supply: Optional[float], info: dict, created_ts: Optional[float] = None) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO stage1 VALUES (?,?,?,?,?,?,?,?)",
                            (pool, status, max_mc, None if runner is None else int(runner), l_bc, supply, json.dumps(info), created_ts))

    def stage2(self, pool: str, tf: str) -> Optional[tuple]:
        return self.db.execute("SELECT status, n_bars, holes FROM stage2 WHERE pool=? AND tf=?", (pool, tf)).fetchone()

    def save_stage2(self, pool: str, tf: str, status: str, n_bars: int, holes: int, info: dict) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO stage2 VALUES (?,?,?,?,?,?)", (pool, tf, status, n_bars, holes, json.dumps(info)))

    def save_setups(self, pool: str, tf: str, events: list[dict]) -> None:
        with self.db:
            self.db.execute("DELETE FROM setups WHERE pool=? AND tf=?", (pool, tf))
            for k, ev in enumerate(events, start=1):
                self.db.execute("INSERT INTO setups VALUES (?,?,?,?,?,?)",
                                (pool, tf, k, int(bool(ev["data"].get("primario"))), ev["ts"], json.dumps(ev, default=str)))

    def setups(self, period: str, tf: Optional[str] = None, primary_only: bool = True) -> list[tuple]:
        q = ("SELECT s.pool, s.tf, s.n, s.primary_flag, s.ts, s.event FROM setups s JOIN graduations g ON g.pool=s.pool "
             "WHERE g.period=?")
        args: list = [period]
        if tf:
            q += " AND s.tf=?"
            args.append(tf)
        if primary_only:
            q += " AND s.primary_flag=1"
        return self.db.execute(q + " ORDER BY s.ts", args).fetchall()

    def save_trade(self, pool: str, tf: str, n: int, variant: str, kind: str, res: Any, info: dict) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (pool, tf, n, variant, kind, res.status, res.net_ret, res.gross_ret, res.r_mult,
                             int(res.hit_tp), res.bars_held, res.reason, json.dumps(info, default=str)))

    def trades(self, period: str, kind: str = "setup") -> list[tuple]:
        return self.db.execute(
            "SELECT t.pool, t.tf, t.n, t.variant, t.status, t.net_ret, t.gross_ret, t.r_mult, t.hit_tp, t.bars_held, t.reason, t.info, "
            "g.launchpad, g.quote FROM trades t JOIN graduations g ON g.pool=t.pool WHERE g.period=? AND t.kind=?", (period, kind)).fetchall()

    def counts(self, period: str) -> dict[str, Any]:
        c = {}
        c["graduacoes"] = self.db.execute("SELECT COUNT(*) FROM graduations WHERE period=?", (period,)).fetchone()[0]
        c["estagio1"] = dict(self.db.execute(
            "SELECT s.status, COUNT(*) FROM stage1 s JOIN graduations g ON g.pool=s.pool WHERE g.period=? GROUP BY s.status", (period,)).fetchall())
        c["runners"] = self.db.execute(
            "SELECT COUNT(*) FROM stage1 s JOIN graduations g ON g.pool=s.pool WHERE g.period=? AND s.runner=1", (period,)).fetchone()[0]
        c["runners_sem_criacao"] = self.db.execute(
            "SELECT COUNT(*) FROM stage1 s JOIN graduations g ON g.pool=s.pool WHERE g.period=? AND s.runner=1 AND s.created_ts IS NULL",
            (period,)).fetchone()[0]
        c["setups_primarios"] = dict(self.db.execute(
            "SELECT s.tf, COUNT(*) FROM setups s JOIN graduations g ON g.pool=s.pool WHERE g.period=? AND s.primary_flag=1 GROUP BY s.tf",
            (period,)).fetchall())
        return c
