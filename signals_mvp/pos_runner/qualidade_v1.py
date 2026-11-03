"""`dado_invalido` ao vivo da V1 (item 3.6 do PROMPT DEFINITIVO V1 + docs/pos-runner-v1/INTERPRETACOES.md #6).

MESMA conclusao ja revisada na EMENDA do V0 (docs/pos-runner-v0/EMENDA_QUALIDADE_DADOS_PROPOSTA.md, proposta,
nao aplicada la porque o V0 ja estava congelado): o GeckoTerminal tem candle historico defeituoso em pools
Meteora DBC (picos de 1 candle, `high/close` ate ~4e9; `L_bc` de US$14 a US$4bi). Sem teto fixo PRECISO de
`L_bc` por launchpad (a curva do pump.fun e fixa, mas DBC/LaunchLab sao configuraveis por projeto e este repo
nao tem o parametro de graduacao de nenhum dos dois sourced -- um teto pump.fun-especifico penalizaria
graduacao legitima maior so por nao ser pump.fun). Como a V1 nasce DEPOIS desta conclusao, a regra entra
direto em `ParamsV1` (`candle_wick_ratio_max`/`l_bc_floor_usd`) -- diferente do V0, que so emendaria isto
depois de congelado.

Revisao da FASE 1 (2026-10-22, evidencia do operador: 547/917 pools DBC com L_bc > 500k, alguns ~US$4bi;
47/132 pools pump.fun com L_bc < 1k): o floor/wick ja cobrem o caso do pump.fun (<1k cai no floor so se for
mesmo um defeito; a maioria dos <1k provavelmente cai no WICK, nao no floor). Para o lado de cima,
`l_bc_ceiling_usd` (teto de SANIDADE, agnostico de launchpad, NAO uma precisao por launchpad) pega o cluster
de centenas de milhares a bilhoes sem assumir nenhuma curva especifica.

Revisao da FASE 1.1 (2026-10-22, evidencia do operador: a menor graduacao legitima medida neste repo e
~28k, N=8; o checkpoint do operador tem 164 pools com L_bc entre US$14 e US$1.000, fisicamente impossivel
para uma graduacao real): o piso subiu de US$100 para US$5.000 (ainda bem abaixo do minimo legitimo medido,
sem alcancar o cluster impossivel). Alem do piso/teto DUROS (bloqueiam, nunca viram alerta), existe agora
uma faixa SUSPEITA (`l_bc_suspeito_baixo_usd`/`l_bc_suspeito_alto_usd`) que NUNCA bloqueia -- so adiciona a
tag `l_bc_suspeito` ao alerta/CSV/contadores para o operador conferir a mao no GeckoTerminal quando o L_bc
foge do grosso da distribuicao sem ser um defeito obvio de candle.
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
    suspeito: bool = False   # tag suave `l_bc_suspeito` (FASE 1.1): NUNCA bloqueia, so acompanha o alerta


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
    if l_bc > params.l_bc_ceiling_usd:
        return QualidadeResult(False, "l_bc_ceiling", wick_ratio_1o, l_bc)
    suspeito = l_bc < params.l_bc_suspeito_baixo_usd or l_bc > params.l_bc_suspeito_alto_usd
    return QualidadeResult(True, "", wick_ratio_1o, l_bc, suspeito)
