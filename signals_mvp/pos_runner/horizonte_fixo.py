"""PEDIDO 2026-11-05 (autorizado pelo operador): implementacao da emenda pre-registrada em
`docs/pos-runner-v1/EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md` (texto CONGELADO por hash --
`garantir_emenda_registrada`, mesmo padrao de `analise.condicional.garantir_plano_registrado`; nunca
editado depois de registrado). PAPER/READ-ONLY. Detector/simulate_v1/ParamsV1/ParamsV2/ParamsV3
intocados -- reusa `simulate_v1` e `scripts.exit_lab._marcar_a_mercado` exatamente como estao, so
aplicados a uma serie de candles TRUNCADA no horizonte fixo (72h/7d apos `t_entrada`), nunca uma regra
nova de entrada/saida.

Desfecho primario (autorizado 2026-11-05, substitui a decisao informal do item 1 do doc -- risco #1
do doc exigia "decisao formal do operador" antes de qualquer promocao, dada aqui): R valorizado a
mercado no horizonte fixo. Resolvido pela REGRA antes do corte => R realizado da regra. Senao (regra
ainda em_aberto no corte, ou so fecharia depois dele -- nunca lookahead: a serie e truncada no corte
antes de simular) => ultimo candle LIMPO <= corte, fracao ainda aberta mantida. Horizonte ainda nao
decorrido (`now < t_entrada + horizonte`) => 'pendente', NUNCA excluido nem contado como perda -- fica
de fora de qualquer media/H1 at'e resolver. R de saida por regra (sem corte) continua disponivel como
SECUNDARIO/censurado (ver `analise.condicional`), nunca descartado."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..util import short_hash
from .candles import Bar
from .costs import CostModel
from .detector_v1 import EventV1
from .params_v1 import ParamsV1
from .simulate_v1 import simulate_v1

EMENDA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v1" / "EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md"
)
META_KEY_HASH = "emenda_horizonte_fixo_hash"
HORIZONTES_S: dict[str, float] = {"72h": 72.0 * 3600.0, "7d": 7.0 * 24.0 * 3600.0}
# MESMO limiar de risco real que o resto do projeto usa pra nunca dividir por quase-zero
# (`analise.condicional.RISCO_IRREALISTA_MIN_PCT`) -- duplicado aqui (valor, nao logica) so pra nao
# criar import circular (`condicional.py` ainda nao depende deste modulo).
RISCO_IRREALISTA_MIN_PCT = 3.0


class EmendaAlteradaError(RuntimeError):
    """O texto da emenda em disco nao bate com o hash registrado -- recusa calcular/persistir."""


def hash_da_emenda(path: Path = EMENDA_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_emenda_registrada(storage: Any, path: Path = EMENDA_PATH) -> str:
    """1a chamada registra o hash atual do texto da emenda; chamadas seguintes recusam
    (`EmendaAlteradaError`) se o arquivo em disco mudou depois do registro -- mesma disciplina de
    `analise.condicional.garantir_plano_registrado` (nunca editar um pre-registro no meio da coleta)."""
    atual = hash_da_emenda(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise EmendaAlteradaError(
            f"docs/pos-runner-v1/EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md mudou depois de "
            f"registrado (registrado {registrado}, atual {atual}) -- o texto pre-registrado nao pode "
            "ser editado no meio da coleta. Abra uma nova emenda/versao em vez de reescrever este texto."
        )
    return atual


@dataclass(frozen=True)
class ResultadoHorizonte:
    status: str  # 'pendente' | 'resolvido_regra' | 'marcado' | 'sem_dado'
    r_mult: Optional[float] = None
    candle_marca_ts: Optional[float] = None


def _r_mult(net: Optional[float], risk_frac: Optional[float]) -> Optional[float]:
    if net is None or not risk_frac or 100.0 * risk_frac < RISCO_IRREALISTA_MIN_PCT:
        return None
    return net / risk_frac


def _simular_e_marcar(
    bars: list[Bar], event: EventV1, params: ParamsV1, costs: CostModel, dex: str, l_bc: Optional[float],
    sol_usd_at: Callable[[float], Optional[float]],
) -> tuple[str, Optional[float], Optional[float], Optional[float]]:
    """Roda `simulate_v1` e, se ainda `em_aberto` no FINAL da serie recebida (que quem chama ja
    truncou no corte), valoriza o restante a mercado (`scripts.exit_lab._marcar_a_mercado`, MESMA
    funcao do item 1, reusada sem copiar logica). Devolve (status_simulate, net_ret_ou_marcado,
    candle_marca_ts, risk_frac)."""
    res = simulate_v1(bars, event, params, costs, dex, l_bc, sol_usd_at)
    if res.status != "em_aberto" or res.entry_price is None or res.entry_cost_pct is None:
        return res.status, res.net_ret, None, res.risk_frac
    from ..scripts.exit_lab import _marcar_a_mercado  # import tardio: evita ciclo exit_lab<->horizonte_fixo

    remaining = 1.0 - sum(leg.frac for leg in res.legs)
    legs_realizados = [(leg.frac, leg.price, leg.cost_pct) for leg in res.legs]
    net_marcado, marca_ts = _marcar_a_mercado(bars, res.entry_price, res.entry_cost_pct, costs, dex, l_bc,
                                              legs_realizados, remaining)
    return res.status, net_marcado, marca_ts, res.risk_frac


def calcular_r_horizonte(
    bars: list[Bar], event: EventV1, params: ParamsV1, costs: CostModel, dex: str, l_bc: Optional[float],
    t_entrada: float, horizonte_s: float, now: float,
    sol_usd_at: Callable[[float], Optional[float]] = lambda _t: None,
) -> ResultadoHorizonte:
    """R no horizonte fixo (`t_entrada + horizonte_s`), causal (zero lookahead -- a serie e truncada
    no corte ANTES de simular, nunca depois). `event` e o MESMO formato que `simulate_v1` ja aceita
    (`idx`/`data`) -- serve tanto para o sinal real quanto para um controle pareado
    (`evidencia.evento_controle`), sem duplicar logica de entrada/saida."""
    ts_corte = t_entrada + horizonte_s
    if now < ts_corte:
        return ResultadoHorizonte("pendente")
    bars_truncados = [b for b in bars if b.ts <= ts_corte]
    if len(bars_truncados) <= event.idx + 1:
        return ResultadoHorizonte("pendente")   # corte decorrido mas candle de entrada ainda nao chegou
    status, net, marca_ts, risk_frac = _simular_e_marcar(bars_truncados, event, params, costs, dex, l_bc, sol_usd_at)
    if status == "cancelado":
        return ResultadoHorizonte("sem_dado")   # abriu fora do stop/TOPO -- nunca foi um trade de verdade
    if net is None:
        return ResultadoHorizonte("pendente")   # em_aberto na serie truncada, nenhum candle limpo ainda
    r_mult = _r_mult(net, risk_frac)
    status_out = "resolvido_regra" if status == "fechado" else "marcado"
    return ResultadoHorizonte(status_out, r_mult, marca_ts if status_out == "marcado" else None)
