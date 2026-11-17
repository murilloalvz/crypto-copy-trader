"""PATCH 2026-10-27 (diagnostico McRib/yagi, docs/pos-runner-v1/INTERPRETACOES.md #13): valida CADA
candle usado em gatilho/entrada/TP1/saida das V1 e V2 -- `qualidade_v1.avaliar_qualidade` so valida
`bars[0]`, 1x, na construcao do detector, e nunca mais depois. Limiares NESTE modulo (config PROPRIA,
fora de `ParamsV1`/`ParamsV2` -- por isso nunca entra no hash de nenhuma das duas versoes).

Duas regras distintas (pedido do operador):
  - GATILHO (entrada): candle suspeito NUNCA pode disparar -- veto absoluto, causal (so usa o candle
    anterior, nunca o seguinte -- regra "sem lookahead" do CLAUDE.md). A zona continua armada; um
    candle LIMPO mais tarde ainda pode disparar normalmente.
  - TP1/EXIT (dentro de `simulate_v1`, que e re-simulado a cada ciclo sobre os candles mais recentes):
    candle suspeito nao decide NADA neste candle (nem stop, nem TP1, nem exit_full) ate confirmar por
    DexPaprika OU pelo candle seguinte -- mesma janela de 1 candle de atraso que a execucao no OPEN
    seguinte ja usa, entao nao e uma violacao nova de causalidade, so uma extensao do mesmo atraso.

NAO toca o rastreamento de onda/pico (`DetectorV1._update_wave`) nem S/R da zona (`_update_zone`) --
fora do escopo pedido (gatilho/entrada/TP1/saida); documentado como limitacao conhecida.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .candles import Bar

PATCH_DATA = "2026-10-27"
QUALIDADE_VERSAO = "candle_v1_2026-10-27"


@dataclass(frozen=True)
class LimiaresQualidadeCandle:
    razao_vizinho_max: float = 10.0   # high/low/close a mais desse multiplo do candle vizinho = suspeito
    razao_pico_max: float = 3.0       # close > esse multiplo do pico (P_peak/TOPO) = suspeito


LIMIARES_PADRAO = LimiaresQualidadeCandle()


def ohlc_coerente(bar: Bar) -> bool:
    """low <= min(open,close) <= max(open,close) <= high -- consistencia minima, independente de
    qualquer vizinho ou limiar configuravel."""
    lo, hi = min(bar.open, bar.close), max(bar.open, bar.close)
    return bar.low <= lo + 1e-9 and bar.high >= hi - 1e-9 and bar.low <= bar.high + 1e-9


def _razao(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return float("inf")
    return max(a, b) / min(a, b)


def _pico_do_candle(bar: Bar) -> float:
    return max(bar.high, bar.open, bar.close, bar.low if bar.low > 0 else 0.0)


LIMIAR_CORROMPIDO_PROVAVEL_PCT = 50.0


def motivo_suspeito(
    bar: Bar, vizinho_anterior_close: Optional[float], peak: Optional[float],
    vizinho_seguinte_open: Optional[float] = None, dex_divergente: bool = False,
    dex_diff_pct_max: Optional[float] = None, limiares: LimiaresQualidadeCandle = LIMIARES_PADRAO,
) -> Optional[str]:
    """`None` = confiavel. Caso contrario, motivo curto (`ohlc_incoerente` / `dexpaprika_divergente` /
    `candle_corrompido_provavel` / `close_vs_pico` / `sem_confirmacao_candle_seguinte` /
    `candle_isolado_vs_vizinhos`).

    `vizinho_seguinte_open` SO deve ser passado quando a chamada e causalmente posterior ao candle
    seguinte existir (TP1/EXIT, re-simulado a cada ciclo) -- o gatilho de ENTRADA (decisao causal, no
    fechamento do proprio candle) nunca passa esse argumento.

    `dex_diff_pct_max` (PEDIDO 2026-10-29): a MAIOR diferenca % (qualquer campo OHLC) entre GT e
    DexPaprika PARA ESTE candle, quando `dex_divergente=True` -- so pra NOMEAR a severidade (>50% =
    `candle_corrompido_provavel`, provavel corrupcao de dado, nao so ruido normal de fonte); o VETO em
    si (nenhum gatilho/TP1/saida decide neste candle) e IDENTICO nos dois casos, so o rotulo muda."""
    if not ohlc_coerente(bar):
        return "ohlc_incoerente"
    if dex_divergente:
        if dex_diff_pct_max is not None and dex_diff_pct_max > LIMIAR_CORROMPIDO_PROVAVEL_PCT:
            return "candle_corrompido_provavel"
        return "dexpaprika_divergente"
    pico_candle = _pico_do_candle(bar)
    if peak is not None and peak > 0 and bar.close > limiares.razao_pico_max * peak:
        return "close_vs_pico"
    if vizinho_anterior_close is None or vizinho_anterior_close <= 0:
        return None
    if _razao(pico_candle, vizinho_anterior_close) <= limiares.razao_vizinho_max:
        return None
    # suspeito vs o candle anterior: so e decisivo se nao houver como confirmar/descartar ainda.
    if vizinho_seguinte_open is None:
        return "sem_confirmacao_candle_seguinte"
    if vizinho_seguinte_open > 0 and _razao(pico_candle, vizinho_seguinte_open) <= limiares.razao_vizinho_max:
        return None   # o nivel persistiu no candle seguinte -- nao foi um glitch isolado
    return "candle_isolado_vs_vizinhos"


def candle_confiavel_cb(bars: list[Bar], peak: Optional[float],
                        divergencias: Optional[dict[int, float]] = None) -> Callable[[int], Optional[str]]:
    """RODADA 17 (achado P1 da Parte B da auditoria 2026-11-10): o MESMO veto de candle corrompido
    que o caminho ao vivo ja aplica em `simulate_v1(candle_confiavel=...)` (`PosRunnerLive.
    _candle_confiavel_cb`), extraido aqui como funcao PURA (sem `self`/Storage) pra ser reusada por
    qualquer motor OFFLINE (`horizonte_fixo.py`, `varredura_v3.py`, `simular_v3_carteira.py`,
    `auditoria_fidelidade_v3.py`, `retrospectivo_saida_fiel.py`) -- nunca uma 2a implementacao do
    mesmo veto que poderia divergir com o tempo. `bars` e a serie JA RESOLVIDA (historica, nunca
    streaming ao vivo) -- por isso `vizinho_seguinte_open` e sempre passado quando `j+1 < len(bars)`
    (causalmente seguro aqui: a serie inteira ja e fato passado no momento do calculo, ao contrario
    do caminho ao vivo que so conhece o candle seguinte quando ele de fato ja chegou).

    `divergencias` (opcional): {ts_do_candle: maior_diff_pct_dexpaprika} -- so existe no caminho ao
    vivo (cruza contra `pr1_dexpaprika_divergencias`, que so e populado pelo bot rodando de verdade);
    motores offline sem esse cruzamento passam `None`/omitem (equivalente a `dex_divergente=False`
    pra todo candle -- o veto por OHLC/pico/vizinho continua identico, so falta a confirmacao extra
    por DexPaprika que so o bot ao vivo tem)."""
    divergencias = divergencias or {}

    def cb(j: int) -> Optional[str]:
        bar = bars[j]
        anterior = bars[j - 1].close if j > 0 else None
        seguinte = bars[j + 1].open if j + 1 < len(bars) else None
        dex_divergente = bar.ts in divergencias
        return motivo_suspeito(bar, anterior, peak, seguinte, dex_divergente, divergencias.get(bar.ts))
    return cb
