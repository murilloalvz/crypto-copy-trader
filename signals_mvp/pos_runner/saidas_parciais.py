"""PEDIDO 2026-11-10 (autorizado, rodada 13): implementação da grade FECHADA de saídas PARCIAIS
antecipadas pré-registrada em `docs/pos-runner-v3/PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md` (texto
CONGELADO por hash -- `garantir_saidas_parciais_registrada`, MESMO padrão de `saida_fiel.
garantir_saida_fiel_registrada`; nunca editado depois de registrado). PAPER/READ-ONLY.
Detector/simulate_v1/ParamsV1/ParamsV2/ParamsV3 intocados -- isto é GESTÃO DA SAÍDA apenas (zero
chamada a `DetectorV1`, zero escrita em `pr3_signals`/alertas/trajetória).

Resumo (ver o pré-registro pra texto completo/motivação -- motivada pelo B3b (a) = -0,15R sobre
TODOS, rodada 12 Parte 4a, nunca um pré-registro "a frio"):
1. TP1 no PRIMEIRO toque (`high >= alvo`, decidido no fechamento, executado no open do candle
   seguinte) de um dos 5 gatilhos (`+1R`/`+2R`/`+3R`/`topo_caixa`=R/`meio_topo_anterior`), com
   fração 30% ou 50% (`VarianteSaidaParcial.tp1_frac`).
2. Restante: `segurar` (stop original nunca se move), `breakeven` (move pro preço de entrada), ou
   `trailing` (stop original nunca se move + saída adicional no 1o fechamento vermelho de 1h abaixo
   do último fundo ascendente -- `_pivo_confirmado`, MESMA definição de `saida_fiel.py`).
3. Custos/slippage: MESMA fórmula de `CostModel.leg_pct`, mas com um multiplicador OPCIONAL só sobre
   o componente de slippage das pernas de SAÍDA (`slippage_saida_mult`, sensibilidade 2x/3x pedida).
4. Grade fechada de 24 variantes (`GRADE_24`) -- ver pré-registro pra a regra exata de poda de 30 pra
   24 (fração 50% só nos 3 gatilhos mais distantes do já medido)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable, Optional

from ..util import short_hash
from .candles import Bar, candle_corrompido_provavel
from .costs import CostModel
from .detector_v1 import EventV1
from .qualidade_candle import candle_confiavel_cb
from .saida_fiel import _fechar, _pivo_confirmado

PREREGISTRO_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v3" / "PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md"
)
META_KEY_HASH = "saidas_parciais_preregistro_hash"


class PreregistroAlteradoError(RuntimeError):
    """O texto do pré-registro em disco não bate com o hash registrado -- recusa calcular/persistir."""


def hash_do_preregistro(path: Path = PREREGISTRO_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_saidas_parciais_registrada(storage: Any, path: Path = PREREGISTRO_PATH) -> str:
    """1a chamada registra o hash atual do pré-registro; chamadas seguintes recusam
    (`PreregistroAlteradoError`) se o arquivo em disco mudou depois do registro -- mesma disciplina
    de `saida_fiel.garantir_saida_fiel_registrada`."""
    atual = hash_do_preregistro(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise PreregistroAlteradoError(
            f"docs/pos-runner-v3/PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md mudou depois de "
            f"registrado (registrado {registrado}, atual {atual}) -- abra uma nova emenda datada, "
            "nunca reescreva o pré-registro em silêncio."
        )
    return atual


# ---------------------------------------------------------------------------
# gatilhos de TP1 e restantes -- eixos da grade
# ---------------------------------------------------------------------------

TRIGGER_1R = "+1R"
TRIGGER_2R = "+2R"
TRIGGER_3R = "+3R"
TRIGGER_TOPO_CAIXA = "topo_caixa"
TRIGGER_MEIO_TOPO_ANTERIOR = "meio_topo_anterior"
TRIGGERS: tuple[str, ...] = (TRIGGER_1R, TRIGGER_2R, TRIGGER_3R, TRIGGER_TOPO_CAIXA, TRIGGER_MEIO_TOPO_ANTERIOR)

REMAINDER_SEGURAR = "segurar"
REMAINDER_BREAKEVEN = "breakeven"
REMAINDER_TRAILING = "trailing"
REMAINDERS: tuple[str, ...] = (REMAINDER_SEGURAR, REMAINDER_BREAKEVEN, REMAINDER_TRAILING)

# gatilhos mais distantes do ja medido (B3b (a) ~= topo_caixa; +2R = ALVO_PAREAMENTO_TOQUE de
# varredura_v3.py) -- SO estes ganham a fracao de 50% (ver pre-registro, secao "poda de 30 para 24").
TRIGGERS_FRACAO_50: tuple[str, ...] = (TRIGGER_1R, TRIGGER_3R, TRIGGER_MEIO_TOPO_ANTERIOR)


@dataclasses.dataclass(frozen=True)
class VarianteSaidaParcial:
    tp1_trigger: str
    tp1_frac: float
    remainder: str

    @property
    def nome(self) -> str:
        return f"{self.tp1_trigger}_f{int(round(self.tp1_frac * 100))}_{self.remainder}"


def _construir_grade_24() -> tuple[VarianteSaidaParcial, ...]:
    variantes: list[VarianteSaidaParcial] = []
    for trigger in TRIGGERS:
        for remainder in REMAINDERS:
            variantes.append(VarianteSaidaParcial(trigger, 0.30, remainder))
    for trigger in TRIGGERS_FRACAO_50:
        for remainder in REMAINDERS:
            variantes.append(VarianteSaidaParcial(trigger, 0.50, remainder))
    return tuple(variantes)


GRADE_24: tuple[VarianteSaidaParcial, ...] = _construir_grade_24()
assert len(GRADE_24) == 24, "grade fechada precisa ter exatamente 24 variantes (ver pre-registro)"
assert len({v.nome for v in GRADE_24}) == 24, "nomes de variante precisam ser unicos"


@dataclasses.dataclass(frozen=True)
class ResultadoSaidaParcial:
    status: str   # 'pendente' | 'resolvido' | 'marcado' | 'sem_dado'
    r_mult: Optional[float] = None
    tp1_realizado: bool = False
    r_leg1: Optional[float] = None   # (preco_leg1 - entry) / risk, PRE-custo, isolado
    r_leg2: Optional[float] = None   # (preco_leg2 - entry) / risk, PRE-custo, isolado


def _preco_alvo_tp1(trigger: str, entry: float, event: EventV1) -> Optional[float]:
    risk = entry - float(event.data["stop"])
    if risk <= 0:
        return None
    if trigger == TRIGGER_1R:
        return entry + 1.0 * risk
    if trigger == TRIGGER_2R:
        return entry + 2.0 * risk
    if trigger == TRIGGER_3R:
        return entry + 3.0 * risk
    if trigger == TRIGGER_TOPO_CAIXA:
        r_caixa = event.data.get("R")
        return float(r_caixa) if r_caixa is not None else None
    if trigger == TRIGGER_MEIO_TOPO_ANTERIOR:
        topo = event.data.get("TOPO")
        return entry + 0.5 * (float(topo) - entry) if topo is not None else None
    raise ValueError(f"gatilho de TP1 desconhecido: {trigger}")


def _ultimo_fundo_ascendente(pivos: list[tuple[int, float]]) -> Optional[float]:
    """Pivo mais recente confirmado, SO se for maior que o pivo confirmado imediatamente anterior
    (ascendente) -- `None` se houver menos de 2 pivos, ou se o par mais recente nao for ascendente
    (nunca inventa um nivel de protecao fora desses 2 casos)."""
    if len(pivos) < 2:
        return None
    (_, anterior), (_, ultimo) = pivos[-2], pivos[-1]
    return ultimo if ultimo > anterior else None


def _leg_cost(costs: CostModel, dex: str, preco: float, l_bc: Optional[float], sol_usd: Optional[float],
             slippage_mult: float) -> float:
    """MESMA formula de `CostModel.leg_pct`, mas multiplicando SO o componente de slippage -- nunca
    o fee do pool/terminal/rede (sensibilidade 2x/3x pedida, só sobre slippage de SAÍDA)."""
    if slippage_mult == 1.0:
        return costs.leg_pct(dex, preco, l_bc, sol_usd, None)
    network_pct = 100.0 * costs.network_sol / costs.position_sol
    base = (costs.pool_fee_pct(dex, preco, sol_usd, None) + costs.terminal_pct + network_pct
           + slippage_mult * costs.slippage_pct(preco, l_bc, sol_usd))
    return base * costs.multiplier


def calcular_r_variante(
    bars: list[Bar], event: EventV1, costs: CostModel, dex: str, l_bc: Optional[float],
    t_entrada: float, horizonte_s: float, now: float, variante: VarianteSaidaParcial,
    sol_usd_at: Callable[[float], Optional[float]] = lambda _t: None, slippage_saida_mult: float = 1.0,
    veto: str = "simples",
) -> ResultadoSaidaParcial:
    """Algoritmo EXATO do pré-registro (ver docstring do módulo), pra UMA `variante` da grade.
    RODADA 18 (item 2): `veto` ('simples' padrao -- ZERO mudanca de comportamento pra quem nao passa
    o parametro -- ou 'amplo' opt-in, MESMO veto de `qualidade_candle.candle_confiavel_cb`)."""
    j0 = event.idx + 1
    if j0 >= len(bars):
        return ResultadoSaidaParcial("pendente")
    stop = float(event.data["stop"])
    entry = bars[j0].open
    if entry <= stop:
        return ResultadoSaidaParcial("sem_dado")
    preco_alvo = _preco_alvo_tp1(variante.tp1_trigger, entry, event)
    if preco_alvo is None or preco_alvo <= entry:
        return ResultadoSaidaParcial("sem_dado")   # gatilho indisponivel pra este sinal
    ts_corte = t_entrada + horizonte_s
    if now < ts_corte:
        return ResultadoSaidaParcial("pendente")

    def leg_cost(preco: float, ts: float, saida: bool) -> float:
        mult = slippage_saida_mult if saida else 1.0
        return _leg_cost(costs, dex, preco, l_bc, sol_usd_at(ts), mult)

    entry_cost_pct = leg_cost(entry, bars[j0].ts, saida=False)
    risk_frac = (entry - stop) / entry
    if risk_frac <= 0:
        return ResultadoSaidaParcial("sem_dado")
    risk = entry - stop

    pivos: list[tuple[int, float]] = []
    tp1_leg: Optional[tuple[float, float, float]] = None
    r_leg1: Optional[float] = None
    ultimo_fechamento: Optional[float] = None
    ultimo_ts: Optional[float] = None

    confiavel = candle_confiavel_cb(bars, event.data.get("TOPO")) if veto == "amplo" else None

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
            if bar.low <= stop:
                saida = min(bar.open, stop)
                leg = (1.0, saida, leg_cost(saida, bar.ts, saida=True))
                return _fechar([leg], entry, entry_cost_pct, risk_frac, "resolvido", False)
            if bar.high >= preco_alvo:
                if idx + 1 >= len(bars) or bars[idx + 1].ts > ts_corte:
                    break   # disparou mas sem candle de execucao dentro do corte -- marca abaixo
                leg1_price = bars[idx + 1].open
                tp1_leg = (variante.tp1_frac, leg1_price, leg_cost(leg1_price, bars[idx + 1].ts, saida=True))
                r_leg1 = (leg1_price - entry) / risk
                idx += 1
                continue
            ultimo_fechamento, ultimo_ts = bar.close, bar.ts
        else:
            nivel_stop_low = entry if variante.remainder == REMAINDER_BREAKEVEN else stop
            if bar.low <= nivel_stop_low:
                saida = max(nivel_stop_low, bar.low)
                leg2 = (1.0 - variante.tp1_frac, saida, leg_cost(saida, bar.ts, saida=True))
                r_leg2 = (saida - entry) / risk
                return _concluir(tp1_leg, leg2, entry, entry_cost_pct, risk_frac, "resolvido", r_leg1, r_leg2)
            if variante.remainder == REMAINDER_TRAILING:
                fundo_asc = _ultimo_fundo_ascendente(pivos)
                if fundo_asc is not None and bar.close < bar.open and bar.close < fundo_asc:
                    leg2 = (1.0 - variante.tp1_frac, bar.close, leg_cost(bar.close, bar.ts, saida=True))
                    r_leg2 = (bar.close - entry) / risk
                    return _concluir(tp1_leg, leg2, entry, entry_cost_pct, risk_frac, "resolvido",
                                     r_leg1, r_leg2)
            ultimo_fechamento, ultimo_ts = bar.close, bar.ts
        idx += 1

    if tp1_leg is None:
        if ultimo_fechamento is None:
            return ResultadoSaidaParcial("pendente")
        leg = (1.0, ultimo_fechamento, leg_cost(ultimo_fechamento, ultimo_ts, saida=True))
        return _concluir(None, leg, entry, entry_cost_pct, risk_frac, "marcado", None, None, legs_unica=True)
    if ultimo_fechamento is None:
        leg2 = (1.0 - variante.tp1_frac, tp1_leg[1], tp1_leg[2])
        return _concluir(tp1_leg, leg2, entry, entry_cost_pct, risk_frac, "marcado", r_leg1, r_leg1)
    leg2 = (1.0 - variante.tp1_frac, ultimo_fechamento, leg_cost(ultimo_fechamento, ultimo_ts, saida=True))
    r_leg2 = (ultimo_fechamento - entry) / risk
    return _concluir(tp1_leg, leg2, entry, entry_cost_pct, risk_frac, "marcado", r_leg1, r_leg2)


def _concluir(leg1: Optional[tuple[float, float, float]], leg2: tuple[float, float, float], entry: float,
             entry_cost_pct: float, risk_frac: float, status: str, r_leg1: Optional[float],
             r_leg2: Optional[float], legs_unica: bool = False) -> ResultadoSaidaParcial:
    legs = [leg2] if legs_unica else [leg1, leg2]
    r = _fechar(legs, entry, entry_cost_pct, risk_frac, status, not legs_unica)
    return ResultadoSaidaParcial(r.status, r.r_mult, r.tp1_realizado, r_leg1, r_leg2)
