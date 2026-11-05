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
  (pr_retro_candidatos + candles truncados em `pr_pools.added_ts`).
  **Congelamento do "lote 2" (NAO implementado nesta rodada)**: exigiria uma tabela/coluna nova pra
  distinguir 2 congelamentos (hoje `pr_retro_candidatos` so guarda 1 `lista_hash`/`congelado_em`
  global) -- fica documentado como proximo passo (reusar `avaliar_candidatos_retro.
  congelar_candidatos`, adaptado pra um `lote` explicito), nunca feito aqui sem essa decisao de
  schema. O lote1 ja congelado continua intocado.
- B1(c) "candidatos nunca admitidos com historico obtivel": pools com `status IN
  ('rejeitado','verificado')` que JA tem `pr_bars` cacheado (zero chamada nova) -- rotulado
  `universo_nunca_admitido`.
- B1(d) "ampliar o historico via coleta lenta": EXPLICITAMENTE opcional no pedido e exige chamadas
  de rede ao vivo -- NAO implementado aqui (um script somente-leitura nunca deveria iniciar
  coleta); documentado como trabalho futuro, separado, em tmux proprio, nunca concorrendo com o
  bot.
- B2 "comparacao contra entradas aleatorias no mesmo pool/fase": NAO implementada nesta rodada
  (escopo cortado por tempo) -- so o pareamento contra os 10 controles (MESMA mecanica da H1,
  `pos_runner/evidencia.py`) foi implementado. Fica documentado como extensao futura.
- B3 estratos: reusa DIRETAMENTE `analise.condicional._grupos_v3_estratos`/`rodar_exploratorias_v3`
  (os MESMOS 8 estratos pre-registrados pra V3, Holm sobre a familia completa) -- zero logica
  estatistica nova, so monta `SinalResolvido` com a covariavel certa
  (`pos_runner_v3.calcular_covariaveis_v3`, ja existente) e `dif_pareada` = R@72h do sinal menos a
  media dos controles no MESMO horizonte.
- B5 "nice/tmux": este script e passivo (nunca inicia um processo proprio) -- o comando de VM abaixo
  ja empacota nice+tmux; o script so faz o check de RAM antes de comecar (`--min-ram-mb`, aborta se
  insuficiente) e imprime progresso.

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
    historico completo -- reusa `avaliar_v3_retro.parte_a_pools_admitidos`, zero replay duplicado."""
    con = _conectar_ro(db_path)
    try:
        params = load_params_v3()
        linhas_pool = parte_a_pools_admitidos(con, params)
        supply_por_pool = {r["pool"]: r["supply"] for r in con.execute("SELECT pool, supply FROM pr_pools")}
    finally:
        con.close()
    sinais: list[SinalVarredura] = []
    for lp in linhas_pool:
        for bars, ev, dex, l_bc in lp["eventos_raw"]:
            created_ts = None  # `parte_a_pools_admitidos` nao devolve created_ts por evento; a
                               # idade entra via `calcular_covariaveis_v3` (data.get("idade_dias")).
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


def _primeiro_toque(sinal: SinalVarredura, alvo_r: float) -> Optional[str]:
    """Varre causalmente a partir do candle de entrada: 'stop' se `low<=stop` (prioridade dentro do
    MESMO candle, mesma convencao de `simulate_v1`), 'alvo' se `high>=preco_alvo`, `None` se a serie
    acabar sem decidir (candles corrompidos pulados -- NUNCA decidem, mas tambem nunca contam como
    "indefinido" so por existirem no meio do caminho)."""
    risk = sinal.entry_price - sinal.stop
    if risk <= 0:
        return None
    preco_alvo = sinal.entry_price + alvo_r * risk
    j0 = sinal.ev.idx + 1
    for idx in range(j0, len(sinal.bars)):
        if candle_corrompido_provavel(sinal.bars, idx):
            continue
        bar = sinal.bars[idx]
        if bar.low <= sinal.stop:
            return "stop"
        if bar.high >= preco_alvo:
            return "alvo"
    return None


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


def _controles_r72h(sinal: SinalVarredura, params: Any, costs: CostModel, now: float) -> list[float]:
    """R@72h dos 10 controles pareados do MESMO token (MESMA mecanica de `pos_runner/evidencia.py`
    ja usada pela H1) -- nunca muda a regra de sorteio/qualificacao, so mede no horizonte fixo."""
    if sinal.created_ts is None:
        return []
    candidatos = candidatos_elegiveis(sinal.bars, sinal.created_ts, params.age_window_days,
                                      tf_seconds(sinal.tf), sinal.ev.idx, DROP_MIN_CONTROLE, MC_MIN_CONTROLE)
    if len(candidatos) < N_CONTROLES_MINIMO:
        return []
    entry_id = abs(hash((sinal.pool, sinal.tf, sinal.t_entrada))) % (2 ** 31)
    escolhidos = sortear_controles(candidatos, entry_id, sinal.origem, N_CONTROLES_PADRAO)
    topo_mult = sinal.topo / sinal.entry_price
    s_mult = sinal.s_val / sinal.entry_price
    risco_pct_sinal = 100.0 * sinal.risk_frac
    valores: list[float] = []
    for idx in escolhidos:
        ev_c = evento_controle(sinal.bars, idx, risco_pct_sinal, topo_mult, s_mult)
        if ev_c is None:
            continue
        r = calcular_r_horizonte(sinal.bars, ev_c, params, costs, sinal.dex, sinal.l_bc,
                                 t_entrada=sinal.bars[idx].ts, horizonte_s=HORIZONTES_S["72h"], now=now)
        if r.r_mult is not None:
            valores.append(r.r_mult)
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
    dif_pareada_media: Optional[float]
    dif_pareada_mediana: Optional[float]
    dif_pareada_sem_top3: Optional[float]
    ic90_bootstrap: Optional[tuple[float, float]]
    n_pareados: int
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

    dif_por_token: dict[str, list[float]] = {}
    resolvidos: list[SinalResolvido] = []
    for idx, s in enumerate(todos):
        r72 = _r_horizonte(s, HORIZONTES_S["72h"], now, params, costs)
        if r72 is None:
            continue
        controles = _controles_r72h(s, params, costs, now)
        if not controles:
            continue
        dif = r72 - statistics.fmean(controles)
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

    dif_valores = [dif for lst in dif_por_token.values() for dif in lst]
    dif_media = statistics.fmean(dif_valores) if dif_valores else None
    dif_mediana = statistics.median(dif_valores) if dif_valores else None
    dif_sem_top3 = None
    if len(dif_valores) > 3:
        maiores = set(sorted(range(len(dif_valores)), key=lambda i: dif_valores[i], reverse=True)[:3])
        resto = [v for i, v in enumerate(dif_valores) if i not in maiores]
        dif_sem_top3 = statistics.fmean(resto) if resto else None

    estratos = rodar_exploratorias_v3(resolvidos) if len(resolvidos) >= 10 else []

    return ResultadoOrigem(
        origem=origem_label, n_sinais=len(todos), n_tokens=len(por_token),
        n_pool_dias_ativos=len(pool_dias), n_corrompidos=n_corrompidos, n_volume_baixo=n_volume_baixo,
        toques=toques, dif_pareada_media=dif_media, dif_pareada_mediana=dif_mediana,
        dif_pareada_sem_top3=dif_sem_top3, ic90_bootstrap=_bootstrap_ic_media(dif_por_token),
        n_pareados=len(dif_valores), estratos=estratos,
    )


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _formatar_origem(r: ResultadoOrigem) -> list[str]:
    out = [f"## {r.origem}", "",
          f"n sinais: {r.n_sinais} | tokens distintos: {r.n_tokens} | pool-dias ativos: "
          f"{r.n_pool_dias_ativos}",
          f"dependem de candle corrompido: {r.n_corrompidos} | entrada com volume <25% media 24h: "
          f"{r.n_volume_baixo}", ""]
    out.append("P(tocar +NR antes de -1R) -- referencia de equilibrio sem custo = 100/(1+N)%:")
    for alvo, d in sorted(r.toques.items()):
        p_txt = f"{d['p_observado_pct']:.1f}%" if d["p_observado_pct"] is not None else "s/d"
        delta_txt = f"{d['delta_pct']:+.1f}pp" if d["delta_pct"] is not None else "s/d"
        out.append(f"  +{alvo:.0f}R: observado={p_txt} (n={d['n_decididos']}, indefinido="
                  f"{d['n_indefinido']}) | equilibrio={d['equilibrio_pct']:.1f}% | delta={delta_txt}")
    out.append("")
    ic_txt = f"[{r.ic90_bootstrap[0]:+.2f},{r.ic90_bootstrap[1]:+.2f}]" if r.ic90_bootstrap else "s/d"
    media_txt = f"{r.dif_pareada_media:+.2f}" if r.dif_pareada_media is not None else "s/d"
    mediana_txt = f"{r.dif_pareada_mediana:+.2f}" if r.dif_pareada_mediana is not None else "s/d"
    sem_top3_txt = f"{r.dif_pareada_sem_top3:+.2f}" if r.dif_pareada_sem_top3 is not None else "s/d"
    out.append(f"Dif. pareada vs 10 controles (R, pareados={r.n_pareados}): media={media_txt} | "
              f"mediana={mediana_txt} | sem top-3={sem_top3_txt} | IC90% bootstrap={ic_txt}")
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
        "n_volume_baixo": r.n_volume_baixo, "dif_pareada_media": r.dif_pareada_media,
        "dif_pareada_mediana": r.dif_pareada_mediana, "dif_pareada_sem_top3": r.dif_pareada_sem_top3,
        "ic90_lo": r.ic90_bootstrap[0] if r.ic90_bootstrap else None,
        "ic90_hi": r.ic90_bootstrap[1] if r.ic90_bootstrap else None, "n_pareados": r.n_pareados,
    }
    for alvo, d in r.toques.items():
        linha[f"p_toque_{int(alvo)}r_pct"] = d["p_observado_pct"]
        linha[f"n_decididos_{int(alvo)}r"] = d["n_decididos"]
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
