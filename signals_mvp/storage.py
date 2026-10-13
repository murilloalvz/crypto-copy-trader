"""Estado persistente (SQLite) e CSVs de formato estavel.

O SQLite e a fonte da verdade: o bot pode cair e reiniciar sem perder o acompanhamento.
Os CSVs sao regenerados do banco (troca atomica); se o arquivo estiver aberto no Excel
(Windows trava), a escrita e adiada para o proximo ciclo — nada se perde.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any, Iterable, Optional, Sequence

from .config import Paths
from .util import atomic_write_csv, atomic_write_text, canonical_json, csv_safe, iso_utc

log = logging.getLogger("signals_mvp.storage")

# --- formato ESTAVEL dos CSVs (nao mude a ordem/nomes sem avisar o operador) -----------------
SINAIS_COLUMNS = [
    "data", "chain", "token", "contrato", "etiqueta", "score", "componentes_score", "mc", "liq", "vol_m5",
    "acel_vol", "compras", "vendas", "top10", "seguranca", "narrativa_match", "enviado", "operou", "mc_5m",
    "mc_15m", "mc_1h", "max", "min", "tp1_antes_sl", "resultado_liq", "latencia_s", "versao_config", "versao_meta",
]
DESCARTADOS_COLUMNS = ["data", "chain", "token", "contrato", "etapa", "motivo", "valor", "versao_config"]
TRADES_COLUMNS = ["data", "chain", "contrato", "acao", "valor", "sinal_relacionado"]

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS config_versions (hash TEXT PRIMARY KEY, first_ts REAL, json TEXT);
CREATE TABLE IF NOT EXISTS meta_versions (hash TEXT PRIMARY KEY, first_ts REAL, text TEXT);
CREATE TABLE IF NOT EXISTS pools (
  chain TEXT NOT NULL, pool TEXT NOT NULL, dex TEXT, created_ts REAL, first_seen_ts REAL NOT NULL,
  first_seen_age_s REAL, first_price REAL, token TEXT, symbol TEXT, token_name TEXT, target_side TEXT,
  last_vol_m5 REAL, last_seen_ts REAL,
  PRIMARY KEY (chain, pool)
);
CREATE TABLE IF NOT EXISTS labels (
  chain TEXT NOT NULL, pool TEXT NOT NULL, etiqueta TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'aberto',
  ts REAL, last_etapa TEXT, last_motivo TEXT, last_valor TEXT,
  PRIMARY KEY (chain, pool, etiqueta)
);
CREATE INDEX IF NOT EXISTS labels_open ON labels (state, etiqueta);
CREATE TABLE IF NOT EXISTS security_cache (
  chain TEXT NOT NULL, token TEXT NOT NULL, ts REAL, status TEXT, json TEXT, PRIMARY KEY (chain, token)
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chain TEXT NOT NULL, pool TEXT NOT NULL, token TEXT NOT NULL, symbol TEXT, token_name TEXT, etiqueta TEXT NOT NULL,
  dex TEXT, decision_ts REAL NOT NULL, created_ts REAL, score REAL, componentes TEXT, entry_price REAL, mc REAL,
  liq REAL, vol_m5 REAL, acel_vol REAL, compras INTEGER, vendas INTEGER, top10 REAL, seguranca TEXT,
  seguranca_json TEXT, narrativa TEXT, enviado INTEGER NOT NULL DEFAULT 0, alert_ts REAL, tg_message_id INTEGER,
  latencia_s REAL, motivo_nao_enviado TEXT, versao_config TEXT, versao_meta TEXT, plano_json TEXT, features_json TEXT,
  status TEXT NOT NULL DEFAULT 'acompanhando', mc_5m REAL, mc_15m REAL, mc_1h REAL, max_mc REAL, min_mc REAL,
  tp1_antes_sl TEXT NOT NULL DEFAULT 'pendente', resultado_liq REAL, finalizado_ts REAL,
  fin_tentativas INTEGER NOT NULL DEFAULT 0, fin_proxima_ts REAL, seguranca_tardia TEXT, outcome_json TEXT,
  UNIQUE (chain, pool, etiqueta)
);
CREATE INDEX IF NOT EXISTS signals_follow ON signals (status, fin_proxima_ts);
CREATE INDEX IF NOT EXISTS signals_token ON signals (chain, token);
CREATE TABLE IF NOT EXISTS discards (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, chain TEXT, symbol TEXT, contract TEXT, etapa TEXT,
  motivo TEXT, valor TEXT, versao_config TEXT, pool TEXT, etiqueta TEXT
);
CREATE TABLE IF NOT EXISTS operator_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, chain TEXT, contract TEXT, acao TEXT, valor REAL,
  signal_id INTEGER, via TEXT
);
CREATE INDEX IF NOT EXISTS trades_signal ON operator_trades (signal_id, acao);
"""

# colunas de `signals` que podem ser atualizadas depois da insercao
UPDATABLE = {
    "enviado", "alert_ts", "tg_message_id", "latencia_s", "motivo_nao_enviado", "status", "mc_5m", "mc_15m", "mc_1h",
    "max_mc", "min_mc", "tp1_antes_sl", "resultado_liq", "finalizado_ts", "fin_tentativas", "fin_proxima_ts",
    "seguranca_tardia", "outcome_json",
}
INSERTABLE = {
    "chain", "pool", "token", "symbol", "token_name", "etiqueta", "dex", "decision_ts", "created_ts", "score",
    "componentes", "entry_price", "mc", "liq", "vol_m5", "acel_vol", "compras", "vendas", "top10", "seguranca",
    "seguranca_json", "narrativa", "enviado", "alert_ts", "tg_message_id", "latencia_s", "motivo_nao_enviado",
    "versao_config", "versao_meta", "plano_json", "features_json", "fin_proxima_ts",
}


def _num(value: Any, digits: int = 0) -> Any:
    """Numero para CSV: vazio se None; inteiro quando digits=0."""
    if value is None:
        return ""
    return int(round(value)) if digits == 0 else round(float(value), digits)


class Storage:
    def __init__(self, paths: Paths):
        self.paths = paths
        paths.dados.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(paths.db), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA busy_timeout=30000")
            self._db.executescript(SCHEMA)
            current = self._db.execute("PRAGMA user_version").fetchone()[0]
            if current == 0:
                self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif current > SCHEMA_VERSION:
                raise RuntimeError(f"banco {paths.db} e de uma versao mais nova do bot (schema {current})")
        self._dirty = {"sinais": True, "descartados": True, "trades": True, "detalhe": True}
        self._warned: set[str] = set()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- util -------------------------------------------------------------------------
    def _one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchone()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, params)

    # -- meta / versoes -----------------------------------------------------------------
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._exec("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def register_config_version(self, version: str, raw: dict, ts: float) -> bool:
        """Grava a versao do config (e uma copia legivel em dados/config_versoes/). True se for nova."""
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO config_versions(hash,first_ts,json) VALUES(?,?,?)", (version, ts, canonical_json(raw)))
            is_new = cur.rowcount == 1
        if is_new:
            try:
                atomic_write_text(self.paths.config_versions / f"{version}.json", json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True))
            except OSError as exc:
                log.warning("nao consegui gravar o snapshot da config %s: %s", version, exc)
        return is_new

    def config_snapshot(self, version: str) -> Optional[dict]:
        row = self._one("SELECT json FROM config_versions WHERE hash=?", (version,))
        return json.loads(row["json"]) if row else None

    def register_meta_version(self, version: str, text: str, ts: float) -> None:
        self._exec("INSERT OR IGNORE INTO meta_versions(hash,first_ts,text) VALUES(?,?,?)", (version, ts, text))

    # -- pools e etiquetas -------------------------------------------------------------------
    def get_pool(self, chain: str, pool: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pools WHERE chain=? AND pool=?", (chain, pool))

    def add_pool_if_new(self, snap: Any, labels: Iterable[str], now: float) -> bool:
        """Registra o pool no primeiro avistamento (preco inicial = preco desse instante)."""
        age = None if snap.created_ts is None else now - snap.created_ts
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO pools(chain,pool,dex,created_ts,first_seen_ts,first_seen_age_s,first_price,token,symbol,token_name,target_side,last_vol_m5,last_seen_ts)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (snap.chain, snap.pool, snap.dex, snap.created_ts, now, age, snap.price_usd, snap.token, snap.symbol, snap.token_name, snap.target_side,
                 snap.vol.get("m5"), now),
            )
            is_new = cur.rowcount == 1
            if is_new:
                for label in labels:
                    self._db.execute("INSERT OR IGNORE INTO labels(chain,pool,etiqueta,state) VALUES(?,?,?, 'aberto')", (snap.chain, snap.pool, label))
        return is_new

    def touch_pool(self, chain: str, pool: str, vol_m5: Optional[float], now: float) -> None:
        """Guarda a atividade mais recente (ordena o refresh: pool mais ativo e re-checado primeiro)."""
        self._exec("UPDATE pools SET last_vol_m5=?, last_seen_ts=? WHERE chain=? AND pool=?", (vol_m5, now, chain, pool))

    def open_labels(self, chain: str, pool: str) -> list[str]:
        rows = self._all("SELECT etiqueta FROM labels WHERE chain=? AND pool=? AND state='aberto'", (chain, pool))
        return [r["etiqueta"] for r in rows]

    def label_state(self, chain: str, pool: str, etiqueta: str) -> Optional[str]:
        row = self._one("SELECT state FROM labels WHERE chain=? AND pool=? AND etiqueta=?", (chain, pool, etiqueta))
        return row["state"] if row else None

    def note_label(self, chain: str, pool: str, etiqueta: str, etapa: str, motivo: str, valor: str) -> None:
        """Guarda por que o gatilho ainda nao disparou (vai pro descartados.csv se expirar)."""
        # 'adiado' (o gatilho chegou a disparar, mas nao deu para avaliar) e pegajoso: um "nao disparou" posterior nao apaga isso
        self._exec(
            "UPDATE labels SET last_etapa=?, last_motivo=?, last_valor=? WHERE chain=? AND pool=? AND etiqueta=? AND state='aberto' "
            "AND (?='adiado' OR COALESCE(last_etapa,'')!='adiado')",
            (etapa, motivo, valor, chain, pool, etiqueta, etapa),
        )

    def finalize_label(self, chain: str, pool: str, etiqueta: str, state: str, ts: float) -> None:
        self._exec("UPDATE labels SET state=?, ts=? WHERE chain=? AND pool=? AND etiqueta=?", (state, ts, chain, pool, etiqueta))

    def pools_to_refresh(self, now: float, novo_max_s: float, s_min_s: float, s_max_s: float) -> list[sqlite3.Row]:
        """Pools com etiqueta ABERTA cuja janela de idade esta ativa agora (1 linha por pool+etiqueta)."""
        return self._all(
            "SELECT p.*, l.etiqueta AS etiqueta FROM pools p JOIN labels l ON l.chain=p.chain AND l.pool=p.pool "
            "WHERE l.state='aberto' AND p.created_ts IS NOT NULL AND ("
            " (l.etiqueta='novo' AND (? - p.created_ts) <= ?) OR "
            " (l.etiqueta='sobrevivente20' AND (? - p.created_ts) >= ? AND (? - p.created_ts) <= ?)"
            ") ORDER BY COALESCE(p.last_vol_m5, 0) DESC, p.created_ts DESC",
            (now, novo_max_s, now, s_min_s, now, s_max_s),
        )

    def expired_labels(self, now: float, novo_max_s: float, s_max_s: float) -> list[sqlite3.Row]:
        """Etiquetas ainda abertas cuja janela acabou (ou pool sem data de criacao)."""
        return self._all(
            "SELECT p.*, l.etiqueta AS etiqueta, l.last_etapa, l.last_motivo, l.last_valor FROM pools p "
            "JOIN labels l ON l.chain=p.chain AND l.pool=p.pool WHERE l.state='aberto' AND ("
            " p.created_ts IS NULL OR "
            " (l.etiqueta='novo' AND (? - p.created_ts) > ?) OR "
            " (l.etiqueta='sobrevivente20' AND (? - p.created_ts) > ?))",
            (now, novo_max_s, now, s_max_s),
        )

    # -- cache de seguranca --------------------------------------------------------------------
    def cache_security(self, chain: str, token: str, ts: float, status: str, payload: dict) -> None:
        self._exec(
            "INSERT INTO security_cache(chain,token,ts,status,json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(chain,token) DO UPDATE SET ts=excluded.ts,status=excluded.status,json=excluded.json",
            (chain, token, ts, status, canonical_json(payload)),
        )

    def cached_security(self, chain: str, token: str, now: float, max_age_s: float) -> Optional[dict]:
        row = self._one("SELECT ts,status,json FROM security_cache WHERE chain=? AND token=?", (chain, token))
        if row is None or now - row["ts"] > max_age_s or row["status"] not in ("ok", "falhou"):
            return None
        return json.loads(row["json"])

    # -- sinais -------------------------------------------------------------------------------------
    def insert_signal(self, row: dict) -> Optional[int]:
        unknown = set(row) - INSERTABLE
        if unknown:
            raise KeyError(f"colunas invalidas em insert_signal: {sorted(unknown)}")
        columns = sorted(row)
        sql = f"INSERT OR IGNORE INTO signals({','.join(columns)}) VALUES({','.join('?' for _ in columns)})"
        with self._lock:
            cur = self._db.execute(sql, [row[c] for c in columns])
            self._dirty["sinais"] = self._dirty["detalhe"] = True
            return cur.lastrowid if cur.rowcount == 1 else None

    def update_signal(self, signal_id: int, **fields: Any) -> None:
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise KeyError(f"colunas invalidas em update_signal: {sorted(unknown)}")
        if not fields:
            return
        assignments = ",".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE signals SET {assignments} WHERE id=?", [*fields.values(), signal_id])
            self._dirty["sinais"] = self._dirty["detalhe"] = True

    def get_signal(self, signal_id: int) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM signals WHERE id=?", (signal_id,))

    def signals_due(self, now: float, limit: int = 50) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM signals WHERE status='acompanhando' AND fin_proxima_ts IS NOT NULL AND fin_proxima_ts<=? "
            "ORDER BY fin_proxima_ts LIMIT ?",
            (now, limit),
        )

    def signals_needing_late_security(self, limit: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM signals WHERE status IN ('finalizado','sem_dado') AND seguranca IN ('sem_dado','parcial') "
            "AND seguranca_tardia IS NULL ORDER BY decision_ts LIMIT ?",
            (limit,),
        )

    def signals_for_contract(self, contract: str, chain: Optional[str] = None) -> list[sqlite3.Row]:
        if chain:
            return self._all("SELECT * FROM signals WHERE chain=? AND lower(token)=lower(?) ORDER BY decision_ts DESC", (chain, contract))
        return self._all("SELECT * FROM signals WHERE lower(token)=lower(?) ORDER BY decision_ts DESC", (contract,))

    def token_dex_label_exists(self, chain: str, token: str, dex: str, etiqueta: str) -> bool:
        return self._one("SELECT 1 FROM signals WHERE chain=? AND token=? AND dex=? AND etiqueta=?", (chain, token, dex, etiqueta)) is not None

    def signals_between(self, ts_from: float, ts_to: float) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM signals WHERE decision_ts>=? AND decision_ts<? ORDER BY decision_ts", (ts_from, ts_to))

    # -- descartados ----------------------------------------------------------------------------------
    def add_discard(
        self, ts: float, chain: str, symbol: str, contract: str, etapa: str, motivo: str, valor: str,
        versao_config: str, pool: str = "", etiqueta: str = "",
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO discards(ts,chain,symbol,contract,etapa,motivo,valor,versao_config,pool,etiqueta) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, chain, symbol, contract, etapa, motivo, valor, versao_config, pool, etiqueta),
            )
            self._dirty["descartados"] = True

    def discards_between(self, ts_from: float, ts_to: float) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM discards WHERE ts>=? AND ts<?", (ts_from, ts_to))

    # -- operador ----------------------------------------------------------------------------------------
    def add_operator_trade(self, ts: float, chain: str, contract: str, acao: str, valor: Optional[float], signal_id: Optional[int], via: str) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO operator_trades(ts,chain,contract,acao,valor,signal_id,via) VALUES(?,?,?,?,?,?,?)",
                (ts, chain, contract, acao, valor, signal_id, via),
            )
            self._dirty["trades"] = self._dirty["sinais"] = self._dirty["detalhe"] = True
            return int(cur.lastrowid)

    def operator_action_for(self, signal_id: int) -> Optional[str]:
        row = self._one("SELECT acao FROM operator_trades WHERE signal_id=? AND acao IN ('entrei','passei') ORDER BY id DESC LIMIT 1", (signal_id,))
        return row["acao"] if row else None

    # -- estatisticas para console/status ------------------------------------------------------------------
    def counts(self) -> dict:
        return {
            "pools": self._one("SELECT COUNT(*) c FROM pools")["c"],
            "sinais": self._one("SELECT COUNT(*) c FROM signals")["c"],
            "enviados": self._one("SELECT COUNT(*) c FROM signals WHERE enviado=1")["c"],
            "acompanhando": self._one("SELECT COUNT(*) c FROM signals WHERE status='acompanhando'")["c"],
            "descartados": self._one("SELECT COUNT(*) c FROM discards")["c"],
        }

    def prune(self, now: float, keep_days: float = 3.0) -> dict:
        """Apaga pools/etiquetas ANTIGOS (>keep_days; as janelas de 10-25 min acabaram ha muito) que nao tem sinal, e o
        cache de seguranca velho. Sinais, descartados e trades do operador nunca sao apagados."""
        cutoff = now - keep_days * 86400.0
        with self._lock:
            labels = self._db.execute(
                "DELETE FROM labels WHERE EXISTS (SELECT 1 FROM pools p WHERE p.chain=labels.chain AND p.pool=labels.pool AND p.first_seen_ts<?) "
                "AND NOT EXISTS (SELECT 1 FROM signals s WHERE s.chain=labels.chain AND s.pool=labels.pool)", (cutoff,)).rowcount
            pools = self._db.execute(
                "DELETE FROM pools WHERE first_seen_ts<? AND NOT EXISTS (SELECT 1 FROM signals s WHERE s.chain=pools.chain AND s.pool=pools.pool)",
                (cutoff,)).rowcount
            cache = self._db.execute("DELETE FROM security_cache WHERE ts<?", (now - 86400.0,)).rowcount
        return {"labels": labels, "pools": pools, "security_cache": cache} if (labels or pools or cache) else {}

    # -- CSVs ----------------------------------------------------------------------------------------------------
    def _sinais_rows(self) -> list[list[Any]]:
        sql = (
            "SELECT s.*, EXISTS(SELECT 1 FROM operator_trades t WHERE t.signal_id=s.id AND t.acao='entrei') AS operou "
            "FROM signals s ORDER BY s.decision_ts, s.id"
        )
        rows: list[list[Any]] = []
        for r in self._all(sql):
            rows.append([
                iso_utc(r["decision_ts"]), r["chain"], csv_safe(r["symbol"]), r["token"], r["etiqueta"], _num(r["score"], 1),
                r["componentes"] or "", _num(r["mc"]), _num(r["liq"]), _num(r["vol_m5"]), _num(r["acel_vol"], 2),
                "" if r["compras"] is None else r["compras"], "" if r["vendas"] is None else r["vendas"], _num(r["top10"], 1),
                r["seguranca"] or "", csv_safe(r["narrativa"]), r["enviado"], r["operou"], _num(r["mc_5m"]), _num(r["mc_15m"]),
                _num(r["mc_1h"]), _num(r["max_mc"]), _num(r["min_mc"]), r["tp1_antes_sl"], _num(r["resultado_liq"], 2),
                _num(r["latencia_s"], 1), r["versao_config"] or "", r["versao_meta"] or "",
            ])
        return rows

    def _descartados_rows(self) -> list[list[Any]]:
        return [
            [iso_utc(r["ts"]), r["chain"], csv_safe(r["symbol"]), r["contract"], r["etapa"], csv_safe(r["motivo"]), csv_safe(r["valor"]), r["versao_config"]]
            for r in self._all("SELECT * FROM discards ORDER BY ts, id")
        ]

    def _trades_rows(self) -> list[list[Any]]:
        sql = (
            "SELECT t.*, s.decision_ts AS sdt, s.etiqueta AS setq FROM operator_trades t "
            "LEFT JOIN signals s ON s.id=t.signal_id ORDER BY t.ts, t.id"
        )
        out = []
        for r in self._all(sql):
            related = f"{iso_utc(r['sdt'])}|{r['setq']}" if r["sdt"] is not None else ""
            out.append([iso_utc(r["ts"]), r["chain"], r["contract"], r["acao"], "" if r["valor"] is None else round(r["valor"], 2), related])
        return out

    def _detalhe_rows(self) -> tuple[list[str], list[list[Any]]]:
        rows = self._all("SELECT * FROM signals ORDER BY decision_ts, id")
        header = list(rows[0].keys()) if rows else [c for c in sorted(INSERTABLE | UPDATABLE | {"id"})]
        out = []
        for r in rows:
            out.append([csv_safe(r[k]) if k in ("symbol", "token_name", "narrativa") else ("" if r[k] is None else r[k]) for k in header])
        return header, out

    def export_csvs(self, force: bool = False) -> list[str]:
        """Regenera os CSVs 'sujos'. Arquivo travado (Excel) fica pro proximo ciclo. Devolve o que gravou."""
        written: list[str] = []
        jobs = {
            "sinais": (self.paths.sinais_csv, lambda: (SINAIS_COLUMNS, self._sinais_rows())),
            "descartados": (self.paths.descartados_csv, lambda: (DESCARTADOS_COLUMNS, self._descartados_rows())),
            "trades": (self.paths.trades_csv, lambda: (TRADES_COLUMNS, self._trades_rows())),
            "detalhe": (self.paths.detalhe_csv, self._detalhe_rows),
        }
        for name, (path, build) in jobs.items():
            with self._lock:
                if not (force or self._dirty[name]):
                    continue
                # limpa ANTES de montar as linhas: escrita concorrente (thread do Telegram) marca de novo
                self._dirty[name] = False
            header, rows = build()
            if self._write_csv(name, path, header, rows):
                written.append(path.name)
        return written

    def _write_csv(self, name: str, path: Any, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> bool:
        try:
            atomic_write_csv(path, header, rows)
            self._warned.discard(name)
            return True
        except PermissionError:
            with self._lock:
                self._dirty[name] = True
            if name not in self._warned:
                self._warned.add(name)
                log.warning("%s esta aberto em outro programa (Excel?). Feche-o: a gravacao sera refeita no proximo ciclo.", path.name)
            return False
        except OSError as exc:
            with self._lock:
                self._dirty[name] = True
            log.error("falha ao gravar %s: %s", path.name, exc)
            return False
