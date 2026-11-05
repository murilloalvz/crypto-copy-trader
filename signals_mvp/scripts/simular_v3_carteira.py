"""PEDIDO 2026-11-05 (autorizado, 3a rodada): simulacao de carteira sobre os sinais V3, SOMENTE
LEITURA (zero chamada de rede, zero escrita em qualquer tabela). PAPER/READ-ONLY. V3 roda com
ParamsV3 CONGELADO (`56762db29cd6`) -- este script NUNCA altera detector/simulate/parametros/H1/
criterios de sinal. EXPLORATORIO: os numeros aqui NUNCA constituem evidencia de edge (isso exige
H1/pre-registro formal, `analise/condicional.py`) -- este script e sobre EXECUCAO/CUSTO/TAMANHO DE
POSICAO, nunca sobre se o sinal "funciona".

Regras novas de saida (ex.: vender no power candle descomunal) NAO sao aplicadas aqui -- se
autorizadas no futuro, entram como "V4-candidata EXPLORATORIA" (rotulada, script separado), nunca
misturadas a V3.

ESCOPO/SIMPLIFICACOES DESTA RODADA (documentadas, nunca escondidas):
- "nº de pavios" usa a covariavel JA existente `n_pavios`/`ev.data["n_testes"]` (quantidade de
  testes de suporte detectados pelo detector V3). "volume do candle de GATILHO" = `bars[ev.idx]`
  (candle que disparou a ENTRADA); "volume do candle de ENTRADA" = `bars[j0]` (candle de execucao,
  open seguinte) -- os dois sao comparados contra a MESMA media das 24h antes da entrada
  (`volume_medio_24h`, simplificacao: nao recalcula uma janela separada pro gatilho, que e so 1
  candle antes). V_oportunidade e MINHA formula documentada (o pedido deu exemplo), nunca otimizada.
- teto de supply usa `pr_pools.supply` (ja gravado via lineage on-chain) x `entry_price` -- sem
  supply conhecido, o teto nao se aplica (nunca inventa supply). Teto de volume usa o volume (USD --
  `pr_bars` ja e MC/volume em USD, `pos_runner/quotes.py: to_mc_bars`) do PROPRIO candle de entrada
  -- `--max-volume-pct` (padrao 10%, minha escolha documentada: participacao maxima razoavel num
  candle de 1h de um token novo, nunca otimizada).
- impacto de preco extra = `IMPACT_COEF_R` (1.0, minha escolha documentada) x (posicao/volume do
  candle de entrada) -- formula LINEAR simples (o pedido so exigiu proporcionalidade, nunca uma
  curva especifica); ocupar 100% do volume do candle custa 1R extra. Sem volume conhecido -> 0.
- corrigir "preco de entrada apos a latencia medida" usa `ts_alerta`/`alert_ts` (ja gravados) pra
  achar o 1o candle que o bot podia realmente agir, quando a tag `entrada_atrasada` esta presente;
  sem esses campos, cai no candle de execucao padrao (bars[j0].open), sinalizado.
- carteira roda para as 3 origens (ao_vivo/retro_lote1/replay_v3), cada uma com sua PROPRIA banca
  independente (nunca somadas/misturadas) -- retro_lote1/replay_v3 sao HIPOTETICOS por natureza
  (nunca posicoes reais que concorreriam por capital de verdade), rotulados em toda saida.
- tamanho agora e VALOR ABSOLUTO (nao fracao do capital nem risco) -- banca "livre" so conta saldo
  JA REALIZADO; uma posicao aberta debita seu tamanho da banca no instante da ENTRADA e so devolve
  principal+resultado na LIBERACAO (`t_entrada+72h`) -- nunca antes (sem reinvestir lucro nao
  realizado, sem contar 2x o principal travado).
- probabilidade de ruina: bootstrap por token sobre uma linha do TEMPO SINTETICA (blocos
  concatenados em sequencia, nunca a data real -- evita que sortear o mesmo token >1x crie posicoes
  "simultaneas" que nunca existiram). Limiar agora e RELATIVO (banca cair abaixo de
  `FRACAO_RUINA`=50% do valor INICIAL daquele cenario, nunca um US$ fixo, ja que a banca varia por
  cenario).

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.simular_v3_carteira --db signals_mvp/dados/estado.sqlite
    python -m signals_mvp.scripts.simular_v3_carteira --db ... --banca 500 --desde 2026-10-01
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
SLIPPAGE_VARIANTES: dict[str, float] = {"base": 0.0, "+0.1R": 0.1, "+0.3R": 0.3}
CUSTO_FIXO_VARIANTES: dict[str, float] = {"US$0.05": 0.05, "US$0.15": 0.15, "US$0.30": 0.30}
BANCA_CENARIOS_PADRAO: tuple[float, ...] = (250.0, 500.0, 1000.0)
VALOR_MINIMO_USD = 10.0
MAX_POSICOES_PADRAO = 4
PCT_SUPPLY_MAX = 1.5             # teto fixo: posicao nunca > 1,5% do supply total do token
MAX_VOLUME_PCT_PADRAO = 10.0     # teto parametrizavel: posicao nunca > X% do volume do candle de entrada
IMPACT_COEF_R = 1.0              # impacto de preco = IMPACT_COEF_R x (posicao/volume do candle de entrada)
FRACAO_RUINA = 0.5               # P(banca cair abaixo de 50% do valor INICIAL daquele cenario)
MAX_PERDA_FRAC = 1.0             # PEDIDO 2026-11-05 (A1): spot, SEM alavancagem -- uma posicao nunca
                                 # perde mais que 100% do seu proprio principal, mesmo quando o R
                                 # marcado a mercado (`r_72h`) e muito negativo (ex.: token que caiu
                                 # 95% pode marcar -20R; sem este teto, `resultado_usd` ficava MAIOR
                                 # em modulo que o proprio `tamanho_usd` investido -- bug real, nao
                                 # so um limiar de seguranca).
MAX_POSICOES_SENSIBILIDADE: tuple[int, ...] = (10, 25)   # A4: comparar com o teto configurado


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
    volume_gatilho: Optional[float]    # volume do candle que disparou a ENTRADA (bars[ev.idx])
    volume_entrada: Optional[float]    # volume do candle de execucao (bars[j0])
    volume_medio_24h: Optional[float]
    n_pavios: Optional[int]
    supply: Optional[float]
    # desfechos -- PRIMARIO = R marcado a mercado em 72h; secundarios = regra e 7d.
    status_72h: str
    r_72h: Optional[float]
    r_regra: Optional[float]
    r_7d: Optional[float]
    # sombra exploratoria (C/D), nunca escolhida:
    r_sombra_c: Optional[float]
    r_sombra_d: Optional[float]


def _candle_limpo_na_entrada(bars: list[Bar], j0: int) -> tuple[float, bool]:
    """Candle de entrada corrompido nunca decide o preco -- usa o ultimo candle LIMPO anterior
    (`candle_corrompido_provavel`). Devolve (preco, foi_corrigido)."""
    if not candle_corrompido_provavel(bars, j0):
        return bars[j0].open, False
    for idx in range(j0 - 1, -1, -1):
        if not candle_corrompido_provavel(bars, idx):
            return bars[idx].close, True
    return bars[j0].open, True   # nenhum candle limpo antes -- usa o original, mas AVISA (contado)


def _preco_apos_latencia(bars: list[Bar], j0: int, ts_alerta: Optional[float]) -> tuple[float, int, bool]:
    """Sinal `entrada_atrasada` -- usa o preco do 1o candle cujo `ts` e >= `ts_alerta` (1o momento em
    que o bot realmente PODERIA ter agido), nunca o open retroativo do candle do gatilho. Sem
    `ts_alerta` conhecido, cai no padrao (bars[j0], sinalizado via `False`)."""
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
    ts_alerta: Optional[float] = None, entrada_atrasada: bool = False, supply: Optional[float] = None,
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
    volume_gatilho = bars[ev.idx].volume if 0 <= ev.idx < len(bars) else None
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
        volume_gatilho=volume_gatilho, volume_entrada=volume_entrada, volume_medio_24h=volume_medio_24h,
        n_pavios=n_pavios, supply=supply,
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
                              supply=pool_row["supply"] if pool_row is not None else None)
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
# tamanho de posicao -- PEDIDO 2026-11-05 (3a rodada): VALOR ABSOLUTO em US$ (nao mais fracao do
# capital nem risco), 4 regras FIXAS decididas ANTES de ver qualquer resultado, nunca otimizadas; so
# informacao disponivel NA ENTRADA (volume do gatilho/entrada, n_pavios). Tetos em `_tamanho_com_tetos`.
# ---------------------------------------------------------------------------

REGRAS_TAMANHO: tuple[str, ...] = ("V10", "V25", "V50", "V_oportunidade")


def _valor_base(nome_regra: str, trade: "TradeV3") -> float:
    """V10/V25/V50 = valor fixo em US$. V_oportunidade (minha escolha documentada, o pedido deu
    exemplo): US$10 base; US$25 quando volume do candle de GATILHO >=2x a media das 24h E
    n_pavios==3; US$50 quando, ALEM disso, o volume do candle de ENTRADA >=50% dessa mesma media."""
    if nome_regra == "V10":
        return 10.0
    if nome_regra == "V25":
        return 25.0
    if nome_regra == "V50":
        return 50.0
    if nome_regra == "V_oportunidade":
        qualidade = (trade.volume_gatilho is not None and trade.volume_medio_24h
                    and trade.volume_gatilho >= 2.0 * trade.volume_medio_24h and trade.n_pavios == 3)
        if not qualidade:
            return 10.0
        entrada_forte = (trade.volume_entrada is not None and trade.volume_medio_24h
                        and trade.volume_entrada >= 0.5 * trade.volume_medio_24h)
        return 50.0 if entrada_forte else 25.0
    raise ValueError(f"regra de tamanho desconhecida: {nome_regra}")


def _tamanho_com_tetos(nome_regra: str, banca_livre: float, trade: "TradeV3",
                       max_volume_pct: float) -> tuple[float, float, Optional[str]]:
    """Devolve (tamanho_final_usd, tamanho_desejado_usd, motivo_limitante_ou_None). Tetos, nesta
    ordem: (1) exposicao total <=100% da banca (nunca mais que `banca_livre`, que ja e liquida de
    qualquer principal travado -- ver `_executar_ledger`); (2) <=1,5% do supply do token
    (`pr_pools.supply` x `entry_price`; sem supply conhecido, nunca aplica); (3) <=`max_volume_pct`%
    do volume do candle de ENTRADA (sem volume conhecido, nunca aplica). `motivo_limitante` e o
    ULTIMO teto que apertou o tamanho -- usado por quem chama pra contar o pulado pelo motivo certo
    quando o resultado final fica abaixo de `VALOR_MINIMO_USD`."""
    desejado = _valor_base(nome_regra, trade)
    tamanho = desejado
    motivo: Optional[str] = None
    if tamanho > banca_livre:
        tamanho = banca_livre
        motivo = "sem_capital"
    if trade.supply and trade.entry_price:
        teto_supply = (PCT_SUPPLY_MAX / 100.0) * trade.supply * trade.entry_price
        if teto_supply < tamanho:
            tamanho = teto_supply
            motivo = "teto_supply"
    if trade.volume_entrada:
        teto_volume = (max_volume_pct / 100.0) * trade.volume_entrada
        if teto_volume < tamanho:
            tamanho = teto_volume
            motivo = "teto_volume"
    return max(tamanho, 0.0), desejado, motivo


def _impacto_preco_r(tamanho_usd: float, volume_entrada: Optional[float]) -> float:
    """Impacto de preco extra, proporcional a (posicao/volume do candle de entrada) -- formula
    LINEAR simples (`IMPACT_COEF_R`, minha escolha documentada, nunca otimizada): ocupar 100% do
    volume do candle custa `IMPACT_COEF_R` de R extra. Sem volume conhecido -> 0 (nunca inventa)."""
    if not volume_entrada:
        return 0.0
    return IMPACT_COEF_R * (tamanho_usd / volume_entrada)


# ---------------------------------------------------------------------------
# carteira -- 1 ledger por (origem, banca_inicial, regra de tamanho, slippage, custo fixo)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResultadoCarteira:
    origem: str
    regra_tamanho: str
    slippage_variante: str
    custo_fixo_variante: str
    banca_inicial: float
    banca_final: float
    retorno_pct: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    maior_sequencia_perdas: int
    n_trades: int
    n_tokens: int
    prob_ruina_pct: Optional[float]
    r_medio: Optional[float]
    r_mediano: Optional[float]
    r_medio_sem_top3: Optional[float]
    ic90_bootstrap: Optional[tuple[float, float]]
    ponto_equilibrio_custo_fixo_usd: Optional[float]
    custo_fixo_r_medio: Optional[float]
    slippage_r_medio: Optional[float]
    pulados_por_motivo: dict[str, int]
    n_entradas_reduzidas: int
    curva_capital: list[tuple[float, float]]


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
    banca_inicial: float, max_posicoes: int, max_volume_pct: float, uma_por_token: bool = True,
) -> dict[str, Any]:
    """Motor do ledger, compartilhado por `simular_carteira` e `probabilidade_ruina_bootstrap` (nunca
    duplicado). Banca (caixa) debita o tamanho no instante da ENTRADA (trava o principal -- nunca
    disponivel pra outra entrada) e so credita principal+resultado na LIBERACAO (`t_entrada+72h`) --
    "so saldo realizado volta ao capital" passa a valer de verdade.

    PEDIDO 2026-11-05 (A1, correcao de bug): maxDD/ruina agora usam PATRIMONIO = caixa + principal
    das posicoes AINDA abertas, valorizado A CUSTO (pelo proprio `tamanho_usd` investido -- nunca a
    mercado, porque este modelo discreto so conhece o desfecho FINAL de uma posicao no horizonte, nao
    um preco intermediario pra marcar no meio do caminho; documentado, nunca escondido). Isso corrige
    o caixa (so) subestimar o patrimonio real enquanto posicoes estao travadas, inflando artificialmente
    o drawdown. Junto, `resultado_usd` agora e TRAVADO em -100% do principal (`MAX_PERDA_FRAC`) -- uma
    posicao a vista, sem alavancagem, nunca perde mais do que investiu, mesmo quando o R marcado a
    mercado e muito negativo (ex.: -10R num token que despencou); sem este teto, o drawdown podia
    superar o capital jamais realmente exposto -- o bug relatado.

    Capital insuficiente -> entra MENOR (nunca abaixo de `VALOR_MINIMO_USD`); abaixo disso, pula e
    CONTA pelo motivo (`sem_vaga`/`sem_capital`/`teto_supply`/`teto_volume`/`token_ja_aberto` -- este
    ultimo so quando `uma_por_token=True`, PEDIDO A3: 1 posicao por TOKEN por vez na carteira real,
    nunca na varredura exploratoria da Parte B)."""
    slippage_r = SLIPPAGE_VARIANTES[slippage_nome]
    custo_fixo = CUSTO_FIXO_VARIANTES[custo_fixo_nome]
    banca = banca_inicial
    peak = banca_inicial
    patrimonio_minimo = banca_inicial
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    sequencia_perdas = 0
    maior_sequencia_perdas = 0
    posicoes_abertas: list[list[Any]] = []   # [ts_libera, tamanho_usd, resultado_usd, token]
    tokens_com_posicao_aberta: set[str] = set()
    curva: list[tuple[float, float]] = []
    resultados_usd: list[float] = []
    r_valores: list[float] = []
    r_sem_custo_fixo_valores: list[float] = []
    slippage_r_valores: list[float] = []
    inverso_tamanho_risk: list[float] = []
    por_token: dict[str, list[float]] = {}
    tokens: set[str] = set()
    pulados_por_motivo: dict[str, int] = {}
    n_entradas_reduzidas = 0

    def pular(motivo: str) -> None:
        pulados_por_motivo[motivo] = pulados_por_motivo.get(motivo, 0) + 1

    def patrimonio() -> float:
        return banca + sum(p[1] for p in posicoes_abertas)

    def marcar_equity(ts: float) -> None:
        nonlocal peak, max_dd_pct, max_dd_usd, patrimonio_minimo
        p = patrimonio()
        curva.append((ts, p))
        peak = max(peak, p)
        patrimonio_minimo = min(patrimonio_minimo, p)
        dd_usd = peak - p
        max_dd_usd = max(max_dd_usd, dd_usd)
        dd_pct = 100.0 * dd_usd / peak if peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd_pct)

    def liberar(ts_ref: float) -> None:
        nonlocal banca, sequencia_perdas, maior_sequencia_perdas
        liberadas = sorted((p for p in posicoes_abertas if p[0] <= ts_ref), key=lambda p: p[0])
        for pos in liberadas:
            posicoes_abertas.remove(pos)
            tokens_com_posicao_aberta.discard(pos[3])
            banca += pos[1] + pos[2]
            marcar_equity(pos[0])
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
        if uma_por_token and trade.token in tokens_com_posicao_aberta:
            pular("token_ja_aberto")
            continue
        if len(posicoes_abertas) >= max_posicoes:
            pular("sem_vaga")
            continue
        risk_frac = trade.risk_frac or 0.0
        if risk_frac <= 0:
            continue
        tamanho_usd, desejado_usd, motivo = _tamanho_com_tetos(regra_tamanho, banca, trade, max_volume_pct)
        if tamanho_usd < VALOR_MINIMO_USD - 1e-9:
            pular(motivo or "sem_capital")
            continue
        if tamanho_usd < desejado_usd - 1e-9:
            n_entradas_reduzidas += 1
        slippage_total_r = slippage_r + _impacto_preco_r(tamanho_usd, trade.volume_entrada)
        r_sem_custo_fixo = trade.r_72h - slippage_total_r
        custo_fixo_r = custo_fixo / (tamanho_usd * risk_frac)
        r_final = r_sem_custo_fixo - custo_fixo_r
        net_frac = max(r_final * risk_frac, -MAX_PERDA_FRAC)   # A1: nunca perde mais que o principal
        resultado_usd = tamanho_usd * net_frac
        banca -= tamanho_usd   # o principal fica travado (nunca disponivel pra outra entrada) ate a
                               # LIBERACAO devolver principal+resultado.
        posicoes_abertas.append([trade.t_entrada + HORIZONTES_S["72h"], tamanho_usd, resultado_usd, trade.token])
        tokens_com_posicao_aberta.add(trade.token)
        marcar_equity(trade.t_entrada)   # patrimonio NUNCA muda so por abrir (debito=valor investido),
                                        # mas o ponto entra na curva/peak continuamente (A1).
        resultados_usd.append(resultado_usd)
        r_valores.append(r_final)
        r_sem_custo_fixo_valores.append(r_sem_custo_fixo)
        slippage_r_valores.append(slippage_total_r)
        inverso_tamanho_risk.append(1.0 / (tamanho_usd * risk_frac))
        por_token.setdefault(trade.token, []).append(r_final)
        tokens.add(trade.token)
    liberar(float("inf"))   # realiza o que sobrou, pra banca/drawdown finais ficarem corretos

    return dict(
        banca_final=banca, banca_minima=patrimonio_minimo, max_dd_pct=max_dd_pct, max_dd_usd=max_dd_usd,
        maior_sequencia_perdas=maior_sequencia_perdas, resultados_usd=resultados_usd, r_valores=r_valores,
        r_sem_custo_fixo_valores=r_sem_custo_fixo_valores, slippage_r_valores=slippage_r_valores,
        inverso_tamanho_risk=inverso_tamanho_risk, por_token=por_token, tokens=tokens, curva=curva,
        pulados_por_motivo=pulados_por_motivo, n_entradas_reduzidas=n_entradas_reduzidas,
    )


def probabilidade_ruina_bootstrap(
    trades: list[TradeV3], regra_tamanho: str, slippage_nome: str, custo_fixo_nome: str,
    banca_inicial: float, max_posicoes: int = MAX_POSICOES_PADRAO,
    max_volume_pct: float = MAX_VOLUME_PCT_PADRAO, fracao_ruina: float = FRACAO_RUINA,
    n_bootstrap: int = N_BOOTSTRAP_PADRAO, seed: int = SEED_PADRAO, uma_por_token: bool = True,
) -> Optional[float]:
    """P(a banca cai abaixo de `fracao_ruina` x `banca_inicial` em algum ponto), bootstrap por TOKEN
    (blocos) sobre uma linha do TEMPO SINTETICA (blocos concatenados em sequencia, nunca a data real
    -- evita que sortear o mesmo token >1x crie posicoes "simultaneas" que nunca existiram)."""
    elegiveis = [t for t in trades if t.status_72h not in ("pendente", "sem_dado") and t.r_72h is not None]
    por_token: dict[str, list[TradeV3]] = {}
    for t in elegiveis:
        por_token.setdefault(t.token, []).append(t)
    chaves = sorted(por_token)
    n = len(chaves)
    if n == 0:
        return None
    limite_ruina = fracao_ruina * banca_inicial
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
        resultado = _executar_ledger(amostra, regra_tamanho, slippage_nome, custo_fixo_nome, banca_inicial,
                                     max_posicoes, max_volume_pct, uma_por_token=uma_por_token)
        if resultado["banca_minima"] < limite_ruina:
            ruinas += 1
    return 100.0 * ruinas / n_bootstrap


def simular_carteira(
    trades: list[TradeV3], origem: str, regra_tamanho: str, slippage_nome: str, custo_fixo_nome: str,
    banca_inicial: float, max_posicoes: int = MAX_POSICOES_PADRAO, max_volume_pct: float = MAX_VOLUME_PCT_PADRAO,
    calcular_ruina: bool = True, uma_por_token: bool = True,
) -> ResultadoCarteira:
    """1 ledger cronologico. Desfecho PRIMARIO = R marcado a mercado em 72h (`status_72h`/`r_72h`) --
    `pendente` NUNCA conta como perda, so fica fora da amostra ainda. `calcular_ruina=False` pula o
    bootstrap de ruina (10k reamostras) -- usado pelo grid de custo/slippage e pela sensibilidade a
    `max_posicoes` pra nao pagar o custo Nx (A5); a combinacao principal do relatorio sempre calcula."""
    r = _executar_ledger(trades, regra_tamanho, slippage_nome, custo_fixo_nome, banca_inicial,
                         max_posicoes, max_volume_pct, uma_por_token=uma_por_token)
    resultados_usd, r_valores = r["resultados_usd"], r["r_valores"]
    r_mediano = statistics.median(r_valores) if r_valores else None
    r_medio = statistics.fmean(r_valores) if r_valores else None
    r_medio_sem_top3 = None
    if len(resultados_usd) > 3:
        top3_idx = set(sorted(range(len(resultados_usd)), key=lambda i: resultados_usd[i], reverse=True)[:3])
        resto = [v for i, v in enumerate(r_valores) if i not in top3_idx]
        r_medio_sem_top3 = statistics.fmean(resto) if resto else None
    media_inv = statistics.fmean(r["inverso_tamanho_risk"]) if r["inverso_tamanho_risk"] else None
    media_r_sem_custo = statistics.fmean(r["r_sem_custo_fixo_valores"]) if r["r_sem_custo_fixo_valores"] else None
    ponto_equilibrio = (media_r_sem_custo / media_inv) if (media_inv and media_r_sem_custo is not None) else None
    custo_fixo = CUSTO_FIXO_VARIANTES[custo_fixo_nome]
    prob_ruina = probabilidade_ruina_bootstrap(trades, regra_tamanho, slippage_nome, custo_fixo_nome,
                                               banca_inicial, max_posicoes, max_volume_pct,
                                               uma_por_token=uma_por_token) \
        if calcular_ruina else None
    return ResultadoCarteira(
        origem=origem, regra_tamanho=regra_tamanho, slippage_variante=slippage_nome,
        custo_fixo_variante=custo_fixo_nome, banca_inicial=banca_inicial, banca_final=r["banca_final"],
        retorno_pct=100.0 * (r["banca_final"] - banca_inicial) / banca_inicial,
        max_drawdown_pct=r["max_dd_pct"], max_drawdown_usd=r["max_dd_usd"],
        maior_sequencia_perdas=r["maior_sequencia_perdas"], n_trades=len(resultados_usd), n_tokens=len(r["tokens"]),
        prob_ruina_pct=prob_ruina, r_medio=r_medio, r_mediano=r_mediano, r_medio_sem_top3=r_medio_sem_top3,
        ic90_bootstrap=_bootstrap_ic_por_token(r["por_token"]), ponto_equilibrio_custo_fixo_usd=ponto_equilibrio,
        custo_fixo_r_medio=(custo_fixo * media_inv) if media_inv is not None else None,
        slippage_r_medio=statistics.fmean(r["slippage_r_valores"]) if r["slippage_r_valores"] else None,
        pulados_por_motivo=r["pulados_por_motivo"], n_entradas_reduzidas=r["n_entradas_reduzidas"],
        curva_capital=r["curva"],
    )


# ---------------------------------------------------------------------------
# relatorio
# ---------------------------------------------------------------------------


def _resumo_amostra(trades: list[TradeV3], titulo: str, now: float) -> list[str]:
    pendentes = [t for t in trades if t.status_72h == "pendente"]
    resolvidos = [t for t in trades if t.status_72h != "pendente"]
    n_corrigidos = sum(1 for t in trades if t.entry_price_corrigido)
    n_atraso_corrigido = sum(1 for t in trades if t.entrada_atrasada_corrigida)
    tokens = sorted({t.token for t in trades})
    out = [f"## {titulo}", "",
          f"n total: {len(trades)} | tokens distintos: {len(tokens)} | pendentes de 72h (fora de "
          f"qualquer media/carteira, nunca descartados): {len(pendentes)} | com desfecho em 72h: "
          f"{len(resolvidos)}",
          f"entrada corrigida por candle corrompido: {n_corrigidos} | entrada corrigida por latencia "
          f"(entrada_atrasada): {n_atraso_corrigido}"]
    if pendentes:
        primeiro_completa = min(t.t_entrada + HORIZONTES_S["72h"] for t in pendentes)
        faltam_h = max(0.0, (primeiro_completa - now) / 3600.0)
        data_txt = datetime.fromtimestamp(primeiro_completa, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        out.append(f"1o sinal pendente completa 72h em: {data_txt} (faltam ~{faltam_h:.1f}h)")
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


def _resumo_criterios_oportunidade(trades: list[TradeV3]) -> list[str]:
    """PEDIDO 2026-11-05 (A2): V_oportunidade deu igual a V10 -- reporta, separado, quantos sinais
    satisfazem CADA criterio de upgrade e quantos tem os campos ausentes (nunca silencioso sobre
    dado faltante). Se nenhum sinal passa em algum criterio, diz isso explicitamente."""
    n = len(trades)
    if n == 0:
        return ["(sem sinais nesta origem para avaliar os criterios de V_oportunidade)", ""]
    sem_volume_gatilho = sum(1 for t in trades if t.volume_gatilho is None)
    sem_volume_medio = sum(1 for t in trades if t.volume_medio_24h is None)
    sem_n_pavios = sum(1 for t in trades if t.n_pavios is None)
    sem_volume_entrada = sum(1 for t in trades if t.volume_entrada is None)
    passa_volume_gatilho = sum(1 for t in trades if t.volume_gatilho is not None and t.volume_medio_24h
                               and t.volume_gatilho >= 2.0 * t.volume_medio_24h)
    passa_pavios = sum(1 for t in trades if t.n_pavios == 3)
    passa_qualidade = sum(1 for t in trades if t.volume_gatilho is not None and t.volume_medio_24h
                          and t.volume_gatilho >= 2.0 * t.volume_medio_24h and t.n_pavios == 3)
    passa_entrada_forte = sum(1 for t in trades if t.volume_entrada is not None and t.volume_medio_24h
                              and t.volume_entrada >= 0.5 * t.volume_medio_24h)
    out = [f"Criterios de V_oportunidade (n={n}):",
          f"  volume do gatilho >=2x media 24h: {passa_volume_gatilho}/{n} (sem dado: {sem_volume_gatilho})",
          f"  n_pavios==3: {passa_pavios}/{n} (sem dado: {sem_n_pavios})",
          f"  AMBOS (qualifica p/ US$25+): {passa_qualidade}/{n}",
          f"  volume de entrada >=50% media 24h: {passa_entrada_forte}/{n} (sem dado: {sem_volume_entrada})",
          f"  media 24h ausente (nenhum dos 2 criterios pode avaliar): {sem_volume_medio}/{n}"]
    if passa_qualidade == 0:
        out.append("  NENHUM sinal desta origem satisfez o criterio de qualidade -- V_oportunidade "
                  "sempre cai no US$10 base aqui (explica o resultado igual a V10).")
    out.append("")
    return out


def _resumo_overlap_tokens(ao_vivo: list[TradeV3], retro: list[TradeV3], replay: list[TradeV3]) -> list[str]:
    conjuntos = {"ao_vivo": {t.token for t in ao_vivo}, "retro_lote1": {t.token for t in retro},
                "replay_v3": {t.token for t in replay}}
    contagem: dict[str, int] = {}
    for tokens in conjuntos.values():
        for tok in tokens:
            contagem[tok] = contagem.get(tok, 0) + 1
    repetidos = sorted(tok for tok, n in contagem.items() if n > 1)
    linha = f"tokens em mais de 1 origem: {len(repetidos)}"
    if repetidos:
        linha += " (" + ", ".join(repetidos[:10]) + (", ..." if len(repetidos) > 10 else "") + ")"
    return [linha, ""]


def _formatar_tabela_carteira(resultados: list[ResultadoCarteira]) -> list[str]:
    cols = ["regra", "banca final", "retorno%", "maxDD%", "maxDD$", "seq.perdas", "trades", "tokens",
           f"P(banca<{int(100 * FRACAO_RUINA)}%)", "R medio", "R mediano", "R s/top3", "IC90% boot",
           "equilibrio($)", "pulados", "reduzidos"]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in resultados:
        ic_txt = f"[{r.ic90_bootstrap[0]:+.2f},{r.ic90_bootstrap[1]:+.2f}]" if r.ic90_bootstrap else "s/d"
        ruina_txt = f"{r.prob_ruina_pct:.1f}%" if r.prob_ruina_pct is not None else "s/d"
        equilibrio_txt = f"{r.ponto_equilibrio_custo_fixo_usd:.2f}" if r.ponto_equilibrio_custo_fixo_usd is not None else "s/d"
        pulados_total = sum(r.pulados_por_motivo.values())
        linha = [
            r.regra_tamanho, f"US${r.banca_final:.2f}", f"{r.retorno_pct:+.1f}", f"{r.max_drawdown_pct:.1f}",
            f"US${r.max_drawdown_usd:.2f}", str(r.maior_sequencia_perdas), str(r.n_trades), str(r.n_tokens),
            ruina_txt, r.r_medio and f"{r.r_medio:+.2f}" or "s/d", r.r_mediano and f"{r.r_mediano:+.2f}" or "s/d",
            r.r_medio_sem_top3 and f"{r.r_medio_sem_top3:+.2f}" or "s/d", ic_txt, equilibrio_txt,
            str(pulados_total), str(r.n_entradas_reduzidas),
        ]
        out.append("| " + " | ".join(linha) + " |")
    return out


def _formatar_detalhe_pulados(resultados: list[ResultadoCarteira]) -> list[str]:
    out = ["", "Detalhe dos pulados por motivo:"]
    for r in resultados:
        if not r.pulados_por_motivo:
            continue
        motivos_txt = ", ".join(f"{k}={v}" for k, v in sorted(r.pulados_por_motivo.items()))
        out.append(f"  {r.regra_tamanho}: {motivos_txt}")
    out.append("")
    return out


def _formatar_grid_custos(trades: list[TradeV3], banca_inicial: float, max_posicoes: int,
                          max_volume_pct: float) -> list[str]:
    out = ["Custo fixo e slippage convertidos em R (lado a lado, por regra):", ""]
    for regra in REGRAS_TAMANHO:
        out.append(f"  {regra}:")
        for slippage_nome in SLIPPAGE_VARIANTES:
            linha_vals = []
            for custo_fixo_nome in CUSTO_FIXO_VARIANTES:
                r = simular_carteira(trades, "x", regra, slippage_nome, custo_fixo_nome, banca_inicial,
                                     max_posicoes=max_posicoes, max_volume_pct=max_volume_pct,
                                     calcular_ruina=False)
                custo_txt = f"{r.custo_fixo_r_medio:+.3f}R" if r.custo_fixo_r_medio is not None else "s/d"
                linha_vals.append(f"{custo_fixo_nome}={custo_txt}")
            slip_r = SLIPPAGE_VARIANTES[slippage_nome]
            out.append(f"    slippage {slippage_nome} ({slip_r:+.1f}R base): " + " | ".join(linha_vals))
        out.append("")
    return out


PIOR_SLIPPAGE = "+0.3R"
PIOR_CUSTO_FIXO = "US$0.30"


def _formatar_sensibilidade_max_posicoes(trades: list[TradeV3], banca_inicial: float, max_volume_pct: float,
                                         max_posicoes_configurado: int) -> list[str]:
    """PEDIDO 2026-11-05 (A4): o teto de posicoes pula muitos sinais (uma posicao por token so libera
    em 72h) -- compara o configurado com 10/25, SEM bootstrap de ruina (A5, caro demais pra rodar 3x
    a mais aqui)."""
    out = ["Sensibilidade ao teto de posicoes simultaneas (slippage base, custo fixo US$0.05):", ""]
    valores = sorted({max_posicoes_configurado, *MAX_POSICOES_SENSIBILIDADE})
    for max_pos in valores:
        linhas_regra = []
        for regra in REGRAS_TAMANHO:
            r = simular_carteira(trades, "x", regra, "base", "US$0.05", banca_inicial, max_posicoes=max_pos,
                                 max_volume_pct=max_volume_pct, calcular_ruina=False)
            r_medio_txt = f"{r.r_medio:+.2f}" if r.r_medio is not None else "s/d"
            sem_top3_txt = f"{r.r_medio_sem_top3:+.2f}" if r.r_medio_sem_top3 is not None else "s/d"
            ic_txt = f"[{r.ic90_bootstrap[0]:+.2f},{r.ic90_bootstrap[1]:+.2f}]" if r.ic90_bootstrap else "s/d"
            n_sem_vaga = r.pulados_por_motivo.get("sem_vaga", 0)
            linhas_regra.append(f"{regra}: n={r.n_trades} (sem_vaga={n_sem_vaga}) R={r_medio_txt} "
                               f"sem_top3={sem_top3_txt} IC90%={ic_txt}")
        marca = " (configurado)" if max_pos == max_posicoes_configurado else ""
        out.append(f"  max_posicoes={max_pos}{marca}:")
        for linha in linhas_regra:
            out.append(f"    {linha}")
    out.append("")
    return out


def _tabela_origem_banca(trades: list[TradeV3], origem_label: str, banca_inicial: float,
                         max_posicoes: int, max_volume_pct: float) -> tuple[list[str], list[ResultadoCarteira]]:
    if not trades:
        return ([f"### {origem_label} -- banca inicial US${banca_inicial:.0f}", "",
                "(sem trades com desfecho definido ainda -- ver secao de amostra acima)", ""], [])
    resultados = [simular_carteira(trades, origem_label, regra, "base", "US$0.05", banca_inicial,
                                   max_posicoes=max_posicoes, max_volume_pct=max_volume_pct, calcular_ruina=True)
                 for regra in REGRAS_TAMANHO]
    # A4: pior cenario de custo (slippage +0,3R, custo fixo US$0,30) -- FULL stats, nunca so o R
    # convertido (ja no grid abaixo); com bootstrap de ruina (A5: so base + pior, nunca os 9 combos).
    resultados_pior = [simular_carteira(trades, origem_label, regra, PIOR_SLIPPAGE, PIOR_CUSTO_FIXO, banca_inicial,
                                        max_posicoes=max_posicoes, max_volume_pct=max_volume_pct, calcular_ruina=True)
                       for regra in REGRAS_TAMANHO]
    out = [f"### {origem_label} -- banca inicial US${banca_inicial:.0f} (slippage base, custo fixo US$0.05)", ""]
    out.extend(_formatar_tabela_carteira(resultados))
    out.extend(_formatar_detalhe_pulados(resultados))
    out.append(f"#### {origem_label} -- PIOR CENARIO DE CUSTO (slippage {PIOR_SLIPPAGE}, custo fixo "
              f"{PIOR_CUSTO_FIXO})")
    out.append("")
    out.extend(_formatar_tabela_carteira(resultados_pior))
    out.extend(_formatar_detalhe_pulados(resultados_pior))
    out.extend(_formatar_grid_custos(trades, banca_inicial, max_posicoes, max_volume_pct))
    out.extend(_formatar_sensibilidade_max_posicoes(trades, banca_inicial, max_volume_pct, max_posicoes))
    return out, resultados


def _escrever_csv(path: Path, linhas_csv: list[dict[str, Any]]) -> None:
    import csv as _csv
    if not linhas_csv:
        return
    campos = list(linhas_csv[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas_csv)


def _linha_csv(r: ResultadoCarteira, banca_cenario: float) -> dict[str, Any]:
    return {
        "banca_cenario": banca_cenario, "origem": r.origem, "regra": r.regra_tamanho,
        "slippage": r.slippage_variante, "custo_fixo": r.custo_fixo_variante,
        "banca_final_usd": round(r.banca_final, 2), "retorno_pct": round(r.retorno_pct, 2),
        "max_drawdown_pct": round(r.max_drawdown_pct, 2), "max_drawdown_usd": round(r.max_drawdown_usd, 2),
        "maior_sequencia_perdas": r.maior_sequencia_perdas, "n_trades": r.n_trades, "n_tokens": r.n_tokens,
        "prob_ruina_pct": r.prob_ruina_pct, "r_medio": r.r_medio, "r_mediano": r.r_mediano,
        "r_medio_sem_top3": r.r_medio_sem_top3,
        "ic90_lo": r.ic90_bootstrap[0] if r.ic90_bootstrap else None,
        "ic90_hi": r.ic90_bootstrap[1] if r.ic90_bootstrap else None,
        "ponto_equilibrio_custo_fixo_usd": r.ponto_equilibrio_custo_fixo_usd,
        "pulados_total": sum(r.pulados_por_motivo.values()), "entradas_reduzidas": r.n_entradas_reduzidas,
    }


def relatorio(ao_vivo: list[TradeV3], retro: list[TradeV3], replay: list[TradeV3], now: float,
             bancas: tuple[float, ...] = BANCA_CENARIOS_PADRAO, max_posicoes: int = MAX_POSICOES_PADRAO,
             max_volume_pct: float = MAX_VOLUME_PCT_PADRAO, csv_path: Optional[Path] = None,
             progresso: bool = True) -> str:
    import sys as _sys

    def status(msg: str) -> None:
        if progresso:
            print(f"[simular_v3_carteira] {msg}", file=_sys.stderr, flush=True)

    out = ["# simular_v3_carteira -- carteira sobre sinais V3", "", f"AVISO: {AVISO}", ""]
    out.extend(_resumo_amostra(ao_vivo, "ao_vivo (V3)", now))
    out.extend(_resumo_criterios_oportunidade(ao_vivo))
    out.extend(_resumo_amostra(retro, "retro_lote1 (V3, HIPOTETICO -- amostra dentro da amostra)", now))
    out.extend(_resumo_criterios_oportunidade(retro))
    out.extend(_resumo_amostra(replay, "replay_v3 (EXPLORATORIO, HIPOTETICO -- amostra dentro da amostra)", now))
    out.extend(_resumo_criterios_oportunidade(replay))
    out.extend(_resumo_overlap_tokens(ao_vivo, retro, replay))
    out.append(f"tetos: {PCT_SUPPLY_MAX}% do supply | {max_volume_pct}% do volume do candle de entrada | "
              f"max {max_posicoes} posicoes simultaneas (uma por TOKEN por vez) | exposicao total <=100% "
              f"da banca | entrada minima US${VALOR_MINIMO_USD:.0f}")
    out.append("")
    linhas_csv: list[dict[str, Any]] = []
    for banca in bancas:
        out.append(f"## Carteira -- banca US${banca:.0f}")
        out.append("")
        for trades, label in ((ao_vivo, "ao_vivo"), (retro, "retro_lote1 (HIPOTETICO)"),
                              (replay, "replay_v3 (HIPOTETICO)")):
            status(f"banca US${banca:.0f} | {label} ({len(trades)} sinais)...")
            bloco, resultados = _tabela_origem_banca(trades, label, banca, max_posicoes, max_volume_pct)
            out.extend(bloco)
            linhas_csv.extend(_linha_csv(r, banca) for r in resultados)
    out.append(f"({AVISO})")
    if csv_path is not None:
        _escrever_csv(csv_path, linhas_csv)
        out.append(f"(tabela principal tambem gravada em {csv_path})")
    return "\n".join(out)


def executar(db_path: Path, desde: Optional[str] = None, banca: Optional[float] = None,
            max_posicoes: int = MAX_POSICOES_PADRAO, max_volume_pct: float = MAX_VOLUME_PCT_PADRAO,
            csv_path: Optional[Path] = None, progresso: bool = True) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    now = time.time()
    try:
        ao_vivo = carregar_ao_vivo(storage, desde, now)
    finally:
        storage.close()
    retro = carregar_retro_lote1(db_path, now)
    replay = carregar_replay_v3(db_path, now)
    bancas = (banca,) if banca is not None else BANCA_CENARIOS_PADRAO
    return relatorio(ao_vivo, retro, replay, now, bancas=bancas, max_posicoes=max_posicoes,
                     max_volume_pct=max_volume_pct, csv_path=csv_path, progresso=progresso)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulacao de carteira sobre sinais V3 -- PAPER/so leitura/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--desde", default=None, help="AAAA-MM-DD -- reexecuta so a partir desta data (ao_vivo)")
    parser.add_argument("--banca", type=float, default=None,
                        help="US$ -- se omitido, roda os 3 cenarios padrao (250/500/1000)")
    parser.add_argument("--max-posicoes", type=int, default=MAX_POSICOES_PADRAO)
    parser.add_argument("--max-volume-pct", type=float, default=MAX_VOLUME_PCT_PADRAO,
                        help="teto: posicao nunca > X%% do volume do candle de entrada")
    parser.add_argument("--csv", type=Path, default=None, help="grava a tabela principal (base) tambem em CSV")
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    args = parser.parse_args(argv)
    print(executar(args.db, desde=args.desde, banca=args.banca, max_posicoes=args.max_posicoes,
                  max_volume_pct=args.max_volume_pct, csv_path=args.csv, progresso=not args.sem_progresso))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
