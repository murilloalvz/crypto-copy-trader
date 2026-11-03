"""PEDIDO 2026-11-02 PARTE 2: coorte retrospectiva dos candidatos que nunca ganharam vaga (ver PARTE 1,
diagnostico_vagas.py/saude.py -- esta e a continuacao: "o que teria acontecido se eles tivessem entrado?").

SOMENTE LEITURA do detector/regra: reusa `DetectorV1`/`simulate_v1`/`CostModel` exatamente como `live.py`
os usa (MESMOS parametros `ParamsV1`/`ParamsV2` congelados, MESMO custo, MESMA regra de risco <3% =>
R s/d -- `PosRunnerLive.RISCO_IRREALISTA_MIN_PCT`). NUNCA altera `ParamsV1`/`ParamsV2`/hash, NUNCA grava em
`pr_pools`/`pr1_signals`/`pr2_signals`/`pr_funil_marcos`/qualquer tabela que o funil forward, H1 ou
`/analise` leem -- os sinais aqui sao sempre tag `retro_sem_vaga` e vivem SO no relatorio desta execucao.
A UNICA tabela nova escrita e `pr_retro_candidatos` (congelamento, abaixo); nenhuma tabela ja existente e
alterada.

Congelamento (1a execucao apenas, nunca recalculado depois -- amostra FIXA, nunca um alvo em movimento):
candidatos = pools DISTINTOS que ja apareceram em `pr_vaga_descartes` (todo o historico) e cujo `pr_pools`
NUNCA registrou 'ativo' -- aproximacao read-only (o schema nao guarda historico de status): exclui o
status atual 'ativo'/'dormente'/'encerrado' (dormente/encerrado so existem para quem FOI ativo) e
qualquer pool com linha em `pr_dormentes` (so existe para quem foi ativo e rotacionado,
`live.py: _rotacionar_vagas`) ou em `pr1_signals`/`pr2_signals` (so um pool ativo ganha detector,
`_detector_v1`/`_detector_v2` -- nunca um 'verificado'). A lista congelada (pool, mint, symbol, l_bc,
grad_ts, criado_ts, launchpad, mc_found) e gravada em `pr_retro_candidatos` com o sha256 da lista
ordenada de pools (`lista_hash`) e o timestamp do congelamento (`congelado_em`); toda execucao seguinte
LE de volta esta mesma lista, nunca recalcula.

Historico: `OhlcvStore.history` (MESMO modulo do bot ao vivo, cache em disco PROPRIO desta execucao --
`--cache-dir`, default `signals_mvp/dados/pos_runner_retro/ohlcv` -- nunca o cache do bot ao vivo, 100%
retomavel por execucao: a caminhada fica no JSON em disco, uma execucao interrompida continua exatamente
dali). `--max-chamadas-hora` (padrao 15) e um orcamento PROPRIO desta execucao (persistido em
`retro_orcamento.json` no mesmo `--cache-dir`, por hora UTC) para nunca competir com o limite de IP
compartilhado do bot ao vivo -- ao esgotar, a execucao atual para de pedir candle novo e IMPRIME o
relatorio so com o que ja tem; a proxima execucao retoma os candidatos que faltam. Fallback DexPaprika
(`worker.make_dexpaprika_provider`, MESMO toggle `DEXPAPRIKA`/`DEXPAPRIKA_API_KEY` do bot ao vivo) so
quando o GeckoTerminal falha (429/timeout/5xx) depois de esgotar as tentativas -- orcamento PROPRIO do
DexPaprika (creditos/breaker), nunca compartilha o `--max-chamadas-hora` do GT. Mesma validacao de candle
do bot ao vivo: `qualidade_v1.avaliar_qualidade` (dado_invalido bloqueia o candidato, mesmo motivo) e o
veto de candle suspeito (`qualidade_candle.motivo_suspeito`) ja embutido no proprio `DetectorV1`
(`_check_zone`) -- nenhuma logica de qualidade nova, reusa a mesma. Dedupe de candle ja vem do cache do
`OhlcvStore` (chave por `ts`). `contaminado_candle` e uma tag SO do operador (marcacao manual pos-fill
real, `scripts/marcar_contaminados.py`) -- nao existe fill real aqui, entao nunca se aplica (limitacao
documentada, nunca simulada).

Replay: candido a candido, causal (DetectorV1.update, zero lookahead), desde o candle que contem a
criacao do token. Cada `ENTRADA` e simulada com `simulate_v1` (MESMOS `ParamsV1`/`ParamsV2`/`CostModel`
congelados do bot ao vivo); SEM `candle_confiavel` (todo candle historico ja fechado ha muito tempo --
o mecanismo so existe pra incerteza de candle RECENTE, `simulate_v1` documenta "omitido = decisao
IDENTICA"). SEM cotacao SOL/USD cacheada (`sol_usd_at` sempre None) -- `CostModel` ja trata isso como o
caso conservador padrao (teto de fee PumpSwap, slippage 1%; MESMO fallback que o bot ao vivo usaria sem
cotacao cacheada, nunca um numero novo inventado). A guarda de atraso (`_late`, FASE 1 da PARTE 1) NUNCA
se aplica -- e retroativo por definicao; cada sinal carrega `retroativo=True` explicitamente no relatorio.
Risco real <3% exclui o R (`r_mult=None`, motivo `risco_irrealista`) -- MESMA regra de
`PosRunnerLive.RISCO_IRREALISTA_MIN_PCT`/`_motivo_exclusao_r`.

Relatorio: por candidato (pico MC do historico, chegou a RUNNER?, teve ENTRADA V1/V2?, R de cada). Agregado:
n com historico suficiente, % que chegou a runner, numero de sinais V1/V2, R medio/mediano (so entre os
R nao excluidos), taxa de acerto (net_ret>0 entre os fechados com R valido), e comparacao com a populacao
ADMITIDA (pools que JA tiveram vaga -- `pr_pools.status IN ('ativo','dormente','encerrado')`): mc_found,
idade (desde a criacao), % que chegou a runner (`pr_funil_marcos.etapa='runner'`, MESMO marco que a PARTE 1
ja persiste ao vivo -- leitura, nunca recalculo). Aviso explicito: replicacao exploratoria, NUNCA soma ao
N=30 do pre-registro (`docs/pos-runner-v1/PROTOCOLO_VALIDACAO.md`) nem a nenhum H1/H2 confirmatorio.

Uso (na VM, TMUX SEPARADO -- nunca a mesma sessao/janela do bot ao vivo, pra nunca competir visualmente
nem acidentalmente receber um Ctrl+C do operador mirado no bot):
    tmux new -s retro
    python -m signals_mvp.scripts.avaliar_candidatos_retro --db signals_mvp/dados/estado.sqlite
    # Ctrl+B D para destacar; a execucao e idempotente/retomavel -- rodar de novo so avanca o que falta.
    python -m signals_mvp.scripts.avaliar_candidatos_retro --db signals_mvp/dados/estado.sqlite --max-chamadas-hora 10

Nao precisa reiniciar o bot ao vivo (so leitura do mesmo arquivo `.sqlite`, cache/orcamento proprios em
diretorio separado; o bot ao vivo nunca sabe que esta execucao existe).

PATCH 2026-11-02 (relato do operador: 60/60 candidatos saem `sem_dados_pool` sem nenhuma chamada de
rede). Dois achados, nao um so:

1) `l_bc` NUNCA existe em `pr_pools` para um pool que nunca foi 'ativo' -- `live.py` so grava `l_bc`
   dentro de `_refresh_core` (`l_bc = seq[0].open`), que SO roda pra pool ja 'ativo'. A 1a versao
   deste script exigia `row["l_bc"]` JA preenchido (herdado do congelamento) -- por isso bloqueava
   100% dos candidatos ANTES de qualquer chamada de rede. Corrigido: `l_bc` agora e CALCULADO aqui
   (abaixo), nunca mais lido como pre-requisito.
2) bug relacionado, mais grave (ainda nao exercitado em produção por causa do (1), mas teria
   quebrado o replay silenciosamente): a 1a versao chamava `OhlcvStore.history(pool, tf, criado_ts)`
   SEM `currency=`, cujo padrao e `currency="usd", side="base"` -- preco POR TOKEN em USD, nao Market
   Cap (`live.py` so atinge MC multiplicando por `supply` via `to_mc_bars`, que precisa de uma serie
   de cotacao SOL/USD que este script nao tem). Alimentar o detector com preco-por-token (tipicamente
   < US$0,001) em vez de MC faria `runner_min_mc=300_000`/`min_mc_usd=100_000` NUNCA disparar -- fase
   ficaria `sem_fase` pra sempre, silenciosamente, sem erro. Corrigido: busca em `currency="usd"` (GT
   converte pra USD por conta propria, sem depender de cotacao cacheada) e multiplica por
   `pr_pools.supply` aqui mesmo -- MESMA formula de MC (`preco_usd x supply`) que `to_mc_bars` usa,
   so com a fonte da cotacao USD sendo o proprio GT em vez da serie cacheada do bot ao vivo (unica
   divergencia de `live.py`, documentada, nunca uma regra nova). Fetch agora comeca em `grad_ts`
   (graduacao, igual a `live.py: _fetch_gt`), nao em `criado_ts` (criacao do TOKEN, que pode ser dias
   ANTES do pool existir -- comecar dali so desperdiçaria chamadas andando por paginas vazias).
   `criado_ts` ausente (idade desconhecida) NUNCA bloqueia mais: passado como `None` pro `DetectorV1`
   exatamente como ele ja trata isso ao vivo (`age_days()`/`in_age_window()` None/False -- ENTRADA
   cai em FORA_DA_IDADE, nunca um crash nem um numero inventado); o candidato fica `idade_desconhecida`
   no relatorio, nunca escondido.

`pr_retro_candidatos` ganhou as colunas `supply`/`side` (migracao `ALTER TABLE` idempotente, roda em
toda conexao); candidatos JA congelados (lista/hash/`congelado_em` INTOCADOS) sao retro-preenchidos
a partir de `pr_pools` na mesma conexao. `sem_dados_pool` agora e reservado ao caso estrutural (sem
endereco de pool, ou `grad_ts`/`supply` da linhagem ainda incompletos -- raro/defensivo, nunca o caso
comum); `pendente` (orcamento esgotado nesta execucao, ainda nao buscado) e `sem_historico` (buscado,
GT/DexPaprika sem candle, ou `dado_invalido`) sao as 2 categorias que agora realmente se populam.

PATCH 2026-11-02 (2a rodada -- relato do operador: uma execucao mostrou 5 candidatos "ok", a SEGUINTE
(orcamento esgotado) relatou 0/60 com historico): `executar()` nunca persistia o resultado de um
candidato ja processado -- cada execucao recomecava do zero em memoria, e so o cache de CANDLE em
disco (`OhlcvStore`) sobrevivia entre execucoes. Pior: mesmo um candidato "ok" numa execucao anterior
disparava uma chamada de rede NOVA na execucao seguinte (`OhlcvStore.history()` sempre confere "cauda
nova" ate `now`), e se o orcamento JA estivesse zerado por outro candidato antes dele na lista, essa
chamada levantava `ApiError("budget")` e o candidato "ok" virava "pendente" de novo -- nunca refeito de
verdade, so NUNCA MOSTRADO.

Fix: `pr_retro_resultados` (nova tabela, 1 linha por pool) guarda o resultado completo -- categoria,
`n_candles`, `pico_mc`, `chegou_runner`, `idade_desconhecida`, sinais V1/V2 (JSON, com R por sinal),
`versao_config_v1`/`versao_config_v2` (hash do `ParamsV1`/`ParamsV2` usado -- um resultado "ok" so e
reaproveitado se os hashes ainda baterem com os congelados agora) e `ts_processado`. Um candidato com
categoria `ok` persistida NUNCA e reprocessado (zero chamada de rede) a menos que `--reprocessar` seja
passado explicitamente. O orcamento SO entra em jogo pra candidatos que ainda precisam de uma chamada
de rede nova; o relatorio em si e sempre montado a partir do que esta persistido (+ o que acabou de ser
processado nesta execucao), nunca gasta orcamento so para IMPRIMIR.

PATCH 2026-11-02 (3a rodada): dois problemas, nunca mudam detector/hashes/regras.

1) Coorte retrospectiva x ao vivo -- um candidato CONGELADO pode, depois do congelamento, ganhar
   vaga de verdade (`pr_pools.added_ts` passa a existir -- ex.: PAWCAT/CATBOT admitidos em
   02/11 21:43Z). Sem tratamento, o replay retroativo continuaria rodando sobre TODO o historico em
   cache, inclusive candles de DEPOIS da admissao -- que ja sao territorio do funil FORWARD
   (`pr1_signals`/`pr2_signals`), gerando o MESMO sinal contado 2x (retro E forward). Fix: quando
   `pr_pools.added_ts` existe pro pool, o replay usa `pr_bars` (tabela do bot ao vivo, SO LEITURA,
   nunca escrita por este script) TRUNCADO em `decision_ts < added_ts` -- nenhum candle igual ou
   posterior a admissao chega ao detector, pela construcao (`bar.ts + step < added_ts`), nunca por
   um filtro a posteriori em cima do evento. Zero chamada de rede nesse caso (candle ja existe em
   `pr_bars`, buscado pelo bot ao vivo). Candidato fica com `admitido_apos_congelamento=True` no
   relatorio. A lista/hash congelados (`pr_retro_candidatos`) NUNCA mudam -- so a FORMA de processar
   um candidato que ja esta na lista. Um resultado "ok" persistido ANTES da admissao e invalidado e
   reprocessado (1 unica vez, sem rede) quando `added_ts` passa a existir -- ver `executar()`.
2) `pr_api_uso` so cobria `poll_pool` -- as outras finalidades (baseline, trajetoria, carteiras,
   verificacao_candidato, sombra, radar, coorte_retro, descoberta) nunca eram contadas. Ver
   `live.py`/`worker.py` pelas novas chamadas `pr_api_uso_insert(..., finalidade="coorte_retro", ...)`
   deste PROPRIO script (unica finalidade que um processo FORA do bot ao vivo grava).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..http import ApiError, HttpClient, RateLimiter
from ..pos_runner.candles import Bar, OhlcvStore, fill_gaps, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.live import PosRunnerLive
from ..pos_runner.parte_a.pipeline import DEX_OF_LAUNCHPAD
from ..pos_runner.params_v1 import ParamsV1, load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.qualidade_v1 import avaliar_qualidade
from ..pos_runner.simulate_v1 import simulate_v1
from ..worker import make_dexpaprika_provider

log = logging.getLogger("signals_mvp.scripts.avaliar_candidatos_retro")

RETRO_TAG = "retro_sem_vaga"
DEFAULT_MAX_CHAMADAS_HORA = 15
GT_BASE = "https://api.geckoterminal.com/api/v2"
RISCO_IRREALISTA_MIN_PCT = PosRunnerLive.RISCO_IRREALISTA_MIN_PCT   # MESMA regra do bot ao vivo, nunca duplicada

DDL_RETRO_CANDIDATOS = """
CREATE TABLE IF NOT EXISTS pr_retro_candidatos (
  pool TEXT PRIMARY KEY, mint TEXT, symbol TEXT, launchpad TEXT, l_bc REAL, grad_ts REAL, criado_ts REAL,
  mc_found REAL, lista_hash TEXT NOT NULL, congelado_em REAL NOT NULL
);
"""
# PATCH 2026-11-02: supply/side precisam calcular MC (ver docstring do modulo) -- `ALTER TABLE` em
# bancos que ja rodaram a versao anterior deste script (a lista/hash/congelado_em NUNCA mudam).
_COLUNAS_NOVAS = {"supply": "REAL", "side": "TEXT"}

# PATCH 2026-11-02 (2a rodada): resultado persistido por candidato -- um candidato "ok" nunca e
# reprocessado (ver docstring do modulo); nenhuma ligacao com `pr1_signals`/`pr2_signals` (sinais
# retroativos nunca entram ali).
DDL_RETRO_RESULTADOS = """
CREATE TABLE IF NOT EXISTS pr_retro_resultados (
  pool TEXT PRIMARY KEY, categoria TEXT NOT NULL, motivo_sem_historico TEXT, n_candles INTEGER,
  pico_mc REAL, chegou_runner INTEGER NOT NULL DEFAULT 0, idade_desconhecida INTEGER NOT NULL DEFAULT 0,
  sinais_v1_json TEXT NOT NULL DEFAULT '[]', sinais_v2_json TEXT NOT NULL DEFAULT '[]',
  versao_config_v1 TEXT, versao_config_v2 TEXT, ts_processado REAL NOT NULL
);
"""
# PATCH 2026-11-02 (3a rodada, Fix B): MESMO schema de `storage.py` (pr_api_uso) -- este script roda
# FORA do processo do bot ao vivo, entao precisa da MESMA tabela pronta aqui tambem (idempotente;
# se o bot ao vivo ja rodou nesta base, `CREATE TABLE IF NOT EXISTS` so confirma o schema existente).
DDL_API_USO = """
CREATE TABLE IF NOT EXISTS pr_api_uso (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, fonte TEXT NOT NULL, finalidade TEXT NOT NULL,
  pool TEXT, http_status INTEGER, rate_limited INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pr_api_uso_ts ON pr_api_uso (ts);
"""
# PATCH 2026-11-02 (3a rodada): True = resultado foi calculado com o replay TRUNCADO em
# `pr_pools.added_ts` (ver docstring do modulo) -- um resultado "ok" persistido com um valor
# DIFERENTE do estado atual (`added_ts is not None`) e invalidado/reprocessado em `executar()`.
_COLUNAS_NOVAS_RESULTADOS = {"admitido_apos_congelamento": "INTEGER NOT NULL DEFAULT 0"}


def _conectar_rw(db_path: Path) -> sqlite3.Connection:
    """Read-write (precisa gravar `pr_retro_candidatos`/`pr_retro_resultados`), mas NUNCA passa por
    `Storage` (que roda a migracao completa no `__init__`) -- so as tabelas desta propria ferramenta
    sao criadas/migradas aqui, nada mais."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(DDL_RETRO_CANDIDATOS)
    con.execute(DDL_RETRO_RESULTADOS)
    con.executescript(DDL_API_USO)
    existentes = {r[1] for r in con.execute("PRAGMA table_info(pr_retro_candidatos)").fetchall()}
    for nome, tipo in _COLUNAS_NOVAS.items():
        if nome not in existentes:
            con.execute(f"ALTER TABLE pr_retro_candidatos ADD COLUMN {nome} {tipo}")
    existentes_resultados = {r[1] for r in con.execute("PRAGMA table_info(pr_retro_resultados)").fetchall()}
    for nome, tipo in _COLUNAS_NOVAS_RESULTADOS.items():
        if nome not in existentes_resultados:
            con.execute(f"ALTER TABLE pr_retro_resultados ADD COLUMN {nome} {tipo}")
    con.commit()
    return con


def _backfill_supply_side(con: sqlite3.Connection) -> None:
    """Candidatos congelados ANTES do PATCH 2026-11-02 ficam com `supply`/`side` NULL (coluna nova via
    `ALTER TABLE`) -- preenche a partir de `pr_pools` (leitura, nunca grava ali), sem tocar
    `lista_hash`/`congelado_em`/a lista em si."""
    faltando = con.execute("SELECT pool FROM pr_retro_candidatos WHERE supply IS NULL").fetchall()
    for r in faltando:
        pool_row = con.execute("SELECT supply, info FROM pr_pools WHERE pool=?", (r["pool"],)).fetchone()
        if pool_row is None:
            continue
        side = _info(pool_row["info"]).get("side") or "base"
        con.execute("UPDATE pr_retro_candidatos SET supply=?, side=? WHERE pool=?", (pool_row["supply"], side, r["pool"]))
    if faltando:
        con.commit()


def _info(info_json: Optional[str]) -> dict[str, Any]:
    try:
        data = json.loads(info_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _candidatos_nunca_ativos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    """Ver docstring do modulo (secao "Congelamento") para a definicao exata."""
    rows = con.execute(
        """
        SELECT DISTINCT d.pool AS pool FROM pr_vaga_descartes d
        JOIN pr_pools p ON p.pool = d.pool
        WHERE p.status NOT IN ('ativo', 'dormente', 'encerrado')
          AND p.pool NOT IN (SELECT pool FROM pr_dormentes)
          AND p.pool NOT IN (SELECT pool FROM pr1_signals)
          AND p.pool NOT IN (SELECT pool FROM pr2_signals)
        """
    ).fetchall()
    pools = [r["pool"] for r in rows]
    if not pools:
        return []
    placeholders = ",".join("?" for _ in pools)
    return con.execute(
        f"SELECT pool, mint, symbol, launchpad, l_bc, grad_ts, supply, info, mc_found FROM pr_pools WHERE pool IN ({placeholders})",
        pools,
    ).fetchall()


def congelar_candidatos(con: sqlite3.Connection, now: float) -> list[sqlite3.Row]:
    """Idempotente: a 1a execucao congela (grava `lista_hash`+`congelado_em`); qualquer execucao
    seguinte LE a lista ja congelada de volta, nunca recalcula (amostra fixa -- ver docstring do
    modulo)."""
    frozen = con.execute("SELECT * FROM pr_retro_candidatos ORDER BY pool").fetchall()
    if frozen:
        _backfill_supply_side(con)
        return con.execute("SELECT * FROM pr_retro_candidatos ORDER BY pool").fetchall()
    candidatos = _candidatos_nunca_ativos(con)
    lista_hash = hashlib.sha256("\n".join(sorted(r["pool"] for r in candidatos)).encode("utf-8")).hexdigest()
    for r in candidatos:
        info = _info(r["info"])
        con.execute(
            "INSERT OR IGNORE INTO pr_retro_candidatos "
            "(pool, mint, symbol, launchpad, l_bc, grad_ts, criado_ts, mc_found, supply, side, lista_hash, congelado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["pool"], r["mint"], r["symbol"], r["launchpad"], r["l_bc"], r["grad_ts"],
             info.get("criado_ts"), r["mc_found"], r["supply"], info.get("side") or "base", lista_hash, now),
        )
    con.commit()
    return con.execute("SELECT * FROM pr_retro_candidatos ORDER BY pool").fetchall()


# -- orcamento horario proprio desta execucao (nunca compete com o bot ao vivo) --------------------------
@dataclass
class OrcamentoHorario:
    path: Path
    limite: int
    clock: Any = time.time

    def _bucket(self, now: float) -> str:
        return time.strftime("%Y-%m-%dT%H", time.gmtime(now))

    def _carregar(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {"hora": None, "chamadas": 0}

    def pode_chamar(self) -> bool:
        d = self._carregar()
        bucket = self._bucket(self.clock())
        chamadas = int(d.get("chamadas") or 0) if d.get("hora") == bucket else 0
        return chamadas < self.limite

    def registrar(self) -> None:
        bucket = self._bucket(self.clock())
        d = self._carregar()
        if d.get("hora") != bucket:
            d = {"hora": bucket, "chamadas": 0}
        d["chamadas"] = int(d.get("chamadas") or 0) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d), encoding="utf-8")


class OrcamentoHttpClient(HttpClient):
    """MESMO `HttpClient` do resto do repo, so com um orcamento de chamadas/hora PROPRIO desta
    execucao na frente -- esgotado, levanta `ApiError("budget", ...)` ANTES de qualquer chamada de
    rede (kind="budget" nunca e retentado por `OhlcvStore._page`, propaga na hora pro chamador parar
    e imprimir o relatorio parcial; a proxima execucao retoma do checkpoint em disco do
    `OhlcvStore`)."""

    def __init__(self, *args: Any, orcamento: OrcamentoHorario, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.orcamento = orcamento

    def get_json(self, path: str, params: Any = None, max_wait_s: float = 5.0) -> Any:
        if not self.orcamento.pode_chamar():
            raise ApiError("budget", f"orcamento de {self.orcamento.limite} chamadas GeckoTerminal/hora esgotado nesta execucao")
        self.orcamento.registrar()
        return super().get_json(path, params, max_wait_s=max_wait_s)


def _registrar_api_uso_retro(con: sqlite3.Connection, now: float, fonte: str, pool: str,
                             http_status: Optional[int] = 200, rate_limited: bool = False) -> None:
    """PATCH 2026-11-02 (3a rodada, Fix B): `pr_api_uso` so cobria `poll_pool` (ver docstring do
    modulo) -- finalidade fixa `coorte_retro`, a UNICA gravada por um processo FORA do bot ao vivo.
    MESMA convencao de `live.py: _refresh_core` (so conta chamada de rede DE VERDADE, nunca uma
    janela ja coberta pelo cache local)."""
    con.execute(
        "INSERT INTO pr_api_uso (ts, fonte, finalidade, pool, http_status, rate_limited) VALUES (?,?,?,?,?,?)",
        (now, fonte, "coorte_retro", pool, http_status, int(rate_limited)),
    )
    con.commit()


def _simular_entrada(bars: list[Bar], ev: Any, params: ParamsV1, costs: CostModel, dex: str, l_bc: Optional[float]) -> dict[str, Any]:
    res = simulate_v1(bars, ev, params, costs, dex, l_bc, lambda _t: None)
    risco_pct = ev.data.get("risco_pct")
    r_mult = res.r_mult
    r_excluido_motivo = None
    if risco_pct is None or risco_pct < RISCO_IRREALISTA_MIN_PCT:
        r_excluido_motivo = "risco_irrealista"
        r_mult = None
    return {
        "zona": ev.data.get("zona"), "decision_ts": ev.decision_ts, "status": res.status,
        "net_ret": res.net_ret, "risco_pct": risco_pct, "r_mult": r_mult,
        "r_excluido_motivo": r_excluido_motivo, "retroativo": True,
        # PEDIDO 2026-11-03 (continuacao -- pendente 3, avaliar_v3_retro): campo aditivo, nunca muda
        # nenhum valor ja existente (so leitura das legs que `simulate_v1` ja simulou acima) -- "tocou
        # o topo anterior" = TP1 disparou (`bar.high>=TOPO` com exaustao, ver simulate_v1.py).
        "tocou_topo": any(leg.reason == "tp1" for leg in res.legs),
    }


@dataclass
class ResultadoCandidato:
    pool: str
    symbol: str
    historico_suficiente: bool
    categoria: str = "ok"   # "ok" | "pendente" | "sem_historico" | "sem_dados_pool"
    motivo_sem_historico: Optional[str] = None
    idade_desconhecida: bool = False
    pico_mc: Optional[float] = None
    n_candles: Optional[int] = None
    chegou_runner: bool = False
    sinais_v1: list[dict[str, Any]] = None  # type: ignore[assignment]
    sinais_v2: list[dict[str, Any]] = None  # type: ignore[assignment]
    # PATCH 2026-11-02 (3a rodada): True quando `pr_pools.added_ts` existia NO MOMENTO deste
    # processamento -- replay veio truncado de `pr_bars` (ver docstring do modulo), nunca da rede.
    admitido_apos_congelamento: bool = False

    def __post_init__(self) -> None:
        if self.sinais_v1 is None:
            self.sinais_v1 = []
        if self.sinais_v2 is None:
            self.sinais_v2 = []


def _persistir_resultado(con: sqlite3.Connection, resultado: ResultadoCandidato, versao_v1: str, versao_v2: str, now: float) -> None:
    """Grava/substitui o resultado deste pool -- 1 linha por pool, sempre o MAIS RECENTE. Nunca toca
    `pr1_signals`/`pr2_signals`/`pr_pools` (sinais retroativos nunca entram ali -- ver docstring)."""
    con.execute(
        "INSERT INTO pr_retro_resultados "
        "(pool, categoria, motivo_sem_historico, n_candles, pico_mc, chegou_runner, idade_desconhecida, "
        " sinais_v1_json, sinais_v2_json, versao_config_v1, versao_config_v2, ts_processado, "
        " admitido_apos_congelamento) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(pool) DO UPDATE SET categoria=excluded.categoria, motivo_sem_historico=excluded.motivo_sem_historico, "
        "n_candles=excluded.n_candles, pico_mc=excluded.pico_mc, chegou_runner=excluded.chegou_runner, "
        "idade_desconhecida=excluded.idade_desconhecida, sinais_v1_json=excluded.sinais_v1_json, "
        "sinais_v2_json=excluded.sinais_v2_json, versao_config_v1=excluded.versao_config_v1, "
        "versao_config_v2=excluded.versao_config_v2, ts_processado=excluded.ts_processado, "
        "admitido_apos_congelamento=excluded.admitido_apos_congelamento",
        (resultado.pool, resultado.categoria, resultado.motivo_sem_historico, resultado.n_candles, resultado.pico_mc,
         int(resultado.chegou_runner), int(resultado.idade_desconhecida),
         json.dumps(resultado.sinais_v1), json.dumps(resultado.sinais_v2), versao_v1, versao_v2, now,
         int(resultado.admitido_apos_congelamento)),
    )
    con.commit()


def _ler_resultados(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["pool"]: r for r in con.execute("SELECT * FROM pr_retro_resultados").fetchall()}


def _resultado_de_linha(symbol: str, linha: sqlite3.Row) -> ResultadoCandidato:
    """Reconstroi um `ResultadoCandidato` a partir do que foi persistido -- usado pelo relatorio pra
    nunca recalcular (zero chamada de rede) um candidato ja resolvido."""
    return ResultadoCandidato(
        linha["pool"], symbol, historico_suficiente=linha["categoria"] == "ok", categoria=linha["categoria"],
        motivo_sem_historico=linha["motivo_sem_historico"], idade_desconhecida=bool(linha["idade_desconhecida"]),
        pico_mc=linha["pico_mc"], n_candles=linha["n_candles"], chegou_runner=bool(linha["chegou_runner"]),
        sinais_v1=json.loads(linha["sinais_v1_json"] or "[]"), sinais_v2=json.loads(linha["sinais_v2_json"] or "[]"),
        admitido_apos_congelamento=bool(linha["admitido_apos_congelamento"]),
    )


def _bars_truncados_de_pr_bars(con: sqlite3.Connection, pool: str, tf: str, step: int, added_ts: float) -> list[Bar]:
    """SO LEITURA de `pr_bars` (tabela do bot ao vivo -- candles JA em MC/USD, mesma conversao de
    `live.py: _refresh_core`, ja passados por `fill_gaps` antes de serem gravados ali -- nunca refeito
    aqui). Corta em `bar.ts + step < added_ts` (MESMA comparacao que `live.py` usa para isolar
    `decision_ts < added_ts` -- ver docstring do modulo, PATCH 2026-11-02 3a rodada): nenhum candle
    igual ou posterior a admissao chega ao detector, pela construcao da lista, nunca por um filtro a
    posteriori em cima do evento."""
    rows = con.execute(
        "SELECT ts, o, h, l, c, v, filled FROM pr_bars WHERE pool=? AND tf=? ORDER BY ts", (pool, tf)
    ).fetchall()
    return [Bar(r["ts"], r["o"], r["h"], r["l"], r["c"], r["v"], bool(r["filled"]))
            for r in rows if r["ts"] + step < added_ts]


def processar_candidato(
    con: sqlite3.Connection, row: sqlite3.Row, ohlcv: OhlcvStore, dexpaprika: Any, params_v1: ParamsV1,
    params_v2: ParamsV1, costs: CostModel, now: float,
) -> ResultadoCandidato:
    """PATCH 2026-11-02: `l_bc` NAO e mais um pre-requisito (sempre None pra quem nunca foi 'ativo' --
    ver docstring do modulo) -- e CALCULADO aqui a partir do 1o candle em MC, exatamente a formula de
    `live.py: _refresh_core` (`l_bc = seq[0].open`, so que a cotacao USD vem do proprio GT --
    `currency="usd"` -- em vez da serie cacheada do bot ao vivo). `criado_ts` ausente so marca
    `idade_desconhecida`, nunca bloqueia (o `DetectorV1` ja trata `created_ts=None` sem crash).

    PATCH 2026-11-02 (3a rodada): se `pr_pools.added_ts` existe (candidato ganhou vaga de verdade
    DEPOIS do congelamento), o replay usa `pr_bars` truncado em vez da rede -- ver
    `_bars_truncados_de_pr_bars` e a docstring do modulo. Zero chamada de rede nesse caso."""
    pool, symbol = row["pool"], row["symbol"] or row["pool"][:8]
    grad_ts, supply, criado_ts = row["grad_ts"], row["supply"], row["criado_ts"]
    if not pool or grad_ts is None or supply is None:
        motivo = "sem_endereco_pool" if not pool else "linhagem incompleta (grad_ts/supply ausentes em pr_pools)"
        return ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="sem_dados_pool", motivo_sem_historico=motivo)
    tf = params_v1.timeframes[0]
    step = tf_seconds(tf)
    side = row["side"] or "base"
    pool_row = con.execute("SELECT added_ts, l_bc, launchpad FROM pr_pools WHERE pool=?", (pool,)).fetchone()
    added_ts = pool_row["added_ts"] if pool_row is not None else None
    admitido = added_ts is not None
    if admitido:
        bars = _bars_truncados_de_pr_bars(con, pool, tf, step, added_ts)
        l_bc = pool_row["l_bc"]
        launchpad = pool_row["launchpad"] or row["launchpad"]
        if not bars or l_bc is None:
            return ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="sem_historico",
                                      motivo_sem_historico="sem_historico_pre_admissao",
                                      admitido_apos_congelamento=True)
    else:
        http = getattr(ohlcv, "http", None)
        chamadas_antes = getattr(http, "calls", 0) if http is not None else 0
        limitadas_antes = getattr(http, "rate_limited", 0) if http is not None else 0
        try:
            preco_usd = ohlcv.history(pool, tf, int(grad_ts), currency="usd", side=side)
        except ApiError as exc:
            if http is not None and getattr(http, "calls", 0) > chamadas_antes:
                _registrar_api_uso_retro(con, now, "gt", pool, http_status=exc.status,
                                         rate_limited=getattr(http, "rate_limited", 0) > limitadas_antes)
            if exc.kind == "budget":
                raise
            preco_usd = []
            if dexpaprika is not None and dexpaprika.disponivel():
                chamadas_dp_antes = getattr(dexpaprika, "chamadas_fallback", 0)
                try:
                    # candles_fallback() ja devolve preco (nao MC) -- tratado aqui como USD por token,
                    # mesma suposicao do caminho GT (documentada no modulo, DexPaprika e so melhor-esforco).
                    preco_usd = dexpaprika.candles_fallback("solana", pool, tf, grad_ts, now)
                except Exception:  # noqa: BLE001 - fallback e melhor-esforco, nunca derruba a execucao
                    log.warning("retro: fallback DexPaprika falhou em %s", symbol, exc_info=True)
                    preco_usd = []
                if getattr(dexpaprika, "chamadas_fallback", 0) > chamadas_dp_antes:
                    _registrar_api_uso_retro(con, now, "dexpaprika", pool)
        else:
            if http is not None and getattr(http, "calls", 0) > chamadas_antes:
                _registrar_api_uso_retro(con, now, "gt", pool, http_status=200,
                                         rate_limited=getattr(http, "rate_limited", 0) > limitadas_antes)
        if not preco_usd:
            return ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="sem_historico",
                                      motivo_sem_historico="sem_historico_na_fonte")
        bars = fill_gaps([Bar(b.ts, b.open * supply, b.high * supply, b.low * supply, b.close * supply, b.volume, b.filled)
                          for b in preco_usd], step)
        l_bc = bars[0].open
        launchpad = row["launchpad"]
    qual1, qual2 = avaliar_qualidade(bars, params_v1), avaliar_qualidade(bars, params_v2)
    if not qual1.valido and not qual2.valido:
        return ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="sem_historico",
                                  motivo_sem_historico=f"dado_invalido: {qual1.motivo}",
                                  admitido_apos_congelamento=admitido)
    dex = DEX_OF_LAUNCHPAD.get(launchpad, "desconhecido")
    res = ResultadoCandidato(pool, symbol, historico_suficiente=True, pico_mc=max(b.high for b in bars),
                             n_candles=len(bars), idade_desconhecida=criado_ts is None,
                             admitido_apos_congelamento=admitido)
    det_v1 = DetectorV1(params_v1, tf, l_bc, grad_ts, criado_ts) if qual1.valido else None
    det_v2 = DetectorV1(params_v2, tf, l_bc, grad_ts, criado_ts) if qual2.valido else None
    for bar in bars:
        for det, params, sinais in ((det_v1, params_v1, res.sinais_v1), (det_v2, params_v2, res.sinais_v2)):
            if det is None:
                continue
            for ev in det.update(bar):
                if ev.kind == "RUNNER":
                    res.chegou_runner = True
                elif ev.kind == "ENTRADA":
                    sinais.append(_simular_entrada(bars, ev, params, costs, dex, l_bc))
    return res


def _populacao_admitida(con: sqlite3.Connection) -> dict[str, Any]:
    """MESMA leitura que o heartbeat/`saude.py` ja fazem (ver docstring do modulo) -- so dado JA
    persistido ao vivo, zero replay/chamada nova. "chegou a runner" usa `pr_funil_marcos` (marco
    persistido pela PARTE 1 em `_on_event_v1`/`_on_event_v2`, nunca recalculado aqui)."""
    rows = con.execute("SELECT pool, mc_found, info FROM pr_pools WHERE status IN ('ativo', 'dormente', 'encerrado')").fetchall()
    runners = {r["pool"] for r in con.execute("SELECT DISTINCT pool FROM pr_funil_marcos WHERE etapa='runner'").fetchall()}
    now = time.time()
    mc_founds = [r["mc_found"] for r in rows if r["mc_found"] is not None]
    idades = []
    for r in rows:
        criado_ts = _info(r["info"]).get("criado_ts")
        if criado_ts is not None:
            idades.append((now - float(criado_ts)) / 86400.0)
    n = len(rows)
    return {
        "n": n, "mc_found_medio": statistics.fmean(mc_founds) if mc_founds else None,
        "idade_media_d": statistics.fmean(idades) if idades else None,
        "pct_runner": (100.0 * sum(1 for r in rows if r["pool"] in runners) / n) if n else None,
    }


def _r_stats(sinais: list[dict[str, Any]]) -> dict[str, Any]:
    fechados = [s for s in sinais if s["status"] == "fechado"]
    com_r = [s["r_mult"] for s in fechados if s["r_mult"] is not None]
    return {
        "n_sinais": len(sinais), "n_fechados": len(fechados), "n_r_valido": len(com_r),
        "r_medio": statistics.fmean(com_r) if com_r else None,
        "r_mediano": statistics.median(com_r) if com_r else None,
        "taxa_acerto_pct": (100.0 * sum(1 for r in com_r if r > 0) / len(com_r)) if com_r else None,
    }


def formatar(resultados: list[ResultadoCandidato], admitida: dict[str, Any], lista_hash: str, congelado_em: float,
            buscados_nesta_execucao: int = 0, chamadas_usadas: int = 0, max_chamadas_hora: int = DEFAULT_MAX_CHAMADAS_HORA) -> str:
    ok = [r for r in resultados if r.categoria == "ok"]
    pendentes = [r for r in resultados if r.categoria != "ok"]   # inclui sem_historico/sem_dados_pool/pendente -- ainda "em aberto"
    sem_historico_cat = [r for r in resultados if r.categoria == "sem_historico"]
    sem_dados_pool_cat = [r for r in resultados if r.categoria == "sem_dados_pool"]
    if buscados_nesta_execucao > 0 and chamadas_usadas > 0 and pendentes:
        chamadas_por_candidato = chamadas_usadas / buscados_nesta_execucao
        horas_estimadas = f"{len(pendentes) * chamadas_por_candidato / max_chamadas_hora:.1f}h"
    else:
        horas_estimadas = "s/d"
    out = [
        "# Coorte retrospectiva -- candidatos sem vaga (tag retro_sem_vaga)", "",
        "AVISO: replicacao EXPLORATORIA. Nunca soma ao N=30 do pre-registro nem a nenhum H1/H2 "
        "confirmatorio -- so mede o que teria acontecido aos candidatos que nunca ganharam vaga, com "
        "o MESMO detector/custo/regra de risco congelados do bot ao vivo.",
        "",
        f"congelamento: {len(resultados)} candidatos | lista_hash={lista_hash} | "
        f"congelado em {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(congelado_em))}",
        f"ok={len(ok)} | pendente={len(pendentes)} (sem_historico={len(sem_historico_cat)}, "
        f"sem_dados_pool={len(sem_dados_pool_cat)}) | nesta execucao: buscados={buscados_nesta_execucao} "
        f"({chamadas_usadas} chamadas GT) | estimativa p/ terminar: {horas_estimadas}",
        "",
    ]
    com_historico = [r for r in resultados if r.historico_suficiente]
    sem_historico = [r for r in resultados if not r.historico_suficiente]
    chegaram_runner = sum(1 for r in com_historico if r.chegou_runner)
    todos_v1 = [s for r in com_historico for s in r.sinais_v1]
    todos_v2 = [s for r in com_historico for s in r.sinais_v2]
    stats_v1, stats_v2 = _r_stats(todos_v1), _r_stats(todos_v2)
    out += [
        "## Agregado", "",
        f"candidatos com historico suficiente: {len(com_historico)}/{len(resultados)} "
        f"({len(sem_historico)} sem historico -- ver coluna motivo na tabela)",
        f"chegaram a RUNNER: {chegaram_runner} ({100.0 * chegaram_runner / len(com_historico):.1f}%)"
        if com_historico else "chegaram a RUNNER: s/d (nenhum candidato com historico)",
        f"sinais V1 (ENTRADA): {stats_v1['n_sinais']} | fechados: {stats_v1['n_fechados']} | "
        f"R medio: {stats_v1['r_medio']:.2f} | R mediano: {stats_v1['r_mediano']:.2f} | "
        f"taxa de acerto: {stats_v1['taxa_acerto_pct']:.1f}%" if stats_v1["n_r_valido"] else
        f"sinais V1 (ENTRADA): {stats_v1['n_sinais']} | fechados: {stats_v1['n_fechados']} | R: s/d (sem R valido, risco<3%% exclui)",
        f"sinais V2 (ENTRADA): {stats_v2['n_sinais']} | fechados: {stats_v2['n_fechados']} | "
        f"R medio: {stats_v2['r_medio']:.2f} | R mediano: {stats_v2['r_mediano']:.2f} | "
        f"taxa de acerto: {stats_v2['taxa_acerto_pct']:.1f}%" if stats_v2["n_r_valido"] else
        f"sinais V2 (ENTRADA): {stats_v2['n_sinais']} | fechados: {stats_v2['n_fechados']} | R: s/d (sem R valido, risco<3%% exclui)",
        "",
        "## Barrada (este congelamento) vs admitida (pools que ja tiveram vaga)", "",
        f"barrada: n={len(resultados)} | MC no achado: s/d (candidatos nunca foram 'verificado' com MC "
        f"medido na mesma base -- ver pico MC do historico por candidato, tabela abaixo) | "
        f"% chegou a runner: {100.0 * chegaram_runner / len(com_historico):.1f}%"
        if com_historico else f"barrada: n={len(resultados)} | % chegou a runner: s/d",
        f"admitida: n={admitida['n']} | MC no achado medio: "
        f"{admitida['mc_found_medio']:,.0f}" if admitida["mc_found_medio"] is not None else
        f"admitida: n={admitida['n']} | MC no achado medio: s/d",
    ]
    if admitida["idade_media_d"] is not None:
        out.append(f"admitida: idade media (d): {admitida['idade_media_d']:.1f} | "
                   f"% chegou a runner: {admitida['pct_runner']:.1f}%" if admitida["pct_runner"] is not None
                   else f"admitida: idade media (d): {admitida['idade_media_d']:.1f} | % chegou a runner: s/d")
    out += ["", "## Por candidato", "",
           "| token | categoria | pico MC | runner? | idade s/d? | sinais V1 | sinais V2 | pos-congelamento? |",
           "|---|---|---|---|---|---|---|---|"]
    for r in sorted(resultados, key=lambda x: x.symbol):
        # PATCH 2026-11-02 (3a rodada): tag `admitido_apos_congelamento` -- ver docstring do modulo.
        pos_congelamento = "sim (replay truncado em added_ts)" if r.admitido_apos_congelamento else "nao"
        if not r.historico_suficiente:
            out.append(f"| {r.symbol} | {r.categoria} ({r.motivo_sem_historico}) | s/d | s/d | s/d | s/d | s/d | {pos_congelamento} |")
            continue
        pico = f"{r.pico_mc:,.0f}" if r.pico_mc is not None else "s/d"
        runner = "sim" if r.chegou_runner else "nao"
        idade_sd = "sim" if r.idade_desconhecida else "nao"
        v1 = str(len(r.sinais_v1)) if r.sinais_v1 else "0"
        v2 = str(len(r.sinais_v2)) if r.sinais_v2 else "0"
        out.append(f"| {r.symbol} | ok | {pico} | {runner} | {idade_sd} | {v1} | {v2} | {pos_congelamento} |")
    return "\n".join(out)


def executar(db_path: Path, cache_dir: Path, max_chamadas_hora: int, reprocessar: bool = False,
            ohlcv: Optional[Any] = None, dexpaprika: Optional[Any] = None) -> str:
    """`ohlcv`/`dexpaprika`: injetaveis so pra teste (offline, sem rede real) -- `main()`/uso normal
    nunca os passa, e `executar()` constroi os de verdade (GeckoTerminal + `OrcamentoHttpClient`)."""
    con = _conectar_rw(db_path)
    try:
        now = time.time()
        candidatos = congelar_candidatos(con, now)
        congelado_em = candidatos[0]["congelado_em"] if candidatos else now
        lista_hash = candidatos[0]["lista_hash"] if candidatos else hashlib.sha256(b"").hexdigest()
        params_v1, params_v2 = load_params_v1(), load_params_v2()
        persistidos = _ler_resultados(con)
        orcamento = OrcamentoHorario(cache_dir / "retro_orcamento.json", max_chamadas_hora)
        if ohlcv is None:
            http = OrcamentoHttpClient(GT_BASE, RateLimiter(26, 2, pause_s=30, pause_max_s=240, jitter_s=1.5),
                                       30, name="GeckoTerminal-retro", orcamento=orcamento)
            ohlcv = OhlcvStore(http, cache_dir / "ohlcv")
        if dexpaprika is None:
            dexpaprika = make_dexpaprika_provider()
        costs = CostModel()
        chamadas_antes = int((orcamento._carregar() or {}).get("chamadas") or 0)   # noqa: SLF001
        resultados: list[ResultadoCandidato] = []
        buscados_nesta_execucao = 0
        orcamento_esgotado = False
        for row in candidatos:
            pool, symbol = row["pool"], row["symbol"] or row["pool"][:8]
            linha = persistidos.get(pool)
            pool_atual = con.execute("SELECT added_ts FROM pr_pools WHERE pool=?", (pool,)).fetchone()
            admitido_agora = pool_atual is not None and pool_atual["added_ts"] is not None
            # "ok" persistido com o MESMO hash de ParamsV1/ParamsV2 congelado agora: NUNCA refeito
            # (zero chamada de rede) a menos que --reprocessar seja passado explicitamente. PATCH
            # 2026-11-02 (3a rodada): tambem forca 1 reprocessamento (sem rede, so troca a fonte dos
            # candles -- ver `processar_candidato`) se `added_ts` passou a existir DEPOIS do "ok"
            # persistido (`admitido_apos_congelamento` cacheado != estado atual).
            ja_resolvido = (linha is not None and linha["categoria"] == "ok" and not reprocessar
                           and linha["versao_config_v1"] == params_v1.version
                           and linha["versao_config_v2"] == params_v2.version
                           and bool(linha["admitido_apos_congelamento"]) == admitido_agora)
            if ja_resolvido:
                resultados.append(_resultado_de_linha(symbol, linha))
                continue
            if admitido_agora:
                # truncado de `pr_bars` -- zero chamada de rede, nunca disputa o orcamento do GT.
                resultado = processar_candidato(con, row, ohlcv, dexpaprika, params_v1, params_v2, costs, now)
                _persistir_resultado(con, resultado, params_v1.version, params_v2.version, now)
                resultados.append(resultado)
                continue
            if orcamento_esgotado:
                # mantem o ultimo resultado persistido (se houver, mesmo nao-"ok") -- nunca apaga
                # progresso de uma execucao anterior so porque esta parou mais cedo.
                resultados.append(_resultado_de_linha(symbol, linha) if linha is not None else
                                  ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="pendente",
                                                     motivo_sem_historico="pendente (nunca tentado ou orcamento esgotado)"))
                continue
            try:
                resultado = processar_candidato(con, row, ohlcv, dexpaprika, params_v1, params_v2, costs, now)
                _persistir_resultado(con, resultado, params_v1.version, params_v2.version, now)
                resultados.append(resultado)
                buscados_nesta_execucao += 1
            except ApiError as exc:
                if exc.kind != "budget":
                    raise
                log.info("retro: %s -- parando esta execucao, retomando na proxima", exc)
                orcamento_esgotado = True
                resultados.append(_resultado_de_linha(symbol, linha) if linha is not None else
                                  ResultadoCandidato(pool, symbol, historico_suficiente=False, categoria="pendente",
                                                     motivo_sem_historico="pendente (nunca tentado ou orcamento esgotado)"))
        chamadas_depois = int((orcamento._carregar() or {}).get("chamadas") or 0)   # noqa: SLF001
        chamadas_usadas = max(0, chamadas_depois - chamadas_antes)
        admitida = _populacao_admitida(con)
        return formatar(resultados, admitida, lista_hash, congelado_em, buscados_nesta_execucao, chamadas_usadas, max_chamadas_hora)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Coorte retrospectiva dos candidatos sem vaga (PAPER / leitura do detector, so tag retro_sem_vaga).")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path, default=None, help="padrao: dados/pos_runner_retro ao lado do --db")
    parser.add_argument("--max-chamadas-hora", type=int, default=DEFAULT_MAX_CHAMADAS_HORA)
    parser.add_argument("--reprocessar", action="store_true",
                        help="forca reprocessar candidatos JA 'ok' persistidos (por padrao, nunca sao refeitos)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cache_dir = args.cache_dir or (args.db.parent / "pos_runner_retro")
    print(executar(args.db, cache_dir, args.max_chamadas_hora, reprocessar=args.reprocessar))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
