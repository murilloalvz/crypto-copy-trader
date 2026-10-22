"""`dado_invalido` ao vivo da V1 (item 3.6 do PROMPT DEFINITIVO V1 + docs/pos-runner-v1/INTERPRETACOES.md #6).

MESMA conclusao ja revisada na EMENDA do V0 (docs/pos-runner-v0/EMENDA_QUALIDADE_DADOS_PROPOSTA.md, proposta,
nao aplicada la porque o V0 ja estava congelado): o GeckoTerminal tem candle historico defeituoso em pools
Meteora DBC (picos de 1 candle, `high/close` ate ~4e9; `L_bc` de US$14 a US$4bi). Sem teto fixo de `L_bc` por
launchpad (a curva do pump.fun e fixa, mas DBC/LaunchLab sao configuraveis por projeto -- um teto
pump.fun-especifico penalizaria graduacao legitima maior so por nao ser pump.fun). Como a V1 nasce DEPOIS
desta conclusao, a regra entra direto em `ParamsV1` (`candle_wick_ratio_max`/`l_bc_floor_usd`) -- diferente do
V0, que so emendaria isto depois de congelado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .candles import Bar
from .params_v1 import ParamsV1


@dataclass(frozen=True)
class QualidadeResult:
    valido: bool
    motivo: str = ""
    wick_ratio_1o: Optional[float] = None
    l_bc_robusto: Optional[float] = None


def l_bc_robusto(bars: list[Bar]) -> float:
    """`min(open, close do 1o candle, open do 2o)` -- menos sensivel ao 1o candle isolado (mesmo robustecimento
    revisado na EMENDA; efeito direto: facilita `S >= 0,75 x L_bc`-like checks, consequencia declarada, nao
    escondida)."""
    first = bars[0]
    return min(first.open, first.close, bars[1].open if len(bars) > 1 else float("inf"))


def avaliar_qualidade(bars: list[Bar], params: ParamsV1) -> QualidadeResult:
    """So os candles ja consumidos (sem rede). Pool sem nenhum candle ainda: `valido=True` (nada para avaliar
    ainda -- quem chama so roda isto depois do 1o candle fechado)."""
    if not bars:
        return QualidadeResult(valido=True)
    first = bars[0]
    wick_ratio_1o = (first.high / first.close) if first.close else float("inf")
    l_bc = l_bc_robusto(bars)
    if wick_ratio_1o >= params.candle_wick_ratio_max:
        return QualidadeResult(False, "wick", wick_ratio_1o, l_bc)
    if l_bc < params.l_bc_floor_usd:
        return QualidadeResult(False, "l_bc_floor", wick_ratio_1o, l_bc)
    return QualidadeResult(True, "", wick_ratio_1o, l_bc)
