"""PEDIDO 2026-11-05 (autorizado): simulacao de carteira ($100 inicial) sobre os sinais V3, SOMENTE
LEITURA (zero chamada de rede, zero escrita em qualquer tabela). PAPER/READ-ONLY. V3 roda com
ParamsV3 CONGELADO (`56762db29cd6`) -- este script NUNCA altera detector/simulate/parametros/H1/
criterios de sinal. EXPLORATORIO: os numeros aqui NUNCA constituem evidencia de edge (isso exige
H1/pre-registro formal, `analise/condicional.py`) -- este script e sobre EXECUCAO/CUSTO/TAMANHO DE
POSICAO, nunca sobre se o sinal "funciona".

Regras novas de saida (ex.: vender no power candle descomunal) NAO sao aplicadas aqui -- se
autorizadas no futuro, entram como "V4-candidata EXPLORATORIA" (rotulada, script separado), nunca
misturadas a V3.

ESCOPO DESTA RODADA (simplificacoes documentadas, nunca escondidas):
- carteira ($100, T10/T20/T30/T-qualidade, custo/slippage) roda sobre ao_vivo (pr3_signals) -- a
  fonte real de execucao. retro_lote1/replay_v3 aparecem SEPARADOS no relatorio (amostra/
  estatisticas, MESMO pipeline de R marcado a mercado), mas sem carteira $ propria (sao, por
  natureza, hipoteticos -- nunca posicoes reais que concorreriam por capital/vagas de verdade).
- corrigir "preco de entrada apos a latencia medida" usa `ts_alerta`/`alert_ts` (ja gravados) pra
  achar o 1o candle que o bot podia realmente agir, quando a tag `entrada_atrasada` esta presente;
  sem esses campos, cai no candle de execucao padrao (bars[j0].open), sinalizado.
- "nº de pavios" usa a covariavel JA existente `n_pavios`/`ev.data["n_testes"]` (quantidade de testes
  de suporte detectados pelo detector V3) -- a formula de T-qualidade e MINHA escolha documentada (o
  pedido dizia "ex."), nunca otimizada nem re-tunada depois de ver resultado.
- teto de supply usa `pr_pools.supply` (ja gravado via lineage on-chain) x `entry_price` -- sem
  supply conhecido, o teto simplesmente nao se aplica (nunca inventa supply). Teto de liquidez usa
  `liquidez_usd` do sinal -- a V3 NUNCA calcula esse campo hoje (fica sempre NULL, mesma
  simplificacao ja documentada em `pos_runner_v3.py`), entao na pratica este teto fica sem efeito
  na amostra atual; o parametro/formula ja estao prontos pra quando `liquidez_usd` for computado p/
  V3.
- PEDIDO 2026-11-05 (revisao do item 3): tamanho agora e FRACAO FIXA do capital (nao mais risco
  fixo); capital "livre" so conta saldo JA REALIZADO -- uma posicao aberta trava seu tamanho (nunca
  soma ao caixa disponivel) ate o proprio horizonte de 72h liberar (principal + resultado), nunca
  antes (corrige um lapso da 1a versao deste script, que creditava o resultado no instante da
  ENTRADA em vez do fechamento, e nunca debitava o principal travado do caixa livre -- ja corrigido
  aqui).
- probabilidade de ruina (item 5): bootstrap por token sobre uma linha do TEMPO SINTETICA (blocos
  concatenados em sequencia, nunca a data real -- evita que sortear o mesmo token >1x crie posicoes
  "simultaneas" que nunca existiram). Roda o ledger completo 10000x por combinacao (regra x
  slippage x custo) -- pode levar de segundos a ~1min com dezenas de sinais; aceitavel pra um
  script sob demanda, nunca chamado pelo bot ao vivo.

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.simular_v3_carteira --db signals_mvp/dados/estado.sqlite
    python -m signals_mvp.scripts.simular_v3_carteira --db ... --desde 2026-10-01
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..analise.condicional import CONFIANCA_H1, N_BOOTSTRAP_PADRAO, RISCO_IRREALISTA_MIN_PCT, SEED_PADRAO
from ..config import make_paths
from ..pos_runner.candles import Bar, candle_corrompido_provavel, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.detector_v1 import EventV1
from ..pos_runner.horizonte_fixo import HORIZONTES_S, calcular_r_horizonte
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from .avaliar_v3_retro import _conectar_ro, parte_a_pools_admitidos
from .exit_lab import _variante_a, _variante_c, _variante_d

AVISO = ("EXPLORATORIO -- NUNCA evidencia de edge (H1/pre-registro decidem isso, nao este script). "
        "retro_lote1/replay_v3 sao amostra DENTRO da amostra (nunca population real); resultado em "
        "paper e TETO de execucao (a execucao real so pode ser igual ou pior).")

JANELA_VOLUME_MEDIO = 24   # candles 1h anteriores -- "media horaria das 24h antes"
VOLUME_BAIXO_FRAC = 0.25   # abaixo disso da media -> slippage extra
SLIPPAGE_EXTRA_R_MAX = 0.10   # na borda (volume_entrada ~= 0) -- escala linear, documentado abaixo
SLIPPAGE_VARIANTES: dict[str, float] = {"base": 0.0, "+0.1R": 0.1, "+0.3R": 0.3}
CUSTO_FIXO_VARIANTES: dict[str, float] = {"US$0.05": 0.05, "US$0.15": 0.15, "US$0.30": 0.30}
CAPITAL_INICIAL_USD = 100.0
MAX_POSICOES_PADRAO = 4
PCT_SUPPLY_MAX = 1.5            # teto fixo: posicao nunca > 1,5% do supply total do token
MAX_LIQUIDEZ_PCT_PADRAO = 20.0  # teto parametrizavel: posicao nunca > X% da liquidez do pool
LIMITE_RUINA_USD = 50.0         # "banca cair abaixo de US$50" -- limiar fixo do pedido


# ---------------------------------------------------------------------------
# amostra: 1 Trade por sinal, 3 origens SEPARADAS (nunca somadas)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TradeV3:
    token: str
    mint: str
    pool: str
    tf: str
    origem: str                       # 'ao_vivo' | 'retro_lote1' | 'replay_v3'
    t_entrada: float
    entry_price: float
    entry_price_corrigido: bool        # candle de entrada corrompido -> usou o candle limpo anterior
    entrada_atrasada_corrigida: bool   # entrada_atrasada (ao_vivo) -> usou o 1o candle pos-latencia
    risk_frac: Optional[float]
    volume_entrada: Optional[float]
    volume_medio_24h: Optional[float]
    n_pavios: Optional[int]
    supply: Optional[float]
    liquidez_usd: Optional[float]
    # desfechos -- PRIMARIO = R marcado a mercado em 72h; secundarios = regra e 7d.
    status_72h: str
    r_72h: Optional[float]
    r_regra: Optional[float]
    r_7d: Optional[float]
    # sombra exploratoria (C/D), nunca escolhida:
    r_sombra_c: Optional[float]
    r_sombra_d: Optional[float]


def _candle_limpo_na_entrada(bars: list[Bar], j0: int) -> tuple[float, bool]:
    """PEDIDO 2026-11-05 (item 2): candle de entrada corrompido nunca decide o preco -- usa o
    ultimo candle LIMPO anterior (`candle_corrompido_provavel`, MESMA checagem do item 1). Devolve
    (preco, foi_corrigido)."""
    if not candle_corrompido_provavel(bars, j0):
        return bars[j0].open, False
    for idx in range(j0 - 1, -1, -1):
        if not candle_corrompido_provavel(bars, idx):
            return bars[idx].close, True
    return bars[j0].open, True   # nenhum candle limpo antes -- usa o original, mas AVISA (contado)


def _preco_apos_latencia(bars: list[Bar], j0: int, ts_alerta: Optional[float]) -> tuple[float, int, bool]:
    """PEDIDO 2026-11-05 (item 2): sinal `entrada_atrasada` -- usa o preco do 1o candle cujo `ts` e
    >= `ts_alerta` (1o momento em que o bot realmente PODERIA ter agido), nunca o open retroativo do
    candle do gatilho. Sem `ts_alerta` conhecido, cai no padrao (bars[j0], sinalizado via `False`)."""
    if ts_alerta is None:
        return bars[j0].open, j0, False
    for idx in range(j0, len(bars)):
        if bars[idx].ts >= ts_alerta:
            return bars[idx].open, idx, True
    return bars[j0].open, j0, False


def _volume_medio_24h_antes(bars: list[Bar], idx: int) -> Optional[float]:
    inicio = max(0, idx - JANELA_VOLUME_MEDIO)
    janela = bars[inicio:idx]
    return (sum(b.volume for b in janela) / len(janela)) if janela else None


def _montar_trade(
    bars: list[Bar], ev: EventV1, params: Any, costs: CostModel, dex: str, l_bc: Optional[float],
    origem: str, token: str, mint: str, pool: str, tf: str, now: float,
    ts_alerta: Optional[float] = None, entrada_atrasada: bool = False,
    supply: Optional[float] = None, liquidez_usd: Optional[float] = None,
) -> Optional[TradeV3]:
    j0 = ev.idx + 1
    if j0 >= len(bars):
        return None
    stop, topo, s_val = ev.data["stop"], ev.data["TOPO"], ev.data["S"]
    entry_idx = j0
    entrada_atrasada_corrigida = False
    if entrada_atrasada and ts_alerta is not None:
        entry_price, entry_idx, entrada_atrasada_corrigida = _preco_apos_latencia(bars, j0, ts_alerta)
        entry_corrigido = False
    else:
        entry_price, entry_corrigido = _candle_limpo_na_entrada(bars, j0)
    if entry_price <= 0 or entry_price <= stop or entry_price >= topo:
        return None   # entrada invalida (fora do stop/TOPO) -- nunca um trade de verdade
    risk_frac = (entry_price - stop) / entry_price
    t_entrada = bars[j0].ts
    volume_entrada = bars[entry_idx].volume if entry_idx < len(bars) else None
    volume_medio_24h = _volume_medio_24h_antes(bars, j0)
    n_pavios = ev.data.get("n_testes")

    r_por_horizonte: dict[str, Any] = {}
    for horizonte, horizonte_s in HORIZONTES_S.items():
        r_por_horizonte[horizonte] = calcular_r_horizonte(bars, ev, params, costs, dex, l_bc,
                                                          t_entrada=t_entrada, horizonte_s=horizonte_s, now=now)
    r72 = r_por_horizonte["72h"]
    r7d = r_por_horizonte["7d"]

    # secundario (censurado): R de saida por regra, SEM corte de horizonte -- serie completa (reusa
    # `exit_lab._variante_a`, a variante "atual" -- MESMA regra oficial, equivalencia de custo
    # documentada em exit_lab.py).
    r_regra: Optional[float] = None
    res_a = _variante_a(bars, j0, stop, topo, s_val, params, costs, dex, l_bc)
    net_regra = res_a.net_ret if res_a.net_ret is not None else res_a.net_ret_marcado
    if net_regra is not None and risk_frac and 100.0 * risk_frac >= RISCO_IRREALISTA_MIN_PCT:
        r_regra = net_regra / risk_frac

    # sombra exploratoria C/D (lado a lado, nunca escolhida) -- reusa exit_lab, serie completa.
    r_sombra_c = r_sombra_d = None
    if risk_frac and 100.0 * risk_frac >= RISCO_IRREALISTA_MIN_PCT:
        res_c = _variante_c(bars, j0, entry_price, stop, ev.data.get("R"), costs, dex, l_bc)
        res_d = _variante_d(bars, j0, entry_price, stop, topo, params, costs, dex, l_bc)
        net_c = res_c.net_ret if res_c.net_ret is not None else res_c.net_ret_marcado
        net_d = res_d.net_ret if res_d.net_ret is not None else res_d.net_ret_marcado
        r_sombra_c = (net_c / risk_frac) if net_c is not None else None
        r_sombra_d = (net_d / risk_frac) if net_d is not None else None

    return TradeV3(
        token=token, mint=mint, pool=pool, tf=tf, origem=origem, t_entrada=t_entrada,
        entry_price=entry_price, entry_price_corrigido=entry_corrigido,
        entrada_atrasada_corrigida=entrada_atrasada_corrigida, risk_frac=risk_frac,
        volume_entrada=volume_entrada, volume_medio_24h=volume_medio_24h, n_pavios=n_pavios,
        supply=supply, liquidez_usd=liquidez_usd,
        status_72h=r72.status, r_72h=r72.r_mult, r_regra=r_regra, r_7d=r7d.r_mult,
        r_sombra_c=r_sombra_c, r_sombra_d=r_sombra_d,
    )


def _ts_desde(desde: Optional[str]) -> Optional[float]:
    if desde is None:
        return None
    dt = datetime.strptime(desde, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def carregar_ao_vivo(storage: Storage, desde: Optional[str], now: float) -> list[TradeV3]:
    params = load_params_v3()
    costs = CostModel()
    desde_ts = _ts_desde(desde)
    trades: list[TradeV3] = []
    bars_cache: dict[str, list[Bar]] = {}
    for sinal in storage.pr3_signals():
        if sinal["evento"] != "ENTRADA":
            continue
        if sinal["stop"] is None or sinal["topo"] is None or sinal["entry_price"] is None:
            continue
        traj = storage.pr_trajetoria_get("v3", sinal["id"])
        if traj is None or traj["t_entrada"] is None:
            continue
        if desde_ts is not None and traj["t_entrada"] < desde_ts:
            continue
        tf = sinal["tf"] or params.timeframes[0]
        bars = bars_cache.setdefault(f"{sinal['pool']}|{tf}", [Bar(*row) for row in storage.pr_bars(sinal["pool"], tf)])
        j0 = None
        for idx, bar in enumerate(bars):
            if bar.ts == traj["t_entrada"]:
                j0 = idx
                break
        if j0 is None or j0 <= 0:
            continue
        pool_row = storage.pr_pool(sinal["pool"])
        l_bc = pool_row["l_bc"] if pool_row is not None else None
        dex = sinal["dex"] or "desconhecido"
        ev = EventV1(kind="ENTRADA", idx=j0 - 1, ts=bars[j0 - 1].ts, decision_ts=bars[j0 - 1].ts,
                     data={"stop": sinal["stop"], "TOPO": sinal["topo"], "S": sinal["s_suporte"],
                          "R": sinal["r_resistencia"], "n_testes": sinal["n_pavios"]})
        tags = json.loads(sinal["tags"] or "[]")
        trade = _montar_trade(bars, ev, params, costs, dex, l_bc, "ao_vivo",
                              sinal["symbol"] or (sinal["mint"] or "")[:8], sinal["mint"] or "", sinal["pool"],
                              tf, now, ts_alerta=sinal["ts_alerta"], entrada_atrasada="entrada_atrasada" in tags,
                              supply=pool_row["supply"] if pool_row is not None else None,
                              liquidez_usd=sinal["liquidez_usd"])
        if trade is not None:
            trades.append(trade)
    return sorted(trades, key=lambda t: t.t_entrada)


def carregar_retro_lote1(db_path: Path, now: float) -> list[TradeV3]:
    con = _conectar_ro(db_path)
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "pr_retro_candidatos" not in tabelas:
            return []
        params = load_params_v3()
        costs = CostModel()
        candidatos = con.execute(
            "SELECT pool, symbol, launchpad, grad_ts, criado_ts FROM pr_retro_candidatos").fetchall()
        from ..pos_runner.detector_v1 import DetectorV1
        from .exit_lab import _bars_truncados
        trades: list[TradeV3] = []
        for row in candidatos:
            pool_row = con.execute("SELECT added_ts, l_bc, launchpad, supply FROM pr_pools WHERE pool=?",
                                   (row["pool"],)).fetchone()
            if pool_row is None or pool_row["added_ts"] is None or pool_row["l_bc"] is None:
                continue
            tf = params.timeframes[0]
            step = tf_seconds(tf)
            bars = _bars_truncados(con, row["pool"], tf, step, pool_row["added_ts"])
            if not bars:
                continue
            det = DetectorV1(params, tf, pool_row["l_bc"], row["grad_ts"], row["criado_ts"])
            dex = pool_row["launchpad"] or row["launchpad"] or "desconhecido"
            for bar in bars:
                for ev in det.update(bar):
                    if ev.kind != "ENTRADA":
                        continue
                    trade = _montar_trade(bars, ev, params, costs, dex, pool_row["l_bc"], "retro_lote1",
                                          row["symbol"] or row["pool"][:8], "", row["pool"], tf, now,
                                          supply=pool_row["supply"])
                    if trade is not None:
                        trades.append(trade)
        return sorted(trades, key=lambda t: t.t_entrada)
    finally:
        con.close()


def carregar_replay_v3(db_path: Path, now: float) -> list[TradeV3]:
    con = _conectar_ro(db_path)
    try:
        params = load_params_v3()
        linhas_pool = parte_a_pools_admitidos(con, params)
        supply_por_pool = {r["pool"]: r["supply"] for r in con.execute("SELECT pool, supply FROM pr_pools")}
    finally:
        con.close()
    costs = CostModel()
    trades: list[TradeV3] = []
    for lp in linhas_pool:
        for bars, ev, dex, l_bc in lp["eventos_raw"]:
            trade = _montar_trade(bars, ev, params, costs, dex, l_bc, "v3_replay",
                                  lp["symbol"], "", lp["pool"], params.timeframes[0], now,
                                  supply=supply_por_pool.get(lp["pool"]))
            if trade is not None:
                trades.append(trade)
    return sorted(trades, key=lambda t: t.t_entrada)


# ---------------------------------------------------------------------------
# tamanho de posicao -- PEDIDO 2026-11-05 (revisao do item 3): FRACAO FIXA do capital (nao mais
# risco fixo), 4 regras FIXAS decididas ANTES de ver qualquer resultado, nunca otimizadas; so
# informacao disponivel NA ENTRADA (volume/n_pavios). Tetos aplicados DEPOIS da fracao base, em
# `_tamanho_com_tetos`.
# ---------------------------------------------------------------------------

REGRAS_TAMANHO: tuple[str, ...] = ("T10", "T20", "T30", "T_qualidade")


def _fracao_base(nome_regra: str, trade: "TradeV3") -> float:
    """Fracao do capital TOTAL (caixa livre + principal travado em posicoes abertas, sem contar
    lucro/perda nao realizado) ANTES de qualquer teto. T10/T20/T30 = fracao fixa; T_qualidade = 10%
    base, 20% so quando volume do candle de entrada >= 2x a media das 24h anteriores E n_pavios==3
    (MESMA covariavel/condicao da revisao anterior, nunca re-tunada)."""
    if nome_regra == "T10":
        return 0.10
    if nome_regra == "T20":
        return 0.20
    if nome_regra == "T30":
        return 0.30
    if nome_regra == "T_qualidade":
        if (trade.volume_entrada is not None and trade.volume_medio_24h
                and trade.volume_entrada >= 2.0 * trade.volume_medio_24h and trade.n_pavios == 3):
            return 0.20
        return 0.10
    raise ValueError(f"regra de tamanho desconhecida: {nome_regra}")


def _tamanho_com_tetos(nome_regra: str, capital_total: float, capital_livre: float, trade: "TradeV3",
                       max_liquidez_pct: float) -> tuple[float, float]:
    """Devolve (tamanho_final_usd, tamanho_desejado_usd_antes_dos_tetos). Tetos, nesta ordem: (1)
    exposicao total <=100% do capital (nunca mais que o caixa LIVRE, que so conta saldo realizado);
    (2) <=1,5% do supply do token (`pr_pools.supply` x `entry_price`; sem supply conhecido, nunca
    aplica); (3) <=`max_liquidez_pct`% da liquidez do pool (`liquidez_usd`; sempre None pra V3 hoje,
    documentado no modulo -- nunca aplica na pratica agora, mas o teto ja existe pronto)."""
    desejado = _fracao_base(nome_regra, trade) * capital_total
    tamanho = min(desejado, capital_livre)
    if trade.supply and trade.entry_price:
        tamanho = min(tamanho, (PCT_SUPPLY_MAX / 100.0) * trade.supply * trade.entry_price)
    if trade.liquidez_usd:
        tamanho = min(tamanho, (max_liquidez_pct / 100.0) * trade.liquidez_usd)
    return max(tamanho, 0.0), desejado


# ---------------------------------------------------------------------------
# estresse de custo -- slippage (R) + custo fixo (US$) + slippage extra p/ volume baixo na entrada
# ---------------------------------------------------------------------------


def _slippage_extra_volume_baixo_r(trade: TradeV3) -> float:
    """PEDIDO 2026-11-05 (item 4, formula documentada): entradas com volume do candle de entrada <
    25% da media horaria das 24h antes sofrem slippage extra proporcional -- escala LINEAR de 0 (no
    limiar, 25%) a `SLIPPAGE_EXTRA_R_MAX`=0,10R (volume=0). Sem dado de volume medio -> 0 (nunca
    inventa penalidade)."""
    if trade.volume_entrada is None or not trade.volume_medio_24h:
        return 0.0
    limiar = VOLUME_BAIXO_FRAC * trade.volume_medio_24h
    if trade.volume_entrada >= limiar or limiar <= 0:
        return 0.0
    return SLIPPAGE_EXTRA_R_MAX * (1.0 - trade.volume_entrada / limiar)


# ---------------------------------------------------------------------------
# carteira -- 1 ledger por (origem valida p/ carteira, regra de tamanho, variante de custo)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResultadoCarteira:
    origem: str
    regra_tamanho: str
    slippage_variante: str
    custo_fixo_variante: str
    capital_inicial: float
    capital_final: float
    retorno_total_pct: float
    max_drawdown_pct: float
    maior_sequencia_perdas: int
    n_trades: int
    n_tokens: int
    r_medio: Optional[float]
    r_mediano: Optional[float]
    fracao_top3_pct: Optional[float]
    resultado_sem_top3_usd: Optional[float]
    ic90_bootstrap: Optional[tuple[float, float]]
    curva_capital: list[tuple[float, float]]  # (ts_liberacao, capital_apos) -- SO saldo realizado
    n_pulados_sem_vaga: int
    n_pulados_sem_capital: int
    n_entradas_reduzidas: int   # entrou, mas menor que a fracao desejada (teto de capital/supply/liquidez)
    custo_fixo_r_medio: Optional[float]      # custo fixo convertido em R, medio sobre os trades entrados
    slippage_r_medio: Optional[float]        # slippage (base + extra de volume) em R, medio
    ponto_equilibrio_custo_fixo_usd: Optional[float]   # custo fixo US$ que zeraria o R medio
    prob_ruina_pct: Optional[float]          # P(capital < LIMITE_RUINA_USD em algum ponto), bootstrap


def _fracao_top3_pct(resultados_usd: list[float]) -> Optional[float]:
    soma = sum(resultados_usd)
    if abs(soma) < 1e-9:
        return None
    top3 = sum(sorted(resultados_usd, reverse=True)[:3])
    return 100.0 * top3 / soma


def _bootstrap_ic_por_token(valores_por_token: dict[str, list[float]], confianca: float = CONFIANCA_H1,
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


def _executar_ledger(
    trades: list[TradeV3], regra_tamanho: str, slippage_nome: str, custo_fixo_nome: str,
    capital_inicial: float, max_posicoes: int, max_liquidez_pct: float,
) -> dict[str, Any]:
    """Motor do ledger, compartilhado por `simular_carteira` e `probabilidade_ruina_bootstrap` (nunca
    duplicado). Capital so muda quando uma posicao LIBERA (principal + resultado, no seu proprio
    t_entrada+72h) -- nunca no instante da entrada (corrige o lapso da 1a versao deste script, que
    creditava o resultado cedo demais). Tamanho = fracao fixa do capital TOTAL (caixa livre +
    principal travado em posicoes abertas, nunca contando lucro/perda nao realizado), com tetos de
    exposicao/supply/liquidez; quando o caixa LIVRE nao permite o tamanho desejado, entra MENOR
    (nunca pula so por isso); pula (e conta) so quando nao ha vaga ou o caixa livre e ~0."""
    slippage_r = SLIPPAGE_VARIANTES[slippage_nome]
    custo_fixo = CUSTO_FIXO_VARIANTES[custo_fixo_nome]
    capital = capital_inicial
    peak = capital_inicial
    capital_minimo = capital_inicial
    max_dd_pct = 0.0
    sequencia_perdas = 0
    maior_sequencia_perdas = 0
    posicoes_abertas: list[list[float]] = []   # [ts_libera, tamanho_usd, resultado_usd]
    curva: list[tuple[float, float]] = []
    resultados_usd: list[float] = []
    r_valores: list[float] = []
    r_sem_custo_fixo_valores: list[float] = []
    slippage_r_valores: list[float] = []
    inverso_tamanho_risk: list[float] = []
    por_token: dict[str, list[float]] = {}
    tokens: set[str] = set()
    n_pulados_sem_vaga = 0
    n_pulados_sem_capital = 0
    n_entradas_reduzidas = 0

    def liberar(ts_ref: float) -> None:
        nonlocal capital, peak, max_dd_pct, capital_minimo, sequencia_perdas, maior_sequencia_perdas
        liberadas = sorted((p for p in posicoes_abertas if p[0] <= ts_ref), key=lambda p: p[0])
        for pos in liberadas:
            posicoes_abertas.remove(pos)
            capital += pos[1] + pos[2]
            curva.append((pos[0], capital))
            peak = max(peak, capital)
            capital_minimo = min(capital_minimo, capital)
            dd_pct = 100.0 * (peak - capital) / peak if peak > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd_pct)
            if pos[2] < 0:
                sequencia_perdas += 1
                maior_sequencia_perdas = max(maior_sequencia_perdas, sequencia_perdas)
            else:
                sequencia_perdas = 0

    for trade in trades:
        liberar(trade.t_entrada)
        if trade.status_72h == "pendente":
            continue   # horizonte ainda nao decorreu -- nunca excluido do relatorio, so sem $/R ainda
        if trade.status_72h == "sem_dado" or trade.r_72h is None:
            continue   # entrada nunca valida -- nunca um trade de verdade (nem pra carteira nem pra R)
        if len(posicoes_abertas) >= max_posicoes:
            n_pulados_sem_vaga += 1
            continue
        risk_frac = trade.risk_frac or 0.0
        if risk_frac <= 0:
            continue
        exposto = sum(p[1] for p in posicoes_abertas)
        capital_total = capital + exposto   # base da fracao: caixa livre + principal travado, SEM PnL nao realizado
        # `capital` (caixa livre) ja esta liquido de qualquer principal travado -- usado direto como
        # teto de exposicao (nunca soma mais que 100% do capital).
        tamanho_usd, desejado_usd = _tamanho_com_tetos(regra_tamanho, capital_total, capital, trade, max_liquidez_pct)
        if tamanho_usd <= 0.01:
            n_pulados_sem_capital += 1
            continue
        if tamanho_usd < desejado_usd - 1e-9:
            n_entradas_reduzidas += 1
        slippage_total_r = slippage_r + _slippage_extra_volume_baixo_r(trade)
        r_sem_custo_fixo = trade.r_72h - slippage_total_r
        custo_fixo_r = custo_fixo / (tamanho_usd * risk_frac)
        r_final = r_sem_custo_fixo - custo_fixo_r
        resultado_usd = tamanho_usd * r_final * risk_frac
        capital -= tamanho_usd   # PEDIDO 2026-11-05: o principal fica travado (nunca disponivel pra
                                 # outra entrada) at'e a LIBERACAO devolver principal+resultado.
        posicoes_abertas.append([trade.t_entrada + HORIZONTES_S["72h"], tamanho_usd, resultado_usd])
        resultados_usd.append(resultado_usd)
        r_valores.append(r_final)
        r_sem_custo_fixo_valores.append(r_sem_custo_fixo)
        slippage_r_valores.append(slippage_total_r)
        inverso_tamanho_risk.append(1.0 / (tamanho_usd * risk_frac))
        por_token.setdefault(trade.token, []).append(r_final)
        tokens.add(trade.token)
    liberar(float("inf"))   # realiza o que sobrou, pro capital/drawdown finais ficarem corretos

    return dict(
        capital_final=capital, capital_minimo=capital_minimo, max_dd_pct=max_dd_pct,
        maior_sequencia_perdas=maior_sequencia_perdas, resultados_usd=resultados_usd, r_valores=r_valores,
        r_sem_custo_fixo_valores=r_sem_custo_fixo_valores, slippage_r_valores=slippage_r_valores,
        inverso_tamanho_risk=inverso_tamanho_risk, por_token=por_token, tokens=tokens, curva=curva,
        n_pulados_sem_vaga=n_pulados_sem_vaga, n_pulados_sem_capital=n_pulados_sem_capital,
        n_entradas_reduzidas=n_entradas_reduzidas,
    )


def probabilidade_ruina_bootstrap(
    trades: list[TradeV3], regra_tamanho: str, slippage_nome: str, custo_fixo_nome: str,
    capital_inicial: float = CAPITAL_INICIAL_USD, max_posicoes: int = MAX_POSICOES_PADRAO,
    max_liquidez_pct: float = MAX_LIQUIDEZ_PCT_PADRAO, limite_ruina: float = LIMITE_RUINA_USD,
    n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO,
) -> Optional[float]:
    """PEDIDO 2026-11-05 (item 5): P(a banca cai abaixo de `limite_ruina` em algum ponto), bootstrap
    por TOKEN (blocos -- preserva a correlacao entre trades do mesmo token, MESMO metodo do resto do
    projeto). Cada reamostra roda o MESMO ledger (`_executar_ledger`) do zero sobre uma linha do
    TEMPO SINTETICA (os blocos sorteados sao CONCATENADOS em sequencia, preservando a ordem interna
    de cada token -- nunca a data real): sortear o MESMO token >1x e normal em bootstrap por bloco, e
    sem isso ele colidiria no mesmo `t_entrada` da amostra original, abrindo posicoes "simultaneas"
    que nunca existiram de verdade -- e exatamente o artefato que a linha sintetica evita."""
    elegiveis = [t for t in trades if t.status_72h not in ("pendente", "sem_dado") and t.r_72h is not None]
    por_token: dict[str, list[TradeV3]] = {}
    for t in elegiveis:
        por_token.setdefault(t.token, []).append(t)
    chaves = sorted(por_token)
    n = len(chaves)
    if n == 0:
        return None
    passo_sintetico = HORIZONTES_S["72h"] + 1.0
    rng = np.random.default_rng(seed)
    ruinas = 0
    for _ in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        amostra = []
        t_sintetico = 0.0
        for idx in escolhidos:
            for t in sorted(por_token[chaves[idx]], key=lambda t: t.t_entrada):
                amostra.append(dataclasses.replace(t, t_entrada=t_sintetico))
                t_sintetico += passo_sintetico
        resultado = _executar_ledger(amostra, regra_tamanho, slippage_nome, custo_fixo_nome, capital_inicial,
                                     max_posicoes, max_liquidez_pct)
        if resultado["capital_minimo"] < limite_ruina:
            ruinas += 1
    return 100.0 * ruinas / n_bootstrap


def simular_carteira(
    trades: list[TradeV3], origem: str, regra_tamanho: str, slippage_nome: str, custo_fixo_nome: str,
    capital_inicial: float = CAPITAL_INICIAL_USD, max_posicoes: int = MAX_POSICOES_PADRAO,
    max_liquidez_pct: float = MAX_LIQUIDEZ_PCT_PADRAO, calcular_ruina: bool = True,
) -> ResultadoCarteira:
    """1 ledger cronologico. Desfecho PRIMARIO = R marcado a mercado em 72h (`status_72h`/`r_72h`) --
    `pendente` NUNCA conta como perda, so fica fora da amostra ainda. `calcular_ruina=False` pula o
    bootstrap de ruina (10k reamostras) -- usado pelos testes/combos auxiliares pra nao pagar o custo
    36x no relatorio completo; o relatorio principal sempre calcula."""
    r = _executar_ledger(trades, regra_tamanho, slippage_nome, custo_fixo_nome, capital_inicial,
                         max_posicoes, max_liquidez_pct)
    resultados_usd, r_valores = r["resultados_usd"], r["r_valores"]
    r_mediano = statistics.median(r_valores) if r_valores else None
    r_medio = statistics.fmean(r_valores) if r_valores else None
    custo_fixo = CUSTO_FIXO_VARIANTES[custo_fixo_nome]
    sem_top3_usd = None
    if len(resultados_usd) > 3:
        top3_idx = sorted(range(len(resultados_usd)), key=lambda i: resultados_usd[i], reverse=True)[:3]
        sem_top3_usd = sum(v for i, v in enumerate(resultados_usd) if i not in top3_idx)
    media_inv = statistics.fmean(r["inverso_tamanho_risk"]) if r["inverso_tamanho_risk"] else None
    media_r_sem_custo = statistics.fmean(r["r_sem_custo_fixo_valores"]) if r["r_sem_custo_fixo_valores"] else None
    ponto_equilibrio = (media_r_sem_custo / media_inv) if (media_inv and media_r_sem_custo is not None) else None
    prob_ruina = probabilidade_ruina_bootstrap(trades, regra_tamanho, slippage_nome, custo_fixo_nome,
                                               capital_inicial, max_posicoes, max_liquidez_pct) \
        if calcular_ruina else None
    return ResultadoCarteira(
        origem=origem, regra_tamanho=regra_tamanho, slippage_variante=slippage_nome,
        custo_fixo_variante=custo_fixo_nome, capital_inicial=capital_inicial, capital_final=r["capital_final"],
        retorno_total_pct=100.0 * (r["capital_final"] - capital_inicial) / capital_inicial,
        max_drawdown_pct=r["max_dd_pct"], maior_sequencia_perdas=r["maior_sequencia_perdas"],
        n_trades=len(resultados_usd), n_tokens=len(r["tokens"]), r_medio=r_medio, r_mediano=r_mediano,
        fracao_top3_pct=_fracao_top3_pct(resultados_usd) if resultados_usd else None,
        resultado_sem_top3_usd=sem_top3_usd, ic90_bootstrap=_bootstrap_ic_por_token(r["por_token"]),
        curva_capital=r["curva"], n_pulados_sem_vaga=r["n_pulados_sem_vaga"],
        n_pulados_sem_capital=r["n_pulados_sem_capital"], n_entradas_reduzidas=r["n_entradas_reduzidas"],
        custo_fixo_r_medio=(custo_fixo * media_inv) if media_inv is not None else None,
        slippage_r_medio=statistics.fmean(r["slippage_r_valores"]) if r["slippage_r_valores"] else None,
        ponto_equilibrio_custo_fixo_usd=ponto_equilibrio, prob_ruina_pct=prob_ruina,
    )


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _resumo_amostra(trades: list[TradeV3], titulo: str) -> list[str]:
    n_abertos_pendentes = sum(1 for t in trades if t.status_72h == "pendente")
    resolvidos = [t for t in trades if t.status_72h != "pendente"]
    n_corrigidos = sum(1 for t in trades if t.entry_price_corrigido)
    n_atraso_corrigido = sum(1 for t in trades if t.entrada_atrasada_corrigida)
    out = [f"## {titulo}", "",
          f"n total: {len(trades)} | pendentes de 72h (fora de qualquer media/carteira, nunca "
          f"descartados): {n_abertos_pendentes} | com desfecho em 72h: {len(resolvidos)}",
          f"entrada corrigida por candle corrompido: {n_corrigidos} | entrada corrigida por latencia "
          f"(entrada_atrasada): {n_atraso_corrigido}", ""]
    if trades:
        primeiro, ultimo = trades[0], trades[-1]
        out.append(f"janela cronologica: {datetime.fromtimestamp(primeiro.t_entrada, tz=timezone.utc):%Y-%m-%d} "
                  f"a {datetime.fromtimestamp(ultimo.t_entrada, tz=timezone.utc):%Y-%m-%d}")
    rs = [t.r_72h for t in resolvidos if t.r_72h is not None]
    if rs:
        out.append(f"R primario (72h): media={statistics.fmean(rs):+.2f} | mediana={statistics.median(rs):+.2f} "
                  f"(n={len(rs)})")
    out.append("")
    return out


def _resumo_carteira(r: ResultadoCarteira) -> str:
    ic_txt = f"[{r.ic90_bootstrap[0]:+.2f}R, {r.ic90_bootstrap[1]:+.2f}R]" if r.ic90_bootstrap else "s/d"
    frac_txt = f"{r.fracao_top3_pct:+.0f}%" if r.fracao_top3_pct is not None else "s/d"
    sem_top3_txt = f"US${r.resultado_sem_top3_usd:+.2f}" if r.resultado_sem_top3_usd is not None else "s/d"
    custo_r_txt = f"{r.custo_fixo_r_medio:+.3f}R" if r.custo_fixo_r_medio is not None else "s/d"
    slip_r_txt = f"{r.slippage_r_medio:+.3f}R" if r.slippage_r_medio is not None else "s/d"
    equilibrio_txt = f"US${r.ponto_equilibrio_custo_fixo_usd:.2f}" if r.ponto_equilibrio_custo_fixo_usd is not None else "s/d"
    ruina_txt = f"{r.prob_ruina_pct:.1f}%" if r.prob_ruina_pct is not None else "s/d"
    linha1 = (f"  [{r.regra_tamanho} | slippage {r.slippage_variante} | custo fixo {r.custo_fixo_variante}] "
             f"capital US${r.capital_inicial:.0f}->US${r.capital_final:.2f} ({r.retorno_total_pct:+.1f}%) | "
             f"max drawdown {r.max_drawdown_pct:.1f}% | maior sequencia de perdas {r.maior_sequencia_perdas} | "
             f"n={r.n_trades} ({r.n_tokens} tokens) | pulados sem vaga={r.n_pulados_sem_vaga} sem "
             f"capital={r.n_pulados_sem_capital} | entradas reduzidas={r.n_entradas_reduzidas}")
    linha2 = (f"    R medio={r.r_medio and f'{r.r_medio:+.2f}'} mediano={r.r_mediano and f'{r.r_mediano:+.2f}'} | "
             f"top-3={frac_txt} | sem top-3={sem_top3_txt} | IC90% bootstrap={ic_txt} | custo fixo em "
             f"R={custo_r_txt} | slippage em R={slip_r_txt} | ponto de equilibrio (custo fixo)={equilibrio_txt} | "
             f"P(banca<US${LIMITE_RUINA_USD:.0f})={ruina_txt}")
    return linha1 + "\n" + linha2


def relatorio(ao_vivo: list[TradeV3], retro: list[TradeV3], replay: list[TradeV3],
             max_posicoes: int = MAX_POSICOES_PADRAO, max_liquidez_pct: float = MAX_LIQUIDEZ_PCT_PADRAO) -> str:
    out = ["# simular_v3_carteira -- carteira $100 sobre sinais V3", "", f"AVISO: {AVISO}", ""]
    out.extend(_resumo_amostra(ao_vivo, "ao_vivo (V3)"))
    out.extend(_resumo_amostra(retro, "retro_lote1 (V3, amostra dentro da amostra)"))
    out.extend(_resumo_amostra(replay, "replay_v3 (EXPLORATORIO, amostra dentro da amostra)"))
    out.append("## Carteira $100 (SO ao_vivo -- retro/replay sao hipoteticos, sem carteira propria)")
    out.append(f"tetos: {PCT_SUPPLY_MAX}% do supply | {max_liquidez_pct}% da liquidez do pool | max "
              f"{max_posicoes} posicoes simultaneas | exposicao total <=100% do capital")
    out.append("")
    for regra in REGRAS_TAMANHO:
        for slippage_nome in SLIPPAGE_VARIANTES:
            for custo_fixo_nome in CUSTO_FIXO_VARIANTES:
                r = simular_carteira(ao_vivo, "ao_vivo", regra, slippage_nome, custo_fixo_nome,
                                     max_posicoes=max_posicoes, max_liquidez_pct=max_liquidez_pct)
                out.append(_resumo_carteira(r))
    out.append("")
    out.append(f"({AVISO})")
    return "\n".join(out)


def executar(db_path: Path, desde: Optional[str] = None, max_posicoes: int = MAX_POSICOES_PADRAO,
            max_liquidez_pct: float = MAX_LIQUIDEZ_PCT_PADRAO) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    now = time.time()
    try:
        ao_vivo = carregar_ao_vivo(storage, desde, now)
    finally:
        storage.close()
    retro = carregar_retro_lote1(db_path, now)
    replay = carregar_replay_v3(db_path, now)
    return relatorio(ao_vivo, retro, replay, max_posicoes=max_posicoes, max_liquidez_pct=max_liquidez_pct)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulacao de carteira $100 sobre sinais V3 -- PAPER/so leitura/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--desde", default=None, help="AAAA-MM-DD -- reexecuta so a partir desta data (ao_vivo)")
    parser.add_argument("--max-posicoes", type=int, default=MAX_POSICOES_PADRAO)
    parser.add_argument("--max-liquidez-pct", type=float, default=MAX_LIQUIDEZ_PCT_PADRAO,
                        help="teto: posicao nunca > X%% da liquidez do pool (liquidez_usd)")
    args = parser.parse_args(argv)
    print(executar(args.db, desde=args.desde, max_posicoes=args.max_posicoes,
                  max_liquidez_pct=args.max_liquidez_pct))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
