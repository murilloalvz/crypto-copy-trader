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
# POS-RUNNER-V0 (Parte B): colunas exatas do handoff de 2026-10-15
POS_RUNNER_COLUMNS = [
    "data", "token", "contrato", "launchpad", "tf", "idade_h", "P_peak", "L_bc", "queda_pct", "S", "R", "n_wicks",
    "entrada_mc", "stop_mc", "tp_mc", "rr", "power_candle", "resultado_A", "resultado_B", "tempo_trade_h", "motivo_saida",
    "versao_config",
]
# extras do POS-RUNNER (custo 2x, base pareada, atraso do alerta...): CSV de detalhe, fora do contrato do handoff
POS_RUNNER_DETALHE_COLUMNS = [
    "id", "data", "token", "contrato", "pool", "launchpad", "dex", "tf", "n_entrada", "primario", "onda", "alerta_enviado",
    "atraso_alerta_s", "entrada_ts", "entrada_mc_paper", "ambiguo_A", "ambiguo_B", "bruto_A", "bruto_B", "custo2x_A", "custo2x_B",
    "R_A", "R_B", "tempo_B_h", "base_n", "base_A", "base_B", "edge_A", "edge_B", "vol_ratio_rompimento", "cobertura_ate_topo",
    "status", "versao_config",
    # atributos das regras do operador (2026-10-16): nenhum e filtro
    "faixa_pico", "S_acima_100k", "R_S", "idade_grad_d", "max_caminho_A_pct", "max_caminho_B_pct",
]
# POS-RUNNER-V1 ("regras do professor"): contrato CSV proprio, independente do V0 (mesmo espirito das colunas
# do handoff do V0 -- data/token/contrato/launchpad/tf/idade/pico/L_bc/queda/S/R/n_wicks/entrada/stop/tp/rr/
# power_candle/resultado/tempo/motivo/versao_config -- mais o que a V1 pede: hora BRT, origem, tags, janela de
# ouro, teste_vol_ratio, holders/authority/liquidez (None por ora) e perdido_offline).
POS_RUNNER_V1_COLUMNS = [
    "data", "hora_brt", "chain", "token", "contrato", "launchpad", "tf", "idade_h", "janela_ouro",
    "topo", "L_bc", "queda_pct", "S", "R", "n_wicks", "gatilho", "entrada_mc", "stop_mc", "risco_pct",
    "tp1_mc", "exit_full_mc", "resultado_liq_pct", "tempo_trade_h", "motivo_saida", "tags",
    "holders_tag", "mint_authority", "freeze_authority", "liquidez_usd", "teste_vol_ratio", "origem",
    "versao_config_v1", "perdido_offline",
    # instrumentacao de medicao (sem mudar regra nenhuma): colunas acrescentadas no FIM, nunca no meio.
    "ts_fechamento_candle", "ts_alerta", "ts_envio_telegram", "retorno_sol_dia",
    # sequencial do sinal dentro do MESMO token (mint): 1o ENTRADA do mint = 1, 2o = 2, etc. -- agrupamento
    # por token no /relatorio e na analise Monte Carlo (ver detector_v1.py: "uma decisao por zona; nova
    # maxima acima de P_peak = nova onda" -- varias ENTRADA no mesmo mint, com a 1a ainda aberta, sao POR
    # DESENHO, nao erro; ver docs/pos-runner-v1/INTERPRETACOES.md #11).
    "token_signal_seq",
    # PEDIDO CONSOLIDADO FASE 1 (DexPaprika): fonte do candle que gerou a decisao ("gt"|"dexpaprika").
    "fonte_candle",
]
POS_RUNNER_V1_FILTRADOS_COLUMNS = ["data", "chain", "token", "contrato", "motivo", "valor", "versao_config_v1"]
# feedback do operador na V1 (FASE 3): 1 linha por (sinal, acao) -- ver pr1_feedback.
POS_RUNNER_V1_FEEDBACK_COLUMNS = [
    "data", "hora_brt", "chain", "token", "contrato", "tf", "acao", "voto", "valor", "texto", "chat_id",
    "versao_config_v1",
    # instrumentacao de medicao: preco real do /entrei|/sai e o slippage contra a referencia do alerta/saida.
    "preco_real", "slippage_entrada_pct", "slippage_saida_pct",
]
# /pulei <pool|ticker> <motivo>: sinal da V1 que o operador VIU e decidiu NAO executar (registro separado
# de pr1_feedback -- feedback e sobre um trade que o operador fez; aqui e o oposto, nunca um trade).
POS_RUNNER_V1_PULADOS_COLUMNS = ["data", "chain", "token", "contrato", "motivo", "versao_config_v1"]
# PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 3b: 1 linha por (candle, campo) divergente -- so log.
POS_RUNNER_V1_DEXPAPRIKA_COLUMNS = [
    "data", "chain", "token", "contrato", "tf", "candle_ts", "campo", "valor_gt", "valor_dexpaprika",
    "diff_pct", "versao_config_v1",
]

SCHEMA_VERSION = 1
PR_SIGNALS_DDL = """CREATE TABLE IF NOT EXISTS pr_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, pool TEXT NOT NULL, tf TEXT NOT NULL, n INTEGER NOT NULL, primario INTEGER,
  decision_ts REAL, mint TEXT, symbol TEXT, launchpad TEXT, dex TEXT, versao_config TEXT, event_json TEXT,
  status TEXT NOT NULL DEFAULT 'aberto', result_a REAL, result_b REAL, reason_a TEXT, reason_b TEXT, tempo_h REAL,
  detail_json TEXT, base_json TEXT, tg_message_id INTEGER, alert_ts REAL, closed_ts REAL, UNIQUE (pool, tf, n, versao_config)
);"""
PR_SIGNALS_COLS = {
    "id", "pool", "tf", "n", "primario", "decision_ts", "mint", "symbol", "launchpad", "dex", "versao_config", "event_json",
    "status", "result_a", "result_b", "reason_a", "reason_b", "tempo_h", "detail_json", "base_json", "tg_message_id", "alert_ts",
    "closed_ts",
}
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
-- POS-RUNNER-V0 ao vivo (tabelas novas; bancos antigos ganham elas sem migracao)
-- status do pool: pendente (falta linhagem) -> verificado (fila) -> ativo -> encerrado | rejeitado
CREATE TABLE IF NOT EXISTS pr_pools (
  pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, quote TEXT, launchpad TEXT, dex TEXT, grad_ts REAL, l_bc REAL,
  supply REAL, status TEXT NOT NULL, found_ts REAL, added_ts REAL, checked_ts REAL, mc_found REAL, motivo TEXT, info TEXT
);
CREATE INDEX IF NOT EXISTS pr_pools_status ON pr_pools (status);
-- candles de MC (USD) que o detector ja consumiu: CONGELADOS (so acrescenta; reiniciar refaz o mesmo estado)
CREATE TABLE IF NOT EXISTS pr_bars (
  pool TEXT NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL, v REAL, filled INTEGER,
  -- PEDIDO CONSOLIDADO FASE 1 (DexPaprika): fonte do candle ("gt"|"dexpaprika"). NUNCA lida por
  -- `pr_bars()`/o detector (que so seleciona ts,o,h,l,c,v,filled) -- auditoria/CSV, nunca entra no hot path.
  fonte TEXT NOT NULL DEFAULT 'gt',
  PRIMARY KEY (pool, tf, ts)
);
""" + PR_SIGNALS_DDL + """
CREATE INDEX IF NOT EXISTS pr_signals_open ON pr_signals (status);
CREATE TABLE IF NOT EXISTS pr_alerts (key TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS pr_trade_links (trade_id INTEGER PRIMARY KEY, pr_signal_id INTEGER NOT NULL);
-- gestao de banca ao vivo (addendum de relatorio, 2026-10-16): estado por ajuste (tf x variante x versao_config),
-- persistido entre reinicios -- BankrollState.to_json/from_json (signals_mvp/pos_runner/bankroll.py)
CREATE TABLE IF NOT EXISTS pr_bankroll_state (
  tf TEXT NOT NULL, variante TEXT NOT NULL, versao_config TEXT NOT NULL, state_json TEXT NOT NULL,
  PRIMARY KEY (tf, variante, versao_config)
);
-- uma linha POR entrada fechada (ou "pulada"); nunca reescrita (cada sinal fecha so uma vez por variante)
CREATE TABLE IF NOT EXISTS pr_bankroll_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tf TEXT NOT NULL, variante TEXT NOT NULL,
  versao_config TEXT NOT NULL, pr_signal_id INTEGER NOT NULL, row_json TEXT NOT NULL,
  UNIQUE (pr_signal_id, variante)
);
-- POS-RUNNER-V1 ("regras do professor", PROMPT DEFINITIVO): estrategia INDEPENDENTE do V0 (versao_config_v1
-- e um hash separado); candles compartilhados com o V0 (mesmo pr_bars, por pool+tf). Idempotencia pela chave
-- UNIQUE (chain, pool, tf, evento, ts_fechamento) do item 3.7: um sinal por decisao, nunca duplicado num
-- reinicio, reconstruido a partir dos candles congelados.
CREATE TABLE IF NOT EXISTS pr1_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chain TEXT NOT NULL, pool TEXT NOT NULL, tf TEXT NOT NULL,
  evento TEXT NOT NULL DEFAULT 'ENTRADA', ts_fechamento INTEGER NOT NULL,
  mint TEXT, symbol TEXT, launchpad TEXT, dex TEXT, versao_config_v1 TEXT NOT NULL,
  gatilho TEXT, tags TEXT, janela_ouro TEXT, hora_brt TEXT, origem TEXT, teste_vol_ratio REAL,
  event_json TEXT, status TEXT NOT NULL DEFAULT 'aberto',
  entry_price REAL, stop REAL, topo REAL, s_suporte REAL, r_resistencia REAL,
  tp1_price REAL, tp1_ts REAL, exit_full_price REAL, exit_full_ts REAL,
  result_net REAL, reason TEXT, tempo_h REAL,
  holders_tag TEXT, mint_authority TEXT, freeze_authority TEXT, liquidez_usd REAL,
  tg_message_id INTEGER, alert_ts REAL, closed_ts REAL,
  -- instrumentacao de medicao (sem mudar regra nenhuma -- ver _ensure_columns para bancos ja existentes):
  -- ts_fechamento_candle duplica ts_fechamento (epoch explicito p/ analise); ts_alerta e quando o bot DECIDIU
  -- alertar (antes do envio); ts_envio_telegram e o MESMO instante de alert_ts, so com nome mais claro;
  -- retorno_sol_dia e o retorno % do SOL/USD nas 24h antes de ts_fechamento (so leitura da cotacao JA
  -- cacheada, nunca uma chamada nova -- None quando a cobertura cacheada nao alcanca).
  ts_fechamento_candle INTEGER, ts_alerta REAL, ts_envio_telegram REAL, retorno_sol_dia REAL,
  -- sequencial do sinal dentro do MESMO token (mint) -- ver POS_RUNNER_V1_COLUMNS acima.
  token_signal_seq INTEGER,
  -- PEDIDO CONSOLIDADO FASE 1 (DexPaprika): fonte do candle que gerou a decisao ("gt"|"dexpaprika") --
  -- "dexpaprika" so no fallback de atualizacao recente (item 3a), nunca na reconstrucao do setup.
  fonte_candle TEXT NOT NULL DEFAULT 'gt',
  UNIQUE (chain, pool, tf, evento, ts_fechamento)
);
CREATE INDEX IF NOT EXISTS pr1_signals_open ON pr1_signals (status);
-- tudo que o filtro cortou (dado_invalido, filtrado_mc_baixo, filtrado_idade): contado no resumo diario,
-- nunca silencioso (item 2.4/3.6 do prompt).
CREATE TABLE IF NOT EXISTS pr1_filtrados (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, chain TEXT, pool TEXT, mint TEXT, symbol TEXT,
  motivo TEXT NOT NULL, valor TEXT, versao_config_v1 TEXT
);
-- uptime (item "registro completo"): um par inicio/fim por execucao continua do processo.
CREATE TABLE IF NOT EXISTS pr1_uptime (
  id INTEGER PRIMARY KEY AUTOINCREMENT, inicio_ts REAL NOT NULL, fim_ts REAL, motivo_fim TEXT
);
-- gestao de banca da V1 (item 2.10): mesmo padrao do pr_bankroll_* do V0, 1 ajuste por tf (sem variante A/B).
CREATE TABLE IF NOT EXISTS pr1_bankroll_state (
  tf TEXT NOT NULL, versao_config_v1 TEXT NOT NULL, state_json TEXT NOT NULL, PRIMARY KEY (tf, versao_config_v1)
);
CREATE TABLE IF NOT EXISTS pr1_bankroll_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tf TEXT NOT NULL, versao_config_v1 TEXT NOT NULL,
  pr1_signal_id INTEGER NOT NULL, row_json TEXT NOT NULL, UNIQUE (pr1_signal_id)
);
-- feedback do operador na V1 (FASE 3 do prompt definitivo): botoes 👍/👎/📝 e os comandos /entrei, /sai, /nota.
-- 1 linha por (sinal, acao) -- repetir a acao (clicar 2x, rodar o comando de novo) ATUALIZA a linha, nunca
-- duplica (item 1/2 da Fase 3). `acao` em {'voto','nota','entrei','sai'}; `voto` so para acao='voto'
-- ('bom'/'ruim'); `valor` = preco para acao in ('entrei','sai'); `texto` = nota para acao='nota'.
CREATE TABLE IF NOT EXISTS pr1_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, pr1_signal_id INTEGER NOT NULL, chain TEXT, pool TEXT, tf TEXT,
  mint TEXT, symbol TEXT, versao_config_v1 TEXT, acao TEXT NOT NULL, voto TEXT, valor REAL, texto TEXT,
  chat_id TEXT, criado_ts REAL NOT NULL, atualizado_ts REAL NOT NULL,
  -- instrumentacao de medicao: preco_real duplica `valor` p/ nome claro (so para acao in ('entrei','sai'));
  -- slippage_entrada_pct = preco_real contra entry_price do alerta; slippage_saida_pct = preco_real contra
  -- a ULTIMA referencia que a V1 alcancou (exit_full_price, senao tp1_price, senao stop) -- None quando
  -- nenhuma existe ainda (nunca inventa referencia).
  preco_real REAL, slippage_entrada_pct REAL, slippage_saida_pct REAL,
  UNIQUE (pr1_signal_id, acao)
);
-- /pulei <pool|ticker> <motivo>: sinal da V1 que o operador VIU e decidiu NAO executar. Tabela separada de
-- pr1_feedback (feedback e sobre um trade que o operador FEZ; aqui e o oposto) -- nunca conta como paper
-- nem como execucao manual, so como "visto e pulado".
CREATE TABLE IF NOT EXISTS pr1_pulados (
  id INTEGER PRIMARY KEY AUTOINCREMENT, pr1_signal_id INTEGER, chain TEXT, pool TEXT, symbol TEXT,
  motivo TEXT NOT NULL, chat_id TEXT, versao_config_v1 TEXT, criado_ts REAL NOT NULL
);
-- PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 3b: conferencia cruzada SO LOG, nunca decide. Uma linha por
-- (candle, campo) divergente alem da tolerancia configurada; `candle_divergente` (tag informativa no
-- sinal, se houver) nunca bloqueia nada -- so isto grava o detalhe pra auditoria.
CREATE TABLE IF NOT EXISTS pr1_dexpaprika_divergencias (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, chain TEXT, pool TEXT, mint TEXT, symbol TEXT,
  tf TEXT, candle_ts INTEGER, campo TEXT NOT NULL, valor_gt REAL, valor_dexpaprika REAL, diff_pct REAL,
  versao_config_v1 TEXT
);
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
            self._migrate_pr_signals()
            # instrumentacao de medicao: banco do operador ja existe SEM essas colunas (CREATE TABLE IF NOT
            # EXISTS acima nao alcanca tabela ja criada) -- ALTER TABLE idempotente, nunca muda dado existente.
            self._ensure_columns("pr1_signals", {
                "ts_fechamento_candle": "INTEGER", "ts_alerta": "REAL", "ts_envio_telegram": "REAL",
                "retorno_sol_dia": "REAL", "token_signal_seq": "INTEGER",
                "fonte_candle": "TEXT NOT NULL DEFAULT 'gt'",
            })
            self._ensure_columns("pr_bars", {"fonte": "TEXT NOT NULL DEFAULT 'gt'"})
            self._ensure_columns("pr1_feedback", {
                "preco_real": "REAL", "slippage_entrada_pct": "REAL", "slippage_saida_pct": "REAL",
            })
            current = self._db.execute("PRAGMA user_version").fetchone()[0]
            if current == 0:
                self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif current > SCHEMA_VERSION:
                raise RuntimeError(f"banco {paths.db} e de uma versao mais nova do bot (schema {current})")
        self._dirty = {"sinais": True, "descartados": True, "trades": True, "detalhe": True, "pos_runner": True,
                       "pos_runner_detalhe": True, "pos_runner_banca": True, "pos_runner_v1": True,
                       "pos_runner_v1_filtrados": True, "pos_runner_v1_banca": True, "pos_runner_v1_feedback": True,
                       "pos_runner_v1_pulados": True, "pos_runner_v1_dexpaprika": True}
        self._warned: set[str] = set()

    def _migrate_pr_signals(self) -> None:
        """Banco da 1a versao da Parte B: sinal unico por (pool, tf, n). Com outra config a numeracao recomeca, entao
        a chave passa a incluir `versao_config` (senao um sinal novo seria descartado por colidir com um antigo)."""
        row = self._db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pr_signals'").fetchone()
        if row is None or "UNIQUE(pool,tf,n,versao_config)" in row[0].replace(" ", ""):
            return
        self._db.execute("BEGIN")
        try:
            self._db.execute("ALTER TABLE pr_signals RENAME TO pr_signals_v1")
            self._db.execute("DROP INDEX IF EXISTS pr_signals_open")
            self._db.execute(PR_SIGNALS_DDL)
            cols = [r[1] for r in self._db.execute("PRAGMA table_info(pr_signals_v1)").fetchall()]
            keep = ", ".join(c for c in cols if c in PR_SIGNALS_COLS)
            self._db.execute(f"INSERT INTO pr_signals ({keep}) SELECT {keep} FROM pr_signals_v1")
            self._db.execute("DROP TABLE pr_signals_v1")
            self._db.execute("CREATE INDEX IF NOT EXISTS pr_signals_open ON pr_signals (status)")
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        """ALTER TABLE ... ADD COLUMN idempotente (so para colunas que ainda nao existem) -- nunca toca em
        coluna/linha ja existente, so acrescenta."""
        existentes = {r[1] for r in self._db.execute(f"PRAGMA table_info({table})").fetchall()}
        for nome, tipo in columns.items():
            if nome not in existentes:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {nome} {tipo}")

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
            "SELECT t.*, s.decision_ts AS sdt, s.etiqueta AS setq, p.decision_ts AS pdt, p.tf AS ptf FROM operator_trades t "
            "LEFT JOIN signals s ON s.id=t.signal_id LEFT JOIN pr_trade_links l ON l.trade_id=t.id "
            "LEFT JOIN pr_signals p ON p.id=l.pr_signal_id ORDER BY t.ts, t.id"
        )
        out = []
        for r in self._all(sql):
            if r["sdt"] is not None:
                related = f"{iso_utc(r['sdt'])}|{r['setq']}"
            elif r["pdt"] is not None:
                related = f"{iso_utc(r['pdt'])}|pos_runner_{r['ptf']}"
            else:
                related = ""
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
            "pos_runner": (self.paths.pos_runner_csv, lambda: (POS_RUNNER_COLUMNS, self._pos_runner_rows())),
            "pos_runner_detalhe": (self.paths.pos_runner_detalhe_csv, self._pos_runner_detail_rows),
            "pos_runner_banca": (self.paths.pos_runner_banca_csv, self._pos_runner_banca_header_rows),
            "pos_runner_v1": (self.paths.pos_runner_v1_csv, lambda: (POS_RUNNER_V1_COLUMNS, self._pos_runner_v1_rows())),
            "pos_runner_v1_filtrados": (self.paths.pos_runner_v1_filtrados_csv,
                                       lambda: (POS_RUNNER_V1_FILTRADOS_COLUMNS, self._pos_runner_v1_filtrados_rows())),
            "pos_runner_v1_banca": (self.paths.pos_runner_v1_banca_csv, self._pos_runner_v1_banca_header_rows),
            "pos_runner_v1_feedback": (self.paths.pos_runner_v1_feedback_csv,
                                       lambda: (POS_RUNNER_V1_FEEDBACK_COLUMNS, self._pos_runner_v1_feedback_rows())),
            "pos_runner_v1_pulados": (self.paths.pos_runner_v1_pulados_csv,
                                      lambda: (POS_RUNNER_V1_PULADOS_COLUMNS, self._pos_runner_v1_pulados_rows())),
            "pos_runner_v1_dexpaprika": (self.paths.pos_runner_v1_dexpaprika_csv,
                                        lambda: (POS_RUNNER_V1_DEXPAPRIKA_COLUMNS, self._pos_runner_v1_dexpaprika_rows())),
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

    # -- POS-RUNNER-V0 ao vivo ------------------------------------------------------------------
    def pr_pool(self, pool: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr_pools WHERE pool=?", (pool,))

    def pr_upsert_pool(self, pool: str, **fields: Any) -> None:
        """Atualiza so os campos dados (pool existente) ou insere (pool novo: `status` obrigatorio)."""
        with self._lock:
            if self._db.execute("SELECT 1 FROM pr_pools WHERE pool=?", (pool,)).fetchone() is not None:
                if fields:
                    self._db.execute(f"UPDATE pr_pools SET {', '.join(f'{k}=?' for k in fields)} WHERE pool=?", [*fields.values(), pool])
                return
            cols = ["pool", *fields]
            self._db.execute(f"INSERT INTO pr_pools ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [pool, *fields.values()])

    def pr_pools(self, *statuses: str) -> list[sqlite3.Row]:
        """Pools nos status pedidos (todos se nenhum), na ordem em que foram achados."""
        if not statuses:
            return self._all("SELECT * FROM pr_pools ORDER BY found_ts, pool")
        marks = ", ".join("?" * len(statuses))
        return self._all(f"SELECT * FROM pr_pools WHERE status IN ({marks}) ORDER BY found_ts, pool", statuses)

    def pr_pool_for_mint(self, mint: str) -> Optional[sqlite3.Row]:
        """Pool ja acompanhado (ou na fila/verificacao) do mesmo token: um pool por token."""
        return self._one("SELECT * FROM pr_pools WHERE mint=? AND status NOT IN ('rejeitado') LIMIT 1", (mint,))

    def pr_bars(self, pool: str, tf: str) -> list[tuple]:
        """(ts, open, high, low, close, volume, preenchido) em ordem de tempo."""
        rows = self._all("SELECT ts, o, h, l, c, v, filled FROM pr_bars WHERE pool=? AND tf=? ORDER BY ts", (pool, tf))
        return [tuple(r) for r in rows]

    def pr_append_bars(self, pool: str, tf: str, rows: Sequence[tuple], fonte: str = "gt") -> None:
        """Acrescenta candles consumidos (ts, o, h, l, c, v, filled). Candle ja gravado nunca e reescrito.
        `fonte` ("gt"|"dexpaprika", PEDIDO CONSOLIDADO FASE 1): so auditoria -- `pr_bars()` continua
        selecionando so as 7 colunas de sempre, o detector nunca ve este campo."""
        if not rows:
            return
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.executemany(
                    "INSERT OR IGNORE INTO pr_bars (pool, tf, ts, o, h, l, c, v, filled, fonte) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(pool, tf, int(r[0]), r[1], r[2], r[3], r[4], r[5], int(bool(r[6])), fonte) for r in rows],
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def pr_insert_signal(self, row: dict) -> Optional[int]:
        cols = list(row)
        with self._lock:
            cur = self._db.execute(
                f"INSERT OR IGNORE INTO pr_signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols]
            )
            self._dirty["pos_runner"] = self._dirty["pos_runner_detalhe"] = True
            return cur.lastrowid if cur.rowcount else None

    def pr_update_signal(self, signal_id: int, **fields: Any) -> None:
        if not fields:
            return
        with self._lock:
            self._db.execute(f"UPDATE pr_signals SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", [*fields.values(), signal_id])
            self._dirty["pos_runner"] = self._dirty["pos_runner_detalhe"] = True

    def pr_signal(self, signal_id: int) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr_signals WHERE id=?", (signal_id,))

    def pr_signal_by_key(self, pool: str, tf: str, n: int, version: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr_signals WHERE pool=? AND tf=? AND n=? AND versao_config=?", (pool, tf, n, version))

    def pr_signals(self, status: Optional[str] = None, pool: Optional[str] = None, tf: Optional[str] = None) -> list[sqlite3.Row]:
        where, args = [], []
        for col, value in (("status", status), ("pool", pool), ("tf", tf)):
            if value is not None:
                where.append(f"{col}=?")
                args.append(value)
        sql = "SELECT * FROM pr_signals" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY decision_ts, id"
        return self._all(sql, args)

    def pr_signal_for_contract(self, contract: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr_signals WHERE mint=? ORDER BY decision_ts DESC, id DESC LIMIT 1", (contract,))

    def pr_version_start(self, version: str, ts: float) -> float:
        """Inicio da execucao CONTINUA atual de uma versao_config do POS-RUNNER. Reiniciar com a MESMA versao mantem o
        inicio (decisao tomada com o bot desligado ainda e dela); trocar de versao e voltar recomeca a contagem (o que
        foi decidido enquanto outra versao rodava nunca vira sinal desta)."""
        key = f"pr_versao_inicio:{version}"
        with self._lock:
            cur = self._db.execute("SELECT value FROM meta WHERE key='pr_versao_atual'").fetchone()
            if cur is None or cur[0] != version:
                self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, repr(float(ts))))
                self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('pr_versao_atual', ?)", (version,))
            else:
                self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (key, repr(float(ts))))
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return float(row[0])

    def pr_alert_once(self, key: str, ts: float) -> bool:
        """True na 1a vez que a chave aparece (alerta ainda nao enviado); False depois (nunca repete alerta)."""
        with self._lock:
            cur = self._db.execute("INSERT OR IGNORE INTO pr_alerts (key, ts) VALUES (?, ?)", (key, ts))
            return bool(cur.rowcount)

    def pr_alert_seen(self, prefix: str) -> bool:
        """Ja houve alerta com chave comecando por `prefix`? (ex.: um 👀 daquela onda antes de mandar o 🔴)."""
        # substr (e nao LIKE): endereco base58 diferencia maiuscula de minuscula
        return self._one("SELECT 1 FROM pr_alerts WHERE substr(key, 1, ?)=? LIMIT 1", (len(prefix), prefix)) is not None

    # -- gestao de banca ao vivo (addendum de relatorio, 2026-10-16) ------------------------------
    def pr_bankroll_load(self, tf: str, variante: str, versao_config: str) -> Optional[str]:
        row = self._one("SELECT state_json FROM pr_bankroll_state WHERE tf=? AND variante=? AND versao_config=?",
                        (tf, variante, versao_config))
        return row[0] if row else None

    def pr_bankroll_save(self, tf: str, variante: str, versao_config: str, state_json: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO pr_bankroll_state (tf, variante, versao_config, state_json) VALUES (?, ?, ?, ?)",
                (tf, variante, versao_config, state_json))

    def pr_bankroll_append(self, tf: str, variante: str, versao_config: str, pr_signal_id: int, row: dict, ts: float) -> bool:
        """Grava a linha da tabela (nunca reescreve: um sinal fecha so uma vez por variante). True se gravou agora."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO pr_bankroll_trades (ts, tf, variante, versao_config, pr_signal_id, row_json) "
                "VALUES (?, ?, ?, ?, ?, ?)", (ts, tf, variante, versao_config, pr_signal_id, json.dumps(row, default=str)))
            if cur.rowcount:
                self._dirty["pos_runner_banca"] = True
            return bool(cur.rowcount)

    def pr_bankroll_resumos(self) -> dict[str, dict]:
        """resumo atual (lido do estado salvo) por ajuste x versao_config -- pro resumo diario do Telegram."""
        from .pos_runner.bankroll import BankrollState
        out = {}
        for r in self._all("SELECT tf, variante, versao_config, state_json FROM pr_bankroll_state"):
            out[f"{r['tf']}/{r['variante']}@{r['versao_config'][:12]}"] = BankrollState.from_json(r["state_json"]).resumo()
        return out

    def _pos_runner_banca_header_rows(self) -> tuple[list[str], list[list[Any]]]:
        from .pos_runner.bankroll import COLUMNS, HEADER_LABELS
        header = [HEADER_LABELS.get(c, c) for c in COLUMNS]
        rows = []
        for r in self._all("SELECT row_json FROM pr_bankroll_trades ORDER BY ts, id"):
            d = json.loads(r[0])
            rows.append(["" if d.get(c) is None else d.get(c) for c in COLUMNS])
        return header, rows

    def pr_link_trade(self, trade_id: int, pr_signal_id: int) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO pr_trade_links (trade_id, pr_signal_id) VALUES (?, ?)", (trade_id, pr_signal_id))
            self._dirty["trades"] = True

    def pr_counts(self) -> dict[str, int]:
        pools = {r[0]: r[1] for r in self._all("SELECT status, COUNT(*) FROM pr_pools GROUP BY status")}
        signals = {r[0]: r[1] for r in self._all("SELECT status, COUNT(*) FROM pr_signals GROUP BY status")}
        return {"pools_" + k: v for k, v in pools.items()} | {"sinais_" + k: v for k, v in signals.items()}

    def pr_prune(self, now: float, keep_days: float = 21.0) -> dict:
        """Candles de pools encerrados/rejeitados ha mais de `keep_days` (a base pareada usa os recentes) e chaves de
        alerta velhas. Sinais e pools nunca sao apagados."""
        cutoff = now - keep_days * 86400.0
        with self._lock:
            bars = self._db.execute(
                "DELETE FROM pr_bars WHERE pool IN (SELECT pool FROM pr_pools WHERE status IN ('encerrado', 'rejeitado') "
                "AND COALESCE(checked_ts, found_ts, 0) < ?)", (cutoff,)).rowcount
            alerts = self._db.execute("DELETE FROM pr_alerts WHERE ts < ?", (now - 60 * 86400.0,)).rowcount
        return {"pr_bars": bars, "pr_alerts": alerts} if (bars or alerts) else {}

    @staticmethod
    def _pr_json(text: Optional[str]) -> dict:
        try:
            value = json.loads(text or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _pr_list(text: Optional[str]) -> list[str]:
        try:
            value = json.loads(text or "[]")
        except ValueError:
            return []
        return [str(x) for x in value] if isinstance(value, list) else []

    def _pos_runner_rows(self) -> list[list[Any]]:
        """EMENDA 2026-10-16 (grade de 24 combinacoes): o contrato ESTAVEL do handoff continua so a combinacao
        primaria (extremos); a 2a medida da queda (fechamentos) vai so em `pos_runner_detalhe.csv` (fora do
        contrato), nunca aqui."""
        out = []
        for r in self._all("SELECT * FROM pr_signals WHERE tf NOT LIKE '%\\_fecham' ESCAPE '\\' ORDER BY decision_ts, id"):
            d = self._pr_json(r["event_json"]).get("data", {})
            det = self._pr_json(r["detail_json"])
            entry = det.get("entrada") or d.get("close")      # entrada do paper (open seguinte); antes dele, o fechamento do sinal
            stop, tp = d.get("stop"), d.get("tp")
            rr = ((tp - entry) / (entry - stop)) if entry and stop and tp and entry > stop else None
            if r["status"] == "aberto":
                reason = "em_aberto"
            elif r["reason_a"] or r["reason_b"]:
                reason = f"A={r['reason_a'] or '-'}; B={r['reason_b'] or '-'}"
            else:
                reason = r["status"]
            age = d.get("idade_dias")
            out.append([
                iso_utc(r["decision_ts"]), csv_safe(r["symbol"]), r["mint"], r["launchpad"], r["tf"],
                _num(None if age is None else age * 24, 1), _num(d.get("P_peak_topo") or d.get("P_peak")),
                _num(d.get("L_bc")), _num(d.get("queda_pct"), 1), _num(d.get("S")), _num(d.get("R")),
                d.get("n_testes", d.get("n_wicks", "")),     # coluna do handoff: n de testes de suporte (wicks)
                _num(entry), _num(stop), _num(tp), _num(rr, 2), "sim" if d.get("power_candle") else "nao",
                _num(None if r["result_a"] is None else 100 * r["result_a"], 2), _num(None if r["result_b"] is None else 100 * r["result_b"], 2),
                _num(r["tempo_h"], 1), reason, r["versao_config"],
            ])
        return out

    def _pos_runner_detail_rows(self) -> tuple[list[str], list[list[Any]]]:
        rows = []
        for r in self._all("SELECT * FROM pr_signals ORDER BY decision_ts, id"):
            d = self._pr_json(r["event_json"]).get("data", {})
            det = self._pr_json(r["detail_json"])
            base = self._pr_json(r["base_json"])

            def pct(v: Any) -> Any:
                return _num(None if v is None else 100 * v, 2)

            edge = {v: (r[f"result_{v.lower()}"] - base[v]) if r[f"result_{v.lower()}"] is not None and base.get(v) is not None else None
                    for v in ("A", "B")}
            rows.append([
                r["id"], iso_utc(r["decision_ts"]), csv_safe(r["symbol"]), r["mint"], r["pool"], r["launchpad"], r["dex"] or "", r["tf"],
                r["n"], r["primario"], d.get("onda", ""), 1 if r["tg_message_id"] else 0,
                _num(None if r["alert_ts"] is None else r["alert_ts"] - r["decision_ts"], 1), iso_utc(det.get("entrada_ts")),
                _num(det.get("entrada")), det.get("ambiguo_A", ""), det.get("ambiguo_B", ""), pct(det.get("bruto_A")), pct(det.get("bruto_B")),
                pct(det.get("custo2x_A")), pct(det.get("custo2x_B")), _num(det.get("R_A"), 2), _num(det.get("R_B"), 2),
                _num(det.get("tempo_B_h"), 1), base.get("n", ""), pct(base.get("A")), pct(base.get("B")), pct(edge["A"]), pct(edge["B"]),
                _num(d.get("vol_ratio"), 2), _num(d.get("cobertura"), 3), r["status"], r["versao_config"],
                d.get("faixa_pico", ""), "" if d.get("S_acima_100k") is None else ("sim" if d["S_acima_100k"] else "nao"),
                _num(d.get("R_S"), 2), _num(d.get("idade_grad_dias"), 2), _num(det.get("max_caminho_A"), 1),
                _num(det.get("max_caminho_B"), 1),
            ])
        return POS_RUNNER_DETALHE_COLUMNS, rows

    # -- POS-RUNNER-V1 ("regras do professor") ------------------------------------------------------------
    def pr1_insert_signal(self, row: dict) -> Optional[int]:
        """Idempotente pela UNIQUE (chain,pool,tf,evento,ts_fechamento): reinicio nunca duplica um sinal."""
        cols = list(row)
        with self._lock:
            cur = self._db.execute(
                f"INSERT OR IGNORE INTO pr1_signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols],
            )
            self._dirty["pos_runner_v1"] = True
            return cur.lastrowid if cur.rowcount else None

    def pr1_update_signal(self, signal_id: int, **fields: Any) -> None:
        if not fields:
            return
        with self._lock:
            self._db.execute(f"UPDATE pr1_signals SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                             [*fields.values(), signal_id])
            self._dirty["pos_runner_v1"] = True

    def pr1_signal(self, signal_id: int) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr1_signals WHERE id=?", (signal_id,))

    def pr1_signal_by_key(self, chain: str, pool: str, tf: str, evento: str, ts_fechamento: int) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM pr1_signals WHERE chain=? AND pool=? AND tf=? AND evento=? AND ts_fechamento=?",
                         (chain, pool, tf, evento, ts_fechamento))

    def pr1_token_next_seq(self, mint: Optional[str]) -> int:
        """Sequencial do sinal dentro do MESMO token (mint): 1 para o 1o ENTRADA desse mint, 2 para o 2o,
        etc. -- varias ENTRADA no mesmo mint sao por desenho (zonas/ondas diferentes, ver detector_v1.py),
        token_signal_seq so marca a ordem pra agrupar por token no /relatorio e na analise Monte Carlo."""
        if not mint:
            return 1
        row = self._one("SELECT COUNT(*) AS n FROM pr1_signals WHERE mint=? AND evento='ENTRADA'", (mint,))
        return (row["n"] if row else 0) + 1

    def pr1_signals(self, status: Optional[str] = None, pool: Optional[str] = None, tf: Optional[str] = None) -> list[sqlite3.Row]:
        where, args = [], []
        for col, value in (("status", status), ("pool", pool), ("tf", tf)):
            if value is not None:
                where.append(f"{col}=?")
                args.append(value)
        sql = "SELECT * FROM pr1_signals" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY ts_fechamento, id"
        return self._all(sql, args)

    def pr1_add_filtrado(self, ts: float, chain: str, pool: str, mint: str, symbol: str, motivo: str, valor: str,
                         versao_config_v1: str) -> None:
        """Nunca silencioso (item 2.4/3.6): filtrado_mc_baixo, filtrado_idade e dado_invalido entram aqui e
        contam no resumo diario, mesmo sem nunca virar alerta."""
        with self._lock:
            self._db.execute(
                "INSERT INTO pr1_filtrados (ts,chain,pool,mint,symbol,motivo,valor,versao_config_v1) VALUES (?,?,?,?,?,?,?,?)",
                (ts, chain, pool, mint, symbol, motivo, valor, versao_config_v1),
            )
            self._dirty["pos_runner_v1_filtrados"] = True

    def pr1_version_start(self, version: str, ts: float) -> float:
        """Mesma ideia de `pr_version_start`, chave propria (nunca colide com a contagem do V0)."""
        key = f"pr1_versao_inicio:{version}"
        with self._lock:
            cur = self._db.execute("SELECT value FROM meta WHERE key='pr1_versao_atual'").fetchone()
            if cur is None or cur[0] != version:
                self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, repr(float(ts))))
                self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('pr1_versao_atual', ?)", (version,))
            else:
                self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (key, repr(float(ts))))
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return float(row[0])

    def pr1_filtrado_counts(self, since_ts: float) -> dict[str, int]:
        return {r[0]: r[1] for r in self._all(
            "SELECT motivo, COUNT(*) FROM pr1_filtrados WHERE ts>=? GROUP BY motivo", (since_ts,))}

    def pr1_uptime_start(self, ts: float) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO pr1_uptime (inicio_ts) VALUES (?)", (ts,))
            return int(cur.lastrowid)

    def pr1_uptime_stop(self, uptime_id: int, ts: float, motivo: str = "") -> None:
        self._exec("UPDATE pr1_uptime SET fim_ts=?, motivo_fim=? WHERE id=?", (ts, motivo, uptime_id))

    def pr1_uptime_hours(self, since_ts: float, now: float) -> float:
        """Horas ligado desde `since_ts` (uma sessao ainda aberta conta ate `now`)."""
        total = 0.0
        for row in self._all("SELECT inicio_ts, fim_ts FROM pr1_uptime WHERE COALESCE(fim_ts, ?)>=?", (now, since_ts)):
            ini = max(row["inicio_ts"], since_ts)
            fim = row["fim_ts"] if row["fim_ts"] is not None else now
            total += max(0.0, fim - ini)
        return total / 3600.0

    def _pos_runner_v1_rows(self) -> list[list[Any]]:
        out = []
        for r in self._all("SELECT * FROM pr1_signals WHERE evento='ENTRADA' ORDER BY ts_fechamento, id"):
            d = self._pr_json(r["event_json"]).get("data", {})
            age = d.get("idade_dias")
            gatilho = self._pr_list(r["gatilho"])
            tags = self._pr_list(r["tags"])
            if r["status"] == "aberto":
                motivo_saida = "em_aberto"
            elif r["reason"]:
                motivo_saida = r["reason"]
            else:
                motivo_saida = r["status"]
            out.append([
                iso_utc(r["ts_fechamento"]), r["hora_brt"] or "", r["chain"], csv_safe(r["symbol"]), r["mint"],
                r["launchpad"], r["tf"], _num(None if age is None else age * 24, 1), r["janela_ouro"] or "",
                _num(r["topo"]), _num(d.get("L_bc")), _num(d.get("queda_pct"), 1), _num(r["s_suporte"]), _num(r["r_resistencia"]),
                d.get("n_testes", ""), ",".join(gatilho),
                _num(r["entry_price"]), _num(r["stop"]), _num(d.get("risco_pct"), 1),
                _num(r["tp1_price"]), _num(r["exit_full_price"]), _num(None if r["result_net"] is None else 100 * r["result_net"], 2),
                _num(r["tempo_h"], 1), motivo_saida, ",".join(tags),
                r["holders_tag"] or "", r["mint_authority"] or "", r["freeze_authority"] or "", _num(r["liquidez_usd"]),
                _num(r["teste_vol_ratio"], 2), r["origem"] or "", r["versao_config_v1"],
                1 if r["status"] == "perdido_offline" else 0,
                r["ts_fechamento_candle"] if r["ts_fechamento_candle"] is not None else "",
                _num(r["ts_alerta"], 0), _num(r["ts_envio_telegram"], 0), _num(r["retorno_sol_dia"], 2),
                r["token_signal_seq"] if r["token_signal_seq"] is not None else "",
                r["fonte_candle"] or "gt",
            ])
        return out

    def _pos_runner_v1_filtrados_rows(self) -> list[list[Any]]:
        return [
            [iso_utc(r["ts"]), r["chain"], csv_safe(r["symbol"]), r["mint"], r["motivo"], csv_safe(r["valor"]), r["versao_config_v1"]]
            for r in self._all("SELECT * FROM pr1_filtrados ORDER BY ts, id")
        ]

    # -- feedback do operador na V1 (FASE 3: botoes 👍/👎/📝 + /entrei /sai /nota) -------------------------
    def pr1_feedback_upsert(self, signal_id: int, acao: str, chat_id: str, now: float, voto: Optional[str] = None,
                           valor: Optional[float] = None, texto: Optional[str] = None,
                           preco_real: Optional[float] = None, slippage_entrada_pct: Optional[float] = None,
                           slippage_saida_pct: Optional[float] = None) -> bool:
        """1 linha por (sinal, acao) -- repetir a acao (botao de novo, comando de novo) ATUALIZA, nunca
        duplica. False quando o sinal nao existe (comando/callback aponta pra um id que nao e da V1).
        `preco_real`/`slippage_*`: so para acao in ('entrei','sai') com preco informado (instrumentacao)."""
        signal = self.pr1_signal(signal_id)
        if signal is None:
            return False
        with self._lock:
            self._db.execute(
                "INSERT INTO pr1_feedback (pr1_signal_id,chain,pool,tf,mint,symbol,versao_config_v1,acao,voto,valor,texto,"
                "chat_id,criado_ts,atualizado_ts,preco_real,slippage_entrada_pct,slippage_saida_pct) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(pr1_signal_id,acao) DO UPDATE SET voto=excluded.voto, valor=excluded.valor, "
                "texto=excluded.texto, chat_id=excluded.chat_id, atualizado_ts=excluded.atualizado_ts, "
                "preco_real=excluded.preco_real, slippage_entrada_pct=excluded.slippage_entrada_pct, "
                "slippage_saida_pct=excluded.slippage_saida_pct",
                (signal_id, signal["chain"], signal["pool"], signal["tf"], signal["mint"], signal["symbol"],
                 signal["versao_config_v1"], acao, voto, valor, texto, chat_id, now, now,
                 preco_real, slippage_entrada_pct, slippage_saida_pct),
            )
            self._dirty["pos_runner_v1_feedback"] = True
        return True

    def pr1_feedback_for_signal(self, signal_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM pr1_feedback WHERE pr1_signal_id=? ORDER BY acao", (signal_id,))

    def pr1_feedback_votes_since(self, since_ts: float, until_ts: float, versao_config_v1: str) -> list[sqlite3.Row]:
        """Para o relatorio semanal (so votos 👍/👎, SO da versao atual -- nunca mistura versoes de config,
        complemento FASE 1.1 item 3 aplicado aqui tambem)."""
        return self._all(
            "SELECT f.*, s.gatilho AS sig_gatilho, s.tags AS sig_tags, s.janela_ouro AS sig_janela_ouro, "
            "s.ts_fechamento AS sig_ts_fechamento, s.result_net AS sig_result_net, "
            "s.mint_authority AS sig_mint_authority, s.freeze_authority AS sig_freeze_authority "
            "FROM pr1_feedback f "
            "JOIN pr1_signals s ON s.id = f.pr1_signal_id WHERE f.acao='voto' AND f.versao_config_v1=? "
            "AND s.ts_fechamento>=? AND s.ts_fechamento<?",
            (versao_config_v1, since_ts, until_ts),
        )

    def _pos_runner_v1_feedback_rows(self) -> list[list[Any]]:
        out = []
        for r in self._all(
            "SELECT f.*, s.ts_fechamento AS sig_ts_fechamento, s.hora_brt AS sig_hora_brt FROM pr1_feedback f "
            "JOIN pr1_signals s ON s.id = f.pr1_signal_id ORDER BY f.atualizado_ts, f.id"
        ):
            out.append([
                iso_utc(r["sig_ts_fechamento"]), r["sig_hora_brt"] or "", r["chain"], csv_safe(r["symbol"]), r["mint"],
                r["tf"], r["acao"], r["voto"] or "", "" if r["valor"] is None else r["valor"],
                csv_safe(r["texto"] or ""), r["chat_id"] or "", r["versao_config_v1"],
                _num(r["preco_real"], 6), _num(r["slippage_entrada_pct"], 2), _num(r["slippage_saida_pct"], 2),
            ])
        return out

    # -- /pulei (sinal visto e NAO executado -- instrumentacao, separado de pr1_feedback) -----------------
    def pr1_pulado_insert(self, ts: float, chain: Optional[str], pool: Optional[str], symbol: Optional[str],
                          motivo: str, chat_id: str, versao_config_v1: Optional[str],
                          pr1_signal_id: Optional[int]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO pr1_pulados (pr1_signal_id,chain,pool,symbol,motivo,chat_id,versao_config_v1,criado_ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (pr1_signal_id, chain, pool, symbol, motivo, chat_id, versao_config_v1, ts),
            )
            self._dirty["pos_runner_v1_pulados"] = True

    def pr1_pulados(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM pr1_pulados ORDER BY criado_ts, id")

    def _pos_runner_v1_pulados_rows(self) -> list[list[Any]]:
        return [
            [iso_utc(r["criado_ts"]), r["chain"] or "", csv_safe(r["symbol"] or ""), r["pool"] or "",
             csv_safe(r["motivo"]), r["versao_config_v1"] or ""]
            for r in self._all("SELECT * FROM pr1_pulados ORDER BY criado_ts, id")
        ]

    # -- conferencia cruzada DexPaprika (PEDIDO CONSOLIDADO FASE 1, item 3b) -- so log, nunca decide -------
    def pr1_dexpaprika_divergencia_insert(self, ts: float, chain: Optional[str], pool: Optional[str],
                                          mint: Optional[str], symbol: Optional[str], tf: str,
                                          candle_ts: int, campo: str, valor_gt: float,
                                          valor_dexpaprika: float, diff_pct: float,
                                          versao_config_v1: Optional[str]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO pr1_dexpaprika_divergencias (ts,chain,pool,mint,symbol,tf,candle_ts,campo,"
                "valor_gt,valor_dexpaprika,diff_pct,versao_config_v1) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, chain, pool, mint, symbol, tf, candle_ts, campo, valor_gt, valor_dexpaprika, diff_pct,
                 versao_config_v1),
            )
            self._dirty["pos_runner_v1_dexpaprika"] = True

    def pr1_dexpaprika_divergencias(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM pr1_dexpaprika_divergencias ORDER BY ts, id")

    def pr1_dexpaprika_divergencia_count_since(self, since_ts: float) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM pr1_dexpaprika_divergencias WHERE ts>=?", (since_ts,))
        return int(row["n"]) if row else 0

    def _pos_runner_v1_dexpaprika_rows(self) -> list[list[Any]]:
        return [
            [iso_utc(r["ts"]), r["chain"] or "", csv_safe(r["symbol"] or ""), r["mint"] or "", r["tf"] or "",
             r["candle_ts"] if r["candle_ts"] is not None else "", r["campo"], _num(r["valor_gt"], 8),
             _num(r["valor_dexpaprika"], 8), _num(r["diff_pct"], 3), r["versao_config_v1"] or ""]
            for r in self._all("SELECT * FROM pr1_dexpaprika_divergencias ORDER BY ts, id")
        ]

    # -- gestao de banca da V1 (item 2.10) --------------------------------------------------------
    def pr1_bankroll_load(self, tf: str, versao_config_v1: str) -> Optional[str]:
        row = self._one("SELECT state_json FROM pr1_bankroll_state WHERE tf=? AND versao_config_v1=?", (tf, versao_config_v1))
        return row[0] if row else None

    def pr1_bankroll_save(self, tf: str, versao_config_v1: str, state_json: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO pr1_bankroll_state (tf, versao_config_v1, state_json) VALUES (?, ?, ?)",
                (tf, versao_config_v1, state_json))

    def pr1_bankroll_append(self, tf: str, versao_config_v1: str, pr1_signal_id: int, row: dict, ts: float) -> bool:
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO pr1_bankroll_trades (ts, tf, versao_config_v1, pr1_signal_id, row_json) VALUES (?, ?, ?, ?, ?)",
                (ts, tf, versao_config_v1, pr1_signal_id, json.dumps(row, default=str)))
            if cur.rowcount:
                self._dirty["pos_runner_v1_banca"] = True
            return bool(cur.rowcount)

    def pr1_bankroll_resumos(self) -> dict[str, dict]:
        from .pos_runner.bankroll_v1 import BankrollStateV1
        out = {}
        for r in self._all("SELECT tf, versao_config_v1, state_json FROM pr1_bankroll_state"):
            out[f"{r['tf']}@{r['versao_config_v1'][:12]}"] = BankrollStateV1.from_json(r["state_json"]).resumo()
        return out

    def _pos_runner_v1_banca_header_rows(self) -> tuple[list[str], list[list[Any]]]:
        from .pos_runner.bankroll_v1 import COLUMNS, HEADER_LABELS
        header = [HEADER_LABELS.get(c, c) for c in COLUMNS]
        rows = []
        for r in self._all("SELECT row_json FROM pr1_bankroll_trades ORDER BY ts, id"):
            d = json.loads(r[0])
            rows.append(["" if d.get(c) is None else d.get(c) for c in COLUMNS])
        return header, rows
