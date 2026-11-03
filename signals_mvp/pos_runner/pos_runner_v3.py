"""POS-RUNNER-V3 ("ideia pura: segunda corrida pos-queda", PEDIDO 2026-11-02, Passo 1): covariaveis
por sinal, SO MEDICAO -- nunca decide ENTRADA/saida (isso e inteiramente `DetectorV1`/`simulate_v1`,
reusados de `detector_v1.py`/`simulate_v1.py` SEM nenhuma mudanca de codigo; so os valores de
`ParamsV3`, ver `params_v3.py`, diferem da V1). Cada funcao aqui e pura (bars/evento/params ja
calculados entram, nada busca rede nem le storage) -- testavel isolada, mesma disciplina de
`evidencia.py` (nunca interpola o que falta, nunca inventa um numero). `calcular_covariaveis_v3`
le SO o que `DetectorV1._check_zone` ja grava em `EventV1.data` (ver detector_v1.py) mais o candle
que disparou o gatilho (`bars[ev.idx]`) -- nenhum campo novo no detector, nenhum lookahead novo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .candles import Bar
from .detector_v1 import EventV1
from .params_v1 import ParamsV1

# PEDIDO 2026-11-02 (Passo 1): "alertar se > 1,5%" -- so atributo/tag, nunca bloqueia posicao real
# (a banca/tamanho de posicao de verdade continuam as MESMAS regras de ParamsV1, item 2.10).
POSICAO_PCT_SUPPLY_ALERTA = 1.5


@dataclass(frozen=True)
class CovariaveisV3:
    caixa_candles: Optional[int]
    caixa_horas: Optional[float]
    idade_dias: Optional[float]
    queda_pico_pct: Optional[float]
    mc_pico: Optional[float]
    mc_base: Optional[float]
    razao_base_l_bc: Optional[float]
    n_pavios: Optional[int]
    profundidade_pavios_pct: Optional[float]
    tempo_desde_pico_h: Optional[float]
    corpo_power_candle_atr: Optional[float]
    razao_corpo_descomunal: Optional[float]
    possivel_clone: bool
    gatilho_tag: str


def _profundidade_media_pavios_pct(s_suporte: Optional[float], testes: list[dict[str, Any]]) -> Optional[float]:
    """Profundidade media dos pavios (testes de suporte) relativa a S, em %: quanto a minima de cada
    teste ficou ABAIXO de S (pode ser negativo se o teste nunca furou S -- nunca truncado/forcado a
    0, o sinal importa: teste que so tocou ACIMA de S e um pavio raso de verdade)."""
    if not testes or not s_suporte:
        return None
    profundidades = [100.0 * (s_suporte - t["low"]) / s_suporte for t in testes]
    return sum(profundidades) / len(profundidades)


def gatilho_tag_v3(gatilhos: list[str]) -> str:
    """Simplifica os 3 gatilhos do detector (`GATILHOS` em detector_v1.py) nos 2 rotulos do Passo 1:
    'reacao_suporte' (teste de suporte) ou 'rompimento' (power candle OU volume rompendo R) -- um
    candle pode disparar os 2 ao mesmo tempo ('reacao_suporte+rompimento', nunca escondido).
    PUBLICA (sem `_`): reusada por `analise/condicional.py` pro estrato "gatilho" do Passo 1 item 3,
    a partir do JSON ja persistido em `pr3_signals.gatilho` -- nunca recalculada diferente."""
    tem_reacao = "reacao_suporte" in gatilhos
    tem_rompimento = any(g in gatilhos for g in ("power_candle_rompimento", "rompimento_volume"))
    if tem_reacao and tem_rompimento:
        return "reacao_suporte+rompimento"
    if tem_reacao:
        return "reacao_suporte"
    if tem_rompimento:
        return "rompimento"
    return "s/d"


def possivel_clone(symbol: Optional[str], found_ts: Optional[float],
                   outros_pools: Iterable[tuple[Optional[str], Optional[float]]]) -> bool:
    """True se outro pool JA DESCOBERTO (`pr_pools`, leitura, ZERO chamada de rede nova) tem o MESMO
    symbol (case-insensitive) com `found_ts` ESTRITAMENTE anterior -- "mesmo ticker/nome com
    lancamento anterior entre os tokens descobertos" (Passo 1). Symbol/found_ts ausentes nunca viram
    clone (sem dado, nunca adivinhado)."""
    if not symbol or found_ts is None:
        return False
    alvo = symbol.strip().lower()
    for outro_symbol, outro_found_ts in outros_pools:
        if not outro_symbol or outro_found_ts is None:
            continue
        if outro_symbol.strip().lower() == alvo and outro_found_ts < found_ts:
            return True
    return False


def posicao_pct_supply(entry_price: float, supply: Optional[float], banca_usd: float,
                       params: ParamsV1) -> Optional[float]:
    """MESMA regra de tamanho de posicao da V1 (item 2.10, `PosRunnerLive`): banca < `banca_fixa_limite_usd`
    usa `mao_fixa_usd`; senao `posicao_frac x banca`. Devolve o % do supply total que essa posicao
    compraria no preco de entrada -- SO MEDICAO/atributo (Passo 1: "alertar se > 1,5%"), nunca altera
    a banca real nem o tamanho de posicao de verdade."""
    if not supply or supply <= 0 or not entry_price or entry_price <= 0:
        return None
    posicao_usd = params.mao_fixa_usd if banca_usd < params.banca_fixa_limite_usd else params.posicao_frac * banca_usd
    tokens = posicao_usd / entry_price
    return 100.0 * tokens / supply


def calcular_covariaveis_v3(
    bars: list[Bar], ev: EventV1, step_s: int, l_bc: Optional[float],
    outros_pools: Iterable[tuple[Optional[str], Optional[float]]] = (),
    symbol: Optional[str] = None, found_ts: Optional[float] = None,
) -> CovariaveisV3:
    """`ev` precisa ser o EventV1 de kind='ENTRADA' (mesmo formato que `_check_zone` emite -- ver
    detector_v1.py). `bars`/`step_s`/`l_bc` sao os MESMOS argumentos ja usados por `simulate_v1` para
    o mesmo evento -- nunca uma leitura nova."""
    data = ev.data
    box_len = data.get("box_len")
    s_suporte = data.get("S")
    p_peak = data.get("P_peak")
    r_resistencia = data.get("R")
    atr = data.get("atr")
    peak_ts = data.get("peak_ts")
    testes = data.get("testes") or []
    bar = bars[ev.idx]
    corpo = abs(bar.close - bar.open)
    corpo_atr = (corpo / atr) if atr else None
    descomunal = (corpo / (p_peak - r_resistencia)) if (
        p_peak is not None and r_resistencia is not None and p_peak > r_resistencia) else None
    razao_base_l_bc = (s_suporte / l_bc) if (s_suporte is not None and l_bc) else None
    return CovariaveisV3(
        caixa_candles=box_len, caixa_horas=(box_len * step_s / 3600.0) if box_len is not None else None,
        idade_dias=data.get("idade_dias"), queda_pico_pct=data.get("queda_pct"),
        mc_pico=p_peak, mc_base=s_suporte, razao_base_l_bc=razao_base_l_bc,
        n_pavios=data.get("n_testes"),
        profundidade_pavios_pct=_profundidade_media_pavios_pct(s_suporte, testes),
        tempo_desde_pico_h=((ev.decision_ts - peak_ts) / 3600.0) if peak_ts is not None else None,
        corpo_power_candle_atr=corpo_atr, razao_corpo_descomunal=descomunal,
        possivel_clone=possivel_clone(symbol, found_ts, outros_pools),
        gatilho_tag=gatilho_tag_v3(list(data.get("gatilho") or [])),
    )
