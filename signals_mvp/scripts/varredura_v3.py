"""PEDIDO 2026-11-05 (autorizado, Parte B): descobre se o detector V3 (regras CONGELADAS,
`ParamsV3=56762db29cd6`) acha BOAS OPORTUNIDADES, sem limite de capital/vagas/posicoes/max_pools --
cada sinal e um evento INDEPENDENTE, agrupado por token distinto na agregacao. SOMENTE LEITURA no
banco do bot (zero chamada de rede, zero escrita em qualquer tabela). EXPLORATORIO: nunca evidencia
confirmatoria, nunca entra no N=30 nem na H1 (`docs/research-hypothesis-registry-v1-2026-10-04.md`
continua sendo a unica autoridade pra isso). Definicao de "boa oportunidade" pre-registrada em
`docs/pos-runner-v3/PREREGISTRO_VARREDURA_V3_2026-11-05.md`, ANTES de qualquer resultado real.

Detector/simulate/ParamsV3/H1/criterio de sinal NUNCA alterados por este script.

ESCOPO DESTA RODADA (simplificacoes/cortes documentados, nunca escondidos):
- B1(a) "todos os pools... com historico completo": reusa `avaliar_v3_retro.
  parte_a_pools_admitidos` (status IN ativo/dormente/encerrado -- MESMO universo que o pedido
  descreve como "ativos, aposentados [=encerrado], dormentes"), zero duplicacao de replay.
- B1(b) retro lote1: reusa o MESMO padrao de replay de `simular_v3_carteira.carregar_retro_lote1`
  (pr_retro_candidatos + candles truncados em `pr_pools.added_ts`). O "lote 2" (rodada 9, item 5) e
  CONGELADO separadamente por `scripts.avaliar_candidatos_retro.congelar_candidatos_lote2` (so a
  lista de candidatos + hash/timestamp, SEM replay/rede) -- este script continua lendo so o lote1
  ja admitido na replay (consumir lote2 exige decisao de admissao, fora do escopo desta rodada).
- B1(c) "candidatos nunca admitidos com historico obtivel": pools com `status IN
  ('rejeitado','verificado')` que JA tem `pr_bars` cacheado (zero chamada nova) -- rotulado
  `universo_nunca_admitido`.
- B1(d) "ampliar o historico via coleta lenta": EXPLICITAMENTE opcional no pedido e exige chamadas
  de rede ao vivo -- NAO implementado aqui (um script somente-leitura nunca deveria iniciar
  coleta); proposta de fontes/custo/tempo/vies no pre-registro B6 (rodada 9, item 4), ainda sem
  execucao.
- B2 "comparacao contra entradas aleatorias no mesmo pool/fase" (rodada 9, item 3): IMPLEMENTADO --
  `calcular_equilibrio_empirico`, K=20 entradas aleatorias/sinal, MESMA elegibilidade/fase dos 10
  controles pareados (`candidatos_elegiveis`) e MESMA distancia de stop (`evidencia.evento_controle`
  via risco_pct do sinal), semente PROPRIA (nunca colide com o sorteio dos 10 controles). Substitui
  o equilibrio TEORICO 1/(1+N) como referencia adicional (nunca remove o teorico do relatorio).
- B2/item1 (rodada 9): o pareamento usa R@72h -- resolvido PELA REGRA se a saida real aconteceu
  antes do corte de 72h, SENAO valorizado a MERCADO no proprio corte (`horizonte_fixo.
  calcular_r_horizonte`, MESMA definicao usada pelo resto do projeto/H1) -- NUNCA R de saida por
  regra sem corte. Censura: 'pendente' (horizonte ainda nao decorrido) e 'sem_dado' (entrada
  cancelada, fora do stop/TOPO) descartados simetricamente dos 2 lados (sinal E controle), nunca um
  corte que favoreca um lado. Pareamento por TOQUE novo: P(+2R antes de -1R) do sinal (1/0) menos a
  media dos MESMOS 10 controles (nunca um 2o sorteio independente do pareamento em R).
- Item2 (rodada 9, BUG corrigido): `carregar_universo_admitido` fixava `created_ts=None` sempre,
  zerando o pareamento com controles SO desta origem (`candidatos_elegiveis` nunca elege nada sem
  `created_ts`) -- corrigido buscando `created_ts` real via `pr_pools.info` (MESMO padrao das outras
  2 origens).
- B3 estratos: reusa DIRETAMENTE `analise.condicional._grupos_v3_estratos`/`rodar_exploratorias_v3`
  (os MESMOS 8 estratos pre-registrados pra V3, Holm sobre a familia completa) -- zero logica
  estatistica nova, so monta `SinalResolvido` com a covariavel certa
  (`pos_runner_v3.calcular_covariaveis_v3`, ja existente) e `dif_pareada` = R@72h do sinal menos a
  media dos controles no MESMO horizonte.
- B5 "nice/tmux": este script e passivo (nunca inicia um processo proprio) -- o comando de VM abaixo
  ja empacota nice+tmux; o script so faz o check de RAM antes de comecar (`--min-ram-mb`, aborta se
  insuficiente) e imprime progresso. O comparador aleatorio (K=20) roda, por sinal, o DOBRO de
  varreduras causais dos 10 controles -- custo adicional esperado, nunca um numero fixo chutado (ver
  resposta final/PR pelo tempo medido).

Uso (na VM, a partir da raiz do repo -- RAM/CPU fracos, roda em background):
    nice -n 19 tmux new-session -d -s varredura_v3 \
        'python -m signals_mvp.scripts.varredura_v3 --db signals_mvp/dados/estado.sqlite \
         --csv varredura_v3.csv 2>&1 | tee varredura_v3.log'
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..analise.condicional import (
    CONFIANCA_H1,
    N_BOOTSTRAP_PADRAO,
    RISCO_IRREALISTA_MIN_PCT,
    SEED_PADRAO,
    GrupoExploratorio,
    SinalResolvido,
    rodar_exploratorias_v3,
)
from ..pos_runner.candles import Bar, candle_corrompido_provavel, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import DetectorV1, EventV1
from ..pos_runner.evidencia import (
    DROP_MIN_CONTROLE,
    MC_MIN_CONTROLE,
    N_CONTROLES_MINIMO,
    N_CONTROLES_PADRAO,
    candidatos_elegiveis,
    evento_controle,
    sortear_controles,
)
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte
from ..pos_runner.params_v3 import load_params_v3
from ..pos_runner.pos_runner_v3 import calcular_covariaveis_v3
from .avaliar_v3_retro import DEX_OF_LAUNCHPAD, _conectar_ro, _created_ts, parte_a_pools_admitidos
from .exit_lab import _bars_truncados
from .sensibilidade_parametros import _bars_do_pool

AVISO = ("EXPLORATORIO -- DENTRO DA AMOSTRA (nunca fora-da-amostra no sentido forte); VIES DE "
        "SOBREVIVENCIA (so pools/candidatos que o GT ainda alcanca); resultado em paper e TETO de "
        "execucao; so sinais FUTUROS da V3 congelada, ao vivo, valem como evidencia -- isso aqui "
        "nunca entra no N=30 nem na H1.")

RAM_MINIMA_MB_PADRAO = 150.0
RISCO_MINIMO_PCT = RISCO_IRREALISTA_MIN_PCT   # mesma regra de realismo do resto do projeto
ALVOS_R = (1.0, 2.0, 3.0)
JANELA_VOLUME_MEDIO = 24


# ---------------------------------------------------------------------------
# B5: seguranca operacional -- RAM antes de comecar, nunca concorre com o bot
# ---------------------------------------------------------------------------


def ram_disponivel_mb() -> Optional[float]:
    """Le `/proc/meminfo` (Linux, zero dependencia nova) -- `None` se indisponivel (ex.: nao-Linux
    em testes), nunca inventa um numero."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for linha in f:
                if linha.startswith("MemAvailable:"):
                    return float(linha.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


class RamInsuficienteError(RuntimeError):
    pass


def checar_ram_ou_abortar(minimo_mb: float = RAM_MINIMA_MB_PADRAO) -> None:
    disponivel = ram_disponivel_mb()
    if disponivel is not None and disponivel < minimo_mb:
        raise RamInsuficienteError(
            f"RAM disponivel ({disponivel:.0f}MB) abaixo do minimo ({minimo_mb:.0f}MB) -- abortando "
            "pra nunca competir com o bot ao vivo.")


# ---------------------------------------------------------------------------
# B1: universo MAXIMO, 3 fontes rotuladas (nunca somadas)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SinalVarredura:
    token: str
    mint: str
    pool: str
    tf: str
    origem: str   # 'universo_admitido' | 'universo_nunca_admitido' | 'retro_lote1'
    bars: list[Bar]
    ev: EventV1
    dex: str
    l_bc: Optional[float]
    created_ts: Optional[float]
    supply: Optional[float]
    t_entrada: float
    entry_price: float
    entrada_corrigida: bool
    stop: float
    topo: float
    s_val: float
    risk_frac: float
    volume_gatilho: Optional[float]
    volume_entrada: Optional[float]
    volume_medio_24h: Optional[float]
    n_pavios: Optional[int]


def _volume_medio_24h_antes(bars: list[Bar], idx: int) -> Optional[float]:
    inicio = max(0, idx - JANELA_VOLUME_MEDIO)
    janela = bars[inicio:idx]
    return (sum(b.volume for b in janela) / len(janela)) if janela else None


def _montar_sinal(bars: list[Bar], ev: EventV1, dex: str, l_bc: Optional[float], origem: str, token: str,
                  mint: str, pool: str, tf: str, created_ts: Optional[float],
                  supply: Optional[float]) -> Optional[SinalVarredura]:
    j0 = ev.idx + 1
    if j0 >= len(bars):
        return None
    stop, topo, s_val = ev.data["stop"], ev.data["TOPO"], ev.data["S"]
    entrada_corrigida = candle_corrompido_provavel(bars, j0)
    entry_price = bars[j0].open
    if entrada_corrigida:
        for idx in range(j0 - 1, -1, -1):
            if not candle_corrompido_provavel(bars, idx):
                entry_price = bars[idx].close
                break
    if entry_price <= 0 or entry_price <= stop or entry_price >= topo:
        return None   # entrada nunca invalida -- fora do stop/TOPO, nunca um sinal de verdade
    risk_frac = (entry_price - stop) / entry_price
    return SinalVarredura(
        token=token, mint=mint or token, pool=pool, tf=tf, origem=origem, bars=bars, ev=ev, dex=dex,
        l_bc=l_bc, created_ts=created_ts, supply=supply, t_entrada=bars[j0].ts, entry_price=entry_price,
        entrada_corrigida=entrada_corrigida, stop=stop, topo=topo, s_val=s_val, risk_frac=risk_frac,
        volume_gatilho=bars[ev.idx].volume if 0 <= ev.idx < len(bars) else None,
        volume_entrada=bars[j0].volume, volume_medio_24h=_volume_medio_24h_antes(bars, j0),
        n_pavios=ev.data.get("n_testes"),
    )


def carregar_universo_admitido(db_path: Path) -> list[SinalVarredura]:
    """B1(a): TODOS os pools em `pr_pools` com status ativo/dormente/encerrado ("aposentado") e
    historico completo -- reusa `avaliar_v3_retro.parte_a_pools_admitidos`, zero replay duplicado.

    CORRECAO 2026-11-05 (rodada 9, item 2): `parte_a_pools_admitidos` nao devolve `created_ts` por
    evento (so entra depois via `calcular_covariaveis_v3`/`idade_dias`) -- este script buscava
    `created_ts=None` sempre, o que zerava SEMPRE o pareamento com controles desta origem
    (`candidatos_elegiveis`/`_controles_r72h` nunca elegem nada sem `created_ts`). Busca `info` por
    pool (MESMO padrao de `carregar_universo_nunca_admitido`/`carregar_retro_lote1`) e extrai
    `created_ts` real via `_created_ts`, sem tocar o replay/`parte_a_pools_admitidos` em si."""
    con = _conectar_ro(db_path)
    try:
        params = load_params_v3()
        linhas_pool = parte_a_pools_admitidos(con, params)
        supply_por_pool = {r["pool"]: r["supply"] for r in con.execute("SELECT pool, supply FROM pr_pools")}
        info_por_pool = {r["pool"]: r["info"] for r in con.execute("SELECT pool, info FROM pr_pools")}
    finally:
        con.close()
    sinais: list[SinalVarredura] = []
    for lp in linhas_pool:
        created_ts = _created_ts(info_por_pool.get(lp["pool"]))
        for bars, ev, dex, l_bc in lp["eventos_raw"]:
            s = _montar_sinal(bars, ev, dex, l_bc, "universo_admitido", lp["symbol"], "", lp["pool"],
                              params.timeframes[0], created_ts, supply_por_pool.get(lp["pool"]))
            if s is not None:
                sinais.append(s)
    return sorted(sinais, key=lambda s: s.t_entrada)


def carregar_universo_nunca_admitido(db_path: Path) -> list[SinalVarredura]:
    """B1(c): candidatos descobertos e NUNCA admitidos (`status IN ('rejeitado','verificado')`) que
    ja tem `pr_bars` cacheado -- zero chamada de rede, replay V3 sobre o que ja esta no banco."""
    con = _conectar_ro(db_path)
    try:
        params = load_params_v3()
        costs = CostModel()
        rows = con.execute(
            "SELECT pool, symbol, l_bc, grad_ts, launchpad, info FROM pr_pools "
            "WHERE status IN ('rejeitado', 'verificado')").fetchall()
        tf = params.timeframes[0]
        sinais: list[SinalVarredura] = []
        for row in rows:
            bars = _bars_do_pool(con, row["pool"], tf)
            if not bars:
                continue
            created_ts = _created_ts(row["info"])
            det = DetectorV1(params, tf, row["l_bc"], row["grad_ts"], created_ts)
            dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
            for bar in bars:
                for ev in det.update(bar):
                    if ev.kind != "ENTRADA":
                        continue
                    s = _montar_sinal(bars, ev, dex, row["l_bc"], "universo_nunca_admitido",
                                      row["symbol"] or row["pool"][:8], "", row["pool"], tf, created_ts,
                                      None)
                    if s is not None:
                        sinais.append(s)
        return sorted(sinais, key=lambda s: s.t_entrada)
    finally:
        con.close()


def carregar_retro_lote1(db_path: Path) -> list[SinalVarredura]:
    """B1(b): coorte retro lote1 JA congelada (`pr_retro_candidatos`) -- mesmo padrao de replay de
    `simular_v3_carteira.carregar_retro_lote1`. Lote2 NAO congelado nesta rodada (ver docstring)."""
    con = _conectar_ro(db_path)
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "pr_retro_candidatos" not in tabelas:
            return []
        params = load_params_v3()
        candidatos = con.execute(
            "SELECT pool, symbol, launchpad, grad_ts, criado_ts FROM pr_retro_candidatos").fetchall()
        tf = params.timeframes[0]
        step = tf_seconds(tf)
        sinais: list[SinalVarredura] = []
        for row in candidatos:
            pool_row = con.execute("SELECT added_ts, l_bc, launchpad, supply FROM pr_pools WHERE pool=?",
                                   (row["pool"],)).fetchone()
            if pool_row is None or pool_row["added_ts"] is None or pool_row["l_bc"] is None:
                continue
            bars = _bars_truncados(con, row["pool"], tf, step, pool_row["added_ts"])
            if not bars:
                continue
            det = DetectorV1(params, tf, pool_row["l_bc"], row["grad_ts"], row["criado_ts"])
            dex = pool_row["launchpad"] or row["launchpad"] or "desconhecido"
            for bar in bars:
                for ev in det.update(bar):
                    if ev.kind != "ENTRADA":
                        continue
                    s = _montar_sinal(bars, ev, dex, pool_row["l_bc"], "retro_lote1",
                                      row["symbol"] or row["pool"][:8], "", row["pool"], tf,
                                      row["criado_ts"], pool_row["supply"])
                    if s is not None:
                        sinais.append(s)
        return sorted(sinais, key=lambda s: s.t_entrada)
    finally:
        con.close()


def deduplicar_por_token(sinais: list[SinalVarredura]) -> dict[str, list[SinalVarredura]]:
    """B1: agrupa por token distinto para a agregacao (cada token pesa 1x depois, nunca por sinal).
    Dedup de (pool, tf, t_entrada) repetidos (mesmo evento visto 2x) DENTRO do mesmo token -- nunca
    deveria acontecer entre fontes distintas (cada fonte tem seu proprio filtro de status, mutuamente
    exclusivo), mas protege mesmo assim."""
    por_token: dict[str, list[SinalVarredura]] = {}
    vistos: set[tuple[str, str, float]] = set()
    for s in sinais:
        chave = (s.pool, s.tf, s.t_entrada)
        if chave in vistos:
            continue
        vistos.add(chave)
        por_token.setdefault(s.token, []).append(s)
    return por_token


# ---------------------------------------------------------------------------
# B2: qualidade do sinal, independente da regra de saida -- candles limpos apenas
# ---------------------------------------------------------------------------


def _toque_causal(bars: list[Bar], j0: int, entry_price: float, stop: float, alvo_r: float) -> Optional[str]:
    """Varre causalmente a partir de `j0`: 'stop' se `low<=stop` (prioridade dentro do MESMO candle,
    mesma convencao de `simulate_v1`), 'alvo' se `high>=preco_alvo`, `None` se a serie acabar sem
    decidir (candles corrompidos pulados -- NUNCA decidem, mas tambem nunca contam como "indefinido"
    so por existirem no meio do caminho). Generico (bars/entry/stop) pra servir tanto ao sinal real
    quanto a um controle/entrada aleatoria pareados (rodada 9, itens 1/3) sem duplicar a varredura."""
    risk = entry_price - stop
    if risk <= 0:
        return None
    preco_alvo = entry_price + alvo_r * risk
    for idx in range(j0, len(bars)):
        if candle_corrompido_provavel(bars, idx):
            continue
        bar = bars[idx]
        if bar.low <= stop:
            return "stop"
        if bar.high >= preco_alvo:
            return "alvo"
    return None


def _toque_binario(resultado: Optional[str]) -> Optional[float]:
    """1.0='alvo' (tocou +NR antes de -1R) / 0.0='stop' / `None`='indefinido' (nunca conta -- mesma
    convencao de `resumo_toques`)."""
    if resultado == "alvo":
        return 1.0
    if resultado == "stop":
        return 0.0
    return None


def _primeiro_toque(sinal: SinalVarredura, alvo_r: float) -> Optional[str]:
    return _toque_causal(sinal.bars, sinal.ev.idx + 1, sinal.entry_price, sinal.stop, alvo_r)


def resumo_toques(sinais: list[SinalVarredura]) -> dict[str, Any]:
    """P(tocar +1R/+2R/+3R ANTES de -1R) -- referencia de equilibrio (sem custo): 1/(1+alvo).
    `indefinido` (serie acabou sem decidir) fica de fora do denominador, nunca conta como fracasso."""
    out: dict[str, Any] = {}
    for alvo in ALVOS_R:
        resultados = [_primeiro_toque(s, alvo) for s in sinais]
        decididos = [r for r in resultados if r is not None]
        n_alvo = sum(1 for r in decididos if r == "alvo")
        n = len(decididos)
        p_obs = (100.0 * n_alvo / n) if n else None
        equilibrio = 100.0 / (1.0 + alvo)
        out[alvo] = {"n_decididos": n, "n_indefinido": len(resultados) - n, "n_alvo": n_alvo,
                    "p_observado_pct": p_obs, "equilibrio_pct": equilibrio,
                    "delta_pct": (p_obs - equilibrio) if p_obs is not None else None}
    return out


def _mfe_mae_r(sinal: SinalVarredura, horizonte_s: float) -> tuple[Optional[float], Optional[float]]:
    """MFE/MAE em R dentro do horizonte, candles LIMPOS apenas (nunca decide com dado corrompido)."""
    risk = sinal.entry_price - sinal.stop
    if risk <= 0:
        return None, None
    j0 = sinal.ev.idx + 1
    corte_ts = sinal.t_entrada + horizonte_s
    max_high: Optional[float] = None
    min_low: Optional[float] = None
    for idx in range(j0, len(sinal.bars)):
        bar = sinal.bars[idx]
        if bar.ts > corte_ts:
            break
        if candle_corrompido_provavel(sinal.bars, idx):
            continue
        max_high = bar.high if max_high is None else max(max_high, bar.high)
        min_low = bar.low if min_low is None else min(min_low, bar.low)
    if max_high is None or min_low is None:
        return None, None
    return (max_high - sinal.entry_price) / risk, (min_low - sinal.entry_price) / risk


def _r_horizonte(sinal: SinalVarredura, horizonte_s: float, now: float, params: Any, costs: CostModel) -> Optional[float]:
    r = calcular_r_horizonte(sinal.bars, sinal.ev, params, costs, sinal.dex, sinal.l_bc,
                             t_entrada=sinal.t_entrada, horizonte_s=horizonte_s, now=now)
    return r.r_mult


K_ALEATORIO = 20
ALVO_PAREAMENTO_TOQUE = 2.0   # MESMO desfecho primario do B6 (P(+2R antes de -1R) vs 33,3%)


def _candidatos_mesma_fase(sinal: SinalVarredura, params: Any) -> list[int]:
    """"Fase" = MESMA elegibilidade de `candidatos_elegiveis` (pos-pico, queda>=80%, MC>=100k, dentro
    da janela de idade da versao) -- nunca um conceito novo; serve tanto aos 10 controles pareados
    quanto ao comparador de entrada aleatoria (rodada 9, item 3), so o K e a semente mudam."""
    if sinal.created_ts is None:
        return []
    return candidatos_elegiveis(sinal.bars, sinal.created_ts, params.age_window_days,
                                tf_seconds(sinal.tf), sinal.ev.idx, DROP_MIN_CONTROLE, MC_MIN_CONTROLE)


def _controles_indices(sinal: SinalVarredura, params: Any) -> list[int]:
    """Indices dos 10 controles pareados do MESMO token (MESMA mecanica de `pos_runner/evidencia.py`
    ja usada pela H1). Compartilhado pelo pareamento em R@72h e pelo pareamento por TOQUE (rodada 9,
    item 1) -- os DOIS pareiam contra os MESMOS controles, nunca 2 sorteios independentes."""
    candidatos = _candidatos_mesma_fase(sinal, params)
    if len(candidatos) < N_CONTROLES_MINIMO:
        return []
    entry_id = abs(hash((sinal.pool, sinal.tf, sinal.t_entrada))) % (2 ** 31)
    return sortear_controles(candidatos, entry_id, sinal.origem, N_CONTROLES_PADRAO)


def _aleatorios_indices(sinal: SinalVarredura, params: Any) -> list[int]:
    """Comparador de entrada ALEATORIA (rodada 9, item 3): MESMA fase/elegibilidade dos controles
    pareados, K=20 por sinal, semente PROPRIA (sufixo ":aleatorio" nunca colide com a dos 10
    controles -- sorteios independentes sobre a MESMA populacao elegivel)."""
    candidatos = _candidatos_mesma_fase(sinal, params)
    if len(candidatos) < N_CONTROLES_MINIMO:
        return []
    entry_id = abs(hash((sinal.pool, sinal.tf, sinal.t_entrada))) % (2 ** 31)
    return sortear_controles(candidatos, entry_id, sinal.origem + ":aleatorio", K_ALEATORIO)


def _evento_controle_sinal(sinal: SinalVarredura, idx: int) -> Optional[EventV1]:
    """MESMA distancia de stop do sinal (risco_pct) e MESMA forma relativa de saida (TOPO/S escalados
    pela razao do sinal) -- via `evidencia.evento_controle`, reusado sem duplicar logica."""
    topo_mult = sinal.topo / sinal.entry_price
    s_mult = sinal.s_val / sinal.entry_price
    risco_pct_sinal = 100.0 * sinal.risk_frac
    return evento_controle(sinal.bars, idx, risco_pct_sinal, topo_mult, s_mult)


def _r72h_de_indices(sinal: SinalVarredura, indices: list[int], params: Any, costs: CostModel,
                     now: float) -> list[float]:
    """R@72h (rodada 9, item 1 -- esclarecimento): resolvido PELA REGRA se fechou antes do corte de
    72h, SENAO valorizado a MERCADO no proprio corte (`horizonte_fixo.calcular_r_horizonte`) -- a
    MESMA definicao de R@72h usada em todo o resto do projeto (H1/`analise/condicional.py`), NUNCA o
    R de saida por regra sem corte (esse so existiria se a regra fechasse antes das 72h por si --
    aqui sempre se re-mede no horizonte fixo, pra sinal e controles por igual). Censura: 'pendente'
    (horizonte ainda nao decorrido) e 'sem_dado' (entrada cancelada, fora do stop/TOPO) sao
    descartados dos DOIS lados pela MESMA regra -- nunca um corte que favoreca sinal ou controle."""
    valores: list[float] = []
    for idx in indices:
        ev_c = _evento_controle_sinal(sinal, idx)
        if ev_c is None:
            continue
        r = calcular_r_horizonte(sinal.bars, ev_c, params, costs, sinal.dex, sinal.l_bc,
                                 t_entrada=sinal.bars[idx].ts, horizonte_s=HORIZONTES_S["72h"], now=now)
        if r.r_mult is not None:
            valores.append(r.r_mult)
    return valores


def _toques_de_indices(sinal: SinalVarredura, indices: list[int], alvo_r: float) -> list[float]:
    """Resultado binario (1.0=tocou alvo antes do stop / 0.0=stop primeiro) de cada indice, MESMA
    varredura causal (`_toque_causal`) e MESMA distancia de stop do sinal (`_evento_controle_sinal`)
    -- usado tanto no pareamento por toque (item 1) quanto no comparador aleatorio (item 3).
    'indefinido' nunca conta (mesma convencao de `_toque_binario`)."""
    valores: list[float] = []
    for idx in indices:
        ev_c = _evento_controle_sinal(sinal, idx)
        if ev_c is None:
            continue
        entry_c = sinal.bars[ev_c.idx + 1].open
        stop_c = ev_c.data["stop"]
        b = _toque_binario(_toque_causal(sinal.bars, ev_c.idx + 1, entry_c, stop_c, alvo_r))
        if b is not None:
            valores.append(b)
    return valores


def _bootstrap_ic_media(valores_por_token: dict[str, list[float]], confianca: float = CONFIANCA_H1,
                        n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO
                        ) -> Optional[tuple[float, float]]:
    chaves = sorted(valores_por_token)
    n = len(chaves)
    if n == 0:
        return None
    rng = np.random.default_rng(seed)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        valores = [v for idx in escolhidos for v in valores_por_token[chaves[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    alpha = 1.0 - confianca
    return float(np.percentile(medias, 100.0 * alpha / 2.0)), float(np.percentile(medias, 100.0 * (1.0 - alpha / 2.0)))


@dataclasses.dataclass
class Pareamento:
    """Resumo de uma amostra pareada por token (reusado pro pareamento em R@72h E pro pareamento por
    toque, rodada 9, item 1 -- MESMAS 5 estatisticas, nunca duplicadas por metrica)."""
    media: Optional[float]
    mediana: Optional[float]
    sem_top3: Optional[float]
    ic90_bootstrap: Optional[tuple[float, float]]
    n: int


def _resumir_pareamento(valores_por_token: dict[str, list[float]]) -> Pareamento:
    valores = [v for lst in valores_por_token.values() for v in lst]
    media = statistics.fmean(valores) if valores else None
    mediana = statistics.median(valores) if valores else None
    sem_top3 = None
    if len(valores) > 3:
        maiores = set(sorted(range(len(valores)), key=lambda i: valores[i], reverse=True)[:3])
        resto = [v for i, v in enumerate(valores) if i not in maiores]
        sem_top3 = statistics.fmean(resto) if resto else None
    return Pareamento(media, mediana, sem_top3, _bootstrap_ic_media(valores_por_token), len(valores))


def calcular_equilibrio_empirico(sinais: list[SinalVarredura], params: Any) -> dict[float, dict[str, Any]]:
    """Rodada 9, item 3: equilibrio EMPIRICO de P(+NR antes de -1R) via K=20 entradas aleatorias por
    sinal (MESMA fase/distancia de stop dos controles pareados, semente propria) -- substitui o
    teorico 1/(1+N) como referencia (que ignora custo/friccao/regime do universo real) quando houver
    dado suficiente; NUNCA remove o teorico do relatorio, soma ao lado."""
    valores_por_token: dict[float, dict[str, list[float]]] = {alvo: {} for alvo in ALVOS_R}
    for s in sinais:
        indices = _aleatorios_indices(s, params)
        if not indices:
            continue
        for alvo in ALVOS_R:
            vals = _toques_de_indices(s, indices, alvo)
            if vals:
                valores_por_token[alvo].setdefault(s.token, []).extend(vals)
    out: dict[float, dict[str, Any]] = {}
    for alvo in ALVOS_R:
        vpt = valores_por_token[alvo]
        todos_vals = [v for lst in vpt.values() for v in lst]
        p = (100.0 * statistics.fmean(todos_vals)) if todos_vals else None
        ic = _bootstrap_ic_media(vpt) if vpt else None
        out[alvo] = {
            "p_empirico_pct": p,
            "ic90_empirico_pct": (ic[0] * 100.0, ic[1] * 100.0) if ic else None,
            "n_draws": len(todos_vals), "n_tokens": len(vpt),
        }
    return out


# ---------------------------------------------------------------------------
# B3: agregacao por token, estratos (reusa condicional.py sem duplicar logica)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResultadoOrigem:
    origem: str
    n_sinais: int
    n_tokens: int
    n_pool_dias_ativos: int
    n_corrompidos: int
    n_volume_baixo: int
    toques: dict[float, dict[str, Any]]
    equilibrio_empirico: dict[float, dict[str, Any]]
    dif_pareada: Pareamento
    dif_toque: Pareamento
    estratos: list[GrupoExploratorio]


def agregar_origem(sinais: list[SinalVarredura], origem_label: str, now: float) -> ResultadoOrigem:
    params = load_params_v3()
    costs = CostModel()
    por_token = deduplicar_por_token(sinais)
    todos = [s for lst in por_token.values() for s in lst]
    n_corrompidos = sum(1 for s in todos if s.entrada_corrigida)
    n_volume_baixo = sum(1 for s in todos if s.volume_entrada is not None and s.volume_medio_24h
                         and s.volume_entrada < 0.25 * s.volume_medio_24h)
    pool_dias = {(s.pool, int(s.t_entrada // 86400)) for s in todos}
    toques = resumo_toques(todos)
    equilibrio_empirico = calcular_equilibrio_empirico(todos, params)

    dif_por_token: dict[str, list[float]] = {}
    dif_toque_por_token: dict[str, list[float]] = {}
    resolvidos: list[SinalResolvido] = []
    for idx, s in enumerate(todos):
        escolhidos = _controles_indices(s, params)   # MESMOS 10 controles pro R e pro toque (item 1)
        if not escolhidos:
            continue
        controles_r = _r72h_de_indices(s, escolhidos, params, costs, now)
        r72 = _r_horizonte(s, HORIZONTES_S["72h"], now, params, costs)
        if r72 is not None and controles_r:
            dif = r72 - statistics.fmean(controles_r)
            dif_por_token.setdefault(s.token, []).append(dif)
            cov = calcular_covariaveis_v3(s.bars, s.ev, tf_seconds(s.tf), s.l_bc)
            resolvidos.append(SinalResolvido(
                entry_id=idx, mint=s.mint, symbol=s.token, t_entrada=s.t_entrada, dif_pareada=dif,
                gatilho=(), risco_pct=100.0 * s.risk_frac, liquidez_usd=None, holders_tag=None, tags=(),
                janela_ouro=None, caixa_candles=cov.caixa_candles, caixa_horas=cov.caixa_horas,
                idade_dias=cov.idade_dias, mc_na_entrada=None, queda_pico_pct=cov.queda_pico_pct,
                mc_base=cov.mc_base, razao_corpo_descomunal=cov.razao_corpo_descomunal,
                possivel_clone=cov.possivel_clone, gatilho_v3=cov.gatilho_tag,
            ))
        controles_toque = _toques_de_indices(s, escolhidos, ALVO_PAREAMENTO_TOQUE)
        s_toque = _toque_binario(_primeiro_toque(s, ALVO_PAREAMENTO_TOQUE))
        if s_toque is not None and controles_toque:
            dif_toque_por_token.setdefault(s.token, []).append(s_toque - statistics.fmean(controles_toque))

    estratos = rodar_exploratorias_v3(resolvidos) if len(resolvidos) >= 10 else []

    return ResultadoOrigem(
        origem=origem_label, n_sinais=len(todos), n_tokens=len(por_token),
        n_pool_dias_ativos=len(pool_dias), n_corrompidos=n_corrompidos, n_volume_baixo=n_volume_baixo,
        toques=toques, equilibrio_empirico=equilibrio_empirico,
        dif_pareada=_resumir_pareamento(dif_por_token), dif_toque=_resumir_pareamento(dif_toque_por_token),
        estratos=estratos,
    )


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _formatar_pareamento(titulo: str, p: Pareamento) -> str:
    ic_txt = f"[{p.ic90_bootstrap[0]:+.2f},{p.ic90_bootstrap[1]:+.2f}]" if p.ic90_bootstrap else "s/d"
    media_txt = f"{p.media:+.2f}" if p.media is not None else "s/d"
    mediana_txt = f"{p.mediana:+.2f}" if p.mediana is not None else "s/d"
    sem_top3_txt = f"{p.sem_top3:+.2f}" if p.sem_top3 is not None else "s/d"
    return (f"{titulo} (pareados={p.n}): media={media_txt} | mediana={mediana_txt} | "
           f"sem top-3={sem_top3_txt} | IC90% bootstrap={ic_txt}")


def _formatar_origem(r: ResultadoOrigem) -> list[str]:
    out = [f"## {r.origem}", "",
          f"n sinais: {r.n_sinais} | tokens distintos: {r.n_tokens} | pool-dias ativos: "
          f"{r.n_pool_dias_ativos}",
          f"dependem de candle corrompido: {r.n_corrompidos} | entrada com volume <25% media 24h: "
          f"{r.n_volume_baixo}", ""]
    if r.n_sinais == 0:
        out.append("(sem sinais nesta origem -- universo vazio para esta fonte nesta base)")
        out.append("")
        return out
    out.append("P(tocar +NR antes de -1R) -- equilibrio TEORICO sem custo = 100/(1+N)%, e equilibrio "
              "EMPIRICO (rodada 9, item 3: K=20 entradas aleatorias/sinal, mesma fase/distancia de "
              "stop, no lugar do teorico):")
    for alvo, d in sorted(r.toques.items()):
        p_txt = f"{d['p_observado_pct']:.1f}%" if d["p_observado_pct"] is not None else "s/d"
        delta_txt = f"{d['delta_pct']:+.1f}pp" if d["delta_pct"] is not None else "s/d"
        emp = r.equilibrio_empirico.get(alvo, {})
        if emp.get("p_empirico_pct") is not None:
            ic_e = emp.get("ic90_empirico_pct")
            ic_e_txt = f" IC90%=[{ic_e[0]:.1f},{ic_e[1]:.1f}]" if ic_e else ""
            emp_txt = (f"empirico={emp['p_empirico_pct']:.1f}%{ic_e_txt} (sorteios={emp['n_draws']}, "
                      f"tokens={emp['n_tokens']})")
        else:
            emp_txt = "empirico=s/d (sem entrada elegivel p/ sorteio)"
        out.append(f"  +{alvo:.0f}R: observado={p_txt} (n={d['n_decididos']}, indefinido="
                  f"{d['n_indefinido']}) | teorico={d['equilibrio_pct']:.1f}% | delta={delta_txt} | "
                  f"{emp_txt}")
    out.append("")
    out.append(_formatar_pareamento(
        "Dif. pareada vs 10 controles, R@72h (regra se fechou antes do corte, senao marcado a "
        "mercado no corte -- NUNCA R de regra sem corte; censura 'pendente'/'sem_dado' descartada "
        "dos 2 lados igualmente)", r.dif_pareada))
    out.append(_formatar_pareamento(
        f"Dif. pareada vs 10 controles, TOQUE (+{ALVO_PAREAMENTO_TOQUE:.0f}R antes de -1R, sinal=1/0 "
        "menos media dos controles)", r.dif_toque))
    if r.dif_pareada.n == 0 and r.dif_toque.n == 0:
        out.append("  (pareamento=0: created_ts ausente OU nenhum candle do pool passa queda>=80% "
                  "desde o pico e MC>=100k dentro da janela de idade da V3 -- nunca um corte que "
                  "favoreca sinal ou controle, so falta de candidato elegivel nesta origem)")
    out.append("")
    if r.estratos:
        out.append("Estratos exploratorios (8 pre-registrados, Holm sobre a familia completa):")
        for g in r.estratos:
            marca = " [SIGNIFICATIVO sob Holm]" if g.significativo_holm else ""
            out.append(f"  {g.hipotese} / {g.grupo}: n={g.n_tokens} media={g.media_dif_pareada:+.2f} "
                      f"p={g.p_valor:.3f}{marca}")
    else:
        out.append("Estratos exploratorios: menos de 10 sinais pareados -- nao avaliado nesta origem.")
    out.append("")
    return out


def formatar(ao_vivo_admitido: ResultadoOrigem, nunca_admitido: ResultadoOrigem,
            retro: ResultadoOrigem) -> str:
    out = ["# varredura_v3 -- descoberta de oportunidade da V3 (sem limite de capital/vagas)", "",
          f"AVISO: {AVISO}", ""]
    for r in (ao_vivo_admitido, nunca_admitido, retro):
        out.extend(_formatar_origem(r))
    out.append(f"({AVISO})")
    return "\n".join(out)


def _linhas_csv(r: ResultadoOrigem) -> list[dict[str, Any]]:
    linha: dict[str, Any] = {
        "origem": r.origem, "n_sinais": r.n_sinais, "n_tokens": r.n_tokens,
        "n_pool_dias_ativos": r.n_pool_dias_ativos, "n_corrompidos": r.n_corrompidos,
        "n_volume_baixo": r.n_volume_baixo,
        "dif_pareada_r72h_media": r.dif_pareada.media, "dif_pareada_r72h_mediana": r.dif_pareada.mediana,
        "dif_pareada_r72h_sem_top3": r.dif_pareada.sem_top3,
        "dif_pareada_r72h_ic90_lo": r.dif_pareada.ic90_bootstrap[0] if r.dif_pareada.ic90_bootstrap else None,
        "dif_pareada_r72h_ic90_hi": r.dif_pareada.ic90_bootstrap[1] if r.dif_pareada.ic90_bootstrap else None,
        "n_pareados_r72h": r.dif_pareada.n,
        "dif_pareada_toque_media": r.dif_toque.media, "dif_pareada_toque_mediana": r.dif_toque.mediana,
        "dif_pareada_toque_sem_top3": r.dif_toque.sem_top3,
        "dif_pareada_toque_ic90_lo": r.dif_toque.ic90_bootstrap[0] if r.dif_toque.ic90_bootstrap else None,
        "dif_pareada_toque_ic90_hi": r.dif_toque.ic90_bootstrap[1] if r.dif_toque.ic90_bootstrap else None,
        "n_pareados_toque": r.dif_toque.n,
    }
    for alvo, d in r.toques.items():
        linha[f"p_toque_{int(alvo)}r_pct"] = d["p_observado_pct"]
        linha[f"n_decididos_{int(alvo)}r"] = d["n_decididos"]
        emp = r.equilibrio_empirico.get(alvo, {})
        linha[f"p_empirico_{int(alvo)}r_pct"] = emp.get("p_empirico_pct")
        linha[f"n_draws_empirico_{int(alvo)}r"] = emp.get("n_draws")
    return [linha]


def _escrever_csv(path: Path, linhas: list[dict[str, Any]]) -> None:
    import csv as _csv
    if not linhas:
        return
    campos = list(linhas[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)


def executar(db_path: Path, csv_path: Optional[Path] = None, progresso: bool = True,
            min_ram_mb: float = RAM_MINIMA_MB_PADRAO) -> str:
    import sys as _sys
    checar_ram_ou_abortar(min_ram_mb)

    def status(msg: str) -> None:
        if progresso:
            print(f"[varredura_v3] {msg}", file=_sys.stderr, flush=True)

    now = time.time()
    status("carregando universo_admitido (pode levar um tempo -- replay completo de todos os pools)...")
    admitido = carregar_universo_admitido(db_path)
    status(f"universo_admitido: {len(admitido)} sinais brutos. carregando universo_nunca_admitido...")
    nunca_admitido = carregar_universo_nunca_admitido(db_path)
    status(f"universo_nunca_admitido: {len(nunca_admitido)} sinais brutos. carregando retro_lote1...")
    retro = carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais brutos. agregando (pareamento com controles, estratos)...")
    r_admitido = agregar_origem(admitido, "universo_admitido", now)
    status("universo_admitido agregado.")
    r_nunca_admitido = agregar_origem(nunca_admitido, "universo_nunca_admitido", now)
    status("universo_nunca_admitido agregado.")
    r_retro = agregar_origem(retro, "retro_lote1", now)
    status("retro_lote1 agregado. montando relatorio.")
    texto = formatar(r_admitido, r_nunca_admitido, r_retro)
    if csv_path is not None:
        linhas = _linhas_csv(r_admitido) + _linhas_csv(r_nunca_admitido) + _linhas_csv(r_retro)
        _escrever_csv(csv_path, linhas)
        texto += f"\n(tabela tambem gravada em {csv_path})"
    return texto


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Varredura exploratoria de qualidade de sinal da V3 -- PAPER/so leitura/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--csv", type=Path, default=None, help="grava a tabela por origem em CSV")
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    args = parser.parse_args(argv)
    print(executar(args.db, csv_path=args.csv, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
