"""PEDIDO 2026-11-06 (autorizado): implementacao do algoritmo EXATO pre-registrado em
`docs/pos-runner-v3/PREREGISTRO_SAIDA_FIEL_2026-11-06.md` (texto CONGELADO por hash --
`garantir_saida_fiel_registrada`, MESMO padrao de `horizonte_fixo.garantir_emenda_registrada`; nunca
editado depois de registrado). PAPER/READ-ONLY. Detector/simulate_v1/ParamsV1/ParamsV2/ParamsV3
intocados -- isto e uma variante NOVA de GESTAO DA SAIDA, nunca uma mudanca de entrada/criterio de
sinal (zero chamada a `DetectorV1`, zero escrita em `pr3_signals`/alertas/trajetoria).

Resumo do algoritmo (ver o pre-registro pra texto completo/motivacao -- esta variante foi motivada
por achados exploratorios ja vistos, rodada 11 item B3b, nunca um pre-registro "a frio"):
1. Stop inicial = `event.data["stop"]` (ja calculado pelo detector).
2. TP1 de 30% no PRIMEIRO entre (i) 1o power candle (MESMA formula de amplitude de
   `simulate_v1._exhaustion`, reusada byte a byte) e (ii) `high >= TOPO` (P_peak, `event.data["TOPO"]`
   -- NUNCA o topo da propria caixa), independente de exaustao (OR, nao AND -- diferente da regra
   OFICIAL de TP1).
3. Apos o TP1: stop do restante = preco de entrada (breakeven, via `low`).
4. Saida do restante: 1o fechamento de 1h em candle VERMELHO abaixo da linha de tendencia de alta
   (2 ultimos pivos CONFIRMADOS ascendentes, reta de 2 pontos) OU abaixo do ultimo fundo estrutural
   se nao houver par ascendente -- pivo = minima menor que as 2 vizinhas de CADA lado, confirmado
   causalmente so 2 candles depois. Breakeven tem prioridade sobre o fechamento no MESMO candle.
5. Custos/slippage: MESMA formula de `CostModel.leg_pct`/blend de pernas de `simulate_v1._finish`
   (nunca um numero novo)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable, Optional

from ..util import short_hash
from .candles import Bar, candle_corrompido_provavel
from .costs import CostModel
from .detector_v1 import EventV1
from .qualidade_candle import candle_confiavel_cb
from .simulate_v1 import _atr, _exhaustion  # noqa: F401 (_exhaustion documentado, reusa so _atr aqui)

PREREGISTRO_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v3" / "PREREGISTRO_SAIDA_FIEL_2026-11-06.md"
)
META_KEY_HASH = "saida_fiel_preregistro_hash"


class PreregistroAlteradoError(RuntimeError):
    """O texto do pre-registro em disco nao bate com o hash registrado -- recusa calcular/persistir."""


def hash_do_preregistro(path: Path = PREREGISTRO_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_saida_fiel_registrada(storage: Any, path: Path = PREREGISTRO_PATH) -> str:
    """1a chamada registra o hash atual do pre-registro; chamadas seguintes recusam
    (`PreregistroAlteradoError`) se o arquivo em disco mudou depois do registro -- mesma disciplina
    de `horizonte_fixo.garantir_emenda_registrada` (nunca editar um pre-registro no meio da coleta)."""
    atual = hash_do_preregistro(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise PreregistroAlteradoError(
            f"docs/pos-runner-v3/PREREGISTRO_SAIDA_FIEL_2026-11-06.md mudou depois de registrado "
            f"(registrado {registrado}, atual {atual}) -- abra uma nova emenda datada, nunca "
            "reescreva o pre-registro em silencio."
        )
    return atual


@dataclasses.dataclass(frozen=True)
class ResultadoSaidaFiel:
    status: str   # 'pendente' | 'resolvido' | 'marcado' | 'sem_dado'
    r_mult: Optional[float] = None
    tp1_realizado: bool = False


def _pivo_confirmado(bars: list[Bar], i: int) -> bool:
    """Pivo (fundo) em `i`: minima MENOR que as 2 vizinhas de CADA lado -- precisa de i-2..i+2
    existirem (confirmado causalmente so 2 candles depois, zero lookahead)."""
    if i - 2 < 0 or i + 2 >= len(bars):
        return False
    low = bars[i].low
    return (low < bars[i - 2].low and low < bars[i - 1].low
           and low < bars[i + 1].low and low < bars[i + 2].low)


def _nivel_tendencia_ou_fundo(pivos: list[tuple[int, float]], idx_atual: int) -> Optional[float]:
    """2 ultimos pivos CONFIRMADOS ascendentes -> reta de 2 pontos extrapolada pro candle atual;
    senao (nao ascendentes, ou so 1 pivo), usa o ULTIMO fundo estrutural confirmado como nivel
    unico; sem nenhum pivo ainda -> `None` (nenhuma protecao de tendencia/fundo disponivel)."""
    if len(pivos) >= 2:
        (i1, l1), (i2, l2) = pivos[-2], pivos[-1]
        if l2 > l1:
            slope = (l2 - l1) / (i2 - i1)
            return l2 + slope * (idx_atual - i2)
    if pivos:
        return pivos[-1][1]
    return None


def _fechar(legs: list[tuple[float, float, float]], entry: float, entry_cost_pct: float,
           risk_frac: float, status: str, tp1_realizado: bool) -> ResultadoSaidaFiel:
    """MESMA formula de `simulate_v1._finish`: blend das pernas (frac, preco, custo%), nunca um
    numero novo. `legs` = [(frac, preco, custo_pct), ...], fracoes somam 1.0."""
    c_in = entry_cost_pct / 100.0
    net = sum(frac * (preco / entry) * (1.0 - c_in) * (1.0 - custo_pct / 100.0) for frac, preco, custo_pct in legs)
    net_ret = net - 1.0
    r_mult = (net_ret / risk_frac) if risk_frac else None
    return ResultadoSaidaFiel(status, r_mult, tp1_realizado)


def calcular_r_saida_fiel(
    bars: list[Bar], event: EventV1, params: Any, costs: CostModel, dex: str, l_bc: Optional[float],
    t_entrada: float, horizonte_s: float, now: float,
    sol_usd_at: Callable[[float], Optional[float]] = lambda _t: None, veto: str = "simples",
) -> ResultadoSaidaFiel:
    """Algoritmo EXATO do pre-registro (ver docstring do modulo). `event.data["stop"]`/["TOPO"] sao
    os MESMOS da V3 (ja calculados pelo detector) -- nunca recalculados aqui. RODADA 18 (item 2):
    `veto` ('simples' padrao -- ZERO mudanca de comportamento pra quem nao passa o parametro -- ou
    'amplo' opt-in, MESMO veto de `qualidade_candle.candle_confiavel_cb` que `horizonte_fixo.py` ja
    usa por padrao desde a Rodada 17) decide qual candle corrompido nunca pode decidir TP1/stop."""
    j0 = event.idx + 1
    if j0 >= len(bars):
        return ResultadoSaidaFiel("pendente")
    stop = float(event.data["stop"])
    topo = float(event.data["TOPO"])
    entry = bars[j0].open
    if entry <= stop or entry >= topo:
        return ResultadoSaidaFiel("sem_dado")   # abriu fora do plano -- nunca foi um trade de verdade
    ts_corte = t_entrada + horizonte_s
    if now < ts_corte:
        return ResultadoSaidaFiel("pendente")

    def leg_cost(preco: float, ts: float) -> float:
        return costs.leg_pct(dex, preco, l_bc, sol_usd_at(ts), None)

    entry_cost_pct = leg_cost(entry, bars[j0].ts)
    risk_frac = (entry - stop) / entry
    if risk_frac <= 0:
        return ResultadoSaidaFiel("sem_dado")

    pivos: list[tuple[int, float]] = []
    tp1_leg: Optional[tuple[float, float, float]] = None
    ultimo_fechamento: Optional[float] = None
    ultimo_ts: Optional[float] = None

    confiavel = candle_confiavel_cb(bars, topo) if veto == "amplo" else None

    idx = j0
    while idx < len(bars):
        bar = bars[idx]
        if bar.ts > ts_corte:
            break
        confirmado_em = idx - 2
        if confirmado_em >= j0 and _pivo_confirmado(bars, confirmado_em):
            pivos.append((confirmado_em, bars[confirmado_em].low))
        vetado = confiavel(idx) is not None if confiavel is not None else candle_corrompido_provavel(bars, idx)
        if vetado:
            idx += 1
            continue
        if tp1_leg is None:
            if bar.low <= stop:   # prioridade do stop ORIGINAL dentro do mesmo candle
                saida = min(bar.open, stop)
                leg = (1.0, saida, leg_cost(saida, bar.ts))
                return _fechar([leg], entry, entry_cost_pct, risk_frac, "resolvido", False)
            atr = _atr(bars, idx, params.atr_period)
            power = atr is not None and (bar.high - bar.low) >= params.power_atr_mult * atr
            if power or bar.high >= topo:
                if idx + 1 >= len(bars):
                    break   # sem candle de execucao do TP1 dentro da serie -- pendente
                leg1_price = bars[idx + 1].open
                tp1_leg = (params.tp1_frac, leg1_price, leg_cost(leg1_price, bars[idx + 1].ts))
                idx += 1   # avanca pro candle de execucao -- entra na fase 2 na proxima iteracao
                continue
            ultimo_fechamento, ultimo_ts = bar.close, bar.ts
        else:
            if bar.low <= entry:   # breakeven tem prioridade sobre o fechamento vermelho
                saida = max(entry, bar.low)
                leg2 = (1.0 - params.tp1_frac, saida, leg_cost(saida, bar.ts))
                return _fechar([tp1_leg, leg2], entry, entry_cost_pct, risk_frac, "resolvido", True)
            nivel = _nivel_tendencia_ou_fundo(pivos, idx)
            if nivel is not None and bar.close < bar.open and bar.close < nivel:
                leg2 = (1.0 - params.tp1_frac, bar.close, leg_cost(bar.close, bar.ts))
                return _fechar([tp1_leg, leg2], entry, entry_cost_pct, risk_frac, "resolvido", True)
            ultimo_fechamento, ultimo_ts = bar.close, bar.ts
        idx += 1

    # corte do horizonte alcancado sem resolver -- marca a mercado (MESMA convencao de horizonte_fixo)
    if tp1_leg is None:
        if ultimo_fechamento is None:
            return ResultadoSaidaFiel("pendente")
        leg = (1.0, ultimo_fechamento, leg_cost(ultimo_fechamento, ultimo_ts))
        return _fechar([leg], entry, entry_cost_pct, risk_frac, "marcado", False)
    if ultimo_fechamento is None:
        # TP1 executou no ultimo candle dentro do corte -- restante nunca abriu; marca no mesmo preco
        # do TP1 (conservador, nunca inventa um preco novo).
        leg2 = (1.0 - params.tp1_frac, tp1_leg[1], tp1_leg[2])
        return _fechar([tp1_leg, leg2], entry, entry_cost_pct, risk_frac, "marcado", True)
    leg2 = (1.0 - params.tp1_frac, ultimo_fechamento, leg_cost(ultimo_fechamento, ultimo_ts))
    return _fechar([tp1_leg, leg2], entry, entry_cost_pct, risk_frac, "marcado", True)
