"""Gestao de banca por ajuste (tf x saida) do POS-RUNNER-V0: addendum de RELATORIO pre-registrado em 2026-10-16
(substitui o item 1, "simulacao de banca", da mensagem original do operador). NAO muda nenhuma regra do
detector/simulador nem a escolha da variante (isso continua vindo so do custo FIXO de 0,15 SOL do handoff) --
aqui o tamanho da posicao e REAL (5% de uma banca de US$100 por ajuste) so para esta tabela ilustrativa, por
isso o trade e RESIMULADO com um `CostModel` do tamanho real (mesmo detector, mesmo evento, mesmo caminho de
preco; so o custo muda com o tamanho).

Regras (separadas por ajuste, nunca preco medio):
- banca inicial US$100; posicao = 5% da banca NO MOMENTO da entrada;
- no maximo 3 posicoes abertas ao mesmo tempo (a 4a entrada fica "pulado: limite");
- stop diario: banca cai >= 10% desde o inicio do dia (UTC) OU 3 perdas seguidas -> pausa o resto do dia
  ("pulado: stop diario");
- stop semanal (ISO, UTC): banca cai >= 20% desde o inicio da semana -> pausa o resto da semana
  ("pulado: stop semanal");
- so trades FECHADOS entram na tabela e na contagem de posicoes abertas.

Modulo compartilhado (sem dependencia de `Context`/`Store`): a Parte A (`parte_a/bankroll.py`, loteada) e a Parte
B ao vivo (`live.py`, um passo por sinal fechado, estado persistido) usam o MESMO `BankrollLedger`.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .candles import Bar
from .costs import CostModel
from .detector import Event
from .params import Params
from .simulate import simulate

COLUMNS: tuple[str, ...] = (
    "data_entrada", "token", "contrato", "launchpad", "tf", "saida", "mc_entrada", "mc_saida", "motivo_saida",
    "tempo_no_trade_h", "lucro_bruto_pct", "taxas_pct", "lucro_liquido_pct", "tamanho_posicao_usd",
    "resultado_usd", "banca_depois_usd",
)
HEADER_LABELS = {"lucro_bruto_pct": "lucro_bruto_%", "taxas_pct": "taxas_%", "lucro_liquido_pct": "lucro_liquido_%"}

# motivo de saida do simulador -> rotulo do operador (TP/stop/exaustao/tempo); "trailing"/"stop_na_entrada" sao
# o stop (parcial ja vendido no alvo) do resto da posicao na saida B -- continuam sendo um STOP, nao um 2o TP
_MOTIVO = {"alvo": "TP", "stop": "stop", "stop_na_entrada": "stop", "trailing": "stop", "exaustao": "exaustão", "tempo": "tempo"}


@dataclass(frozen=True)
class BankrollParams:
    banca_inicial_usd: float = 100.0
    posicao_frac: float = 0.05
    max_posicoes_abertas: int = 3
    stop_diario_frac: float = 0.10
    stop_diario_perdas_seguidas: int = 3
    stop_semanal_frac: float = 0.20


def _dia_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _semana_utc(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


@dataclass
class BankrollState:
    """Estado completo de UM ajuste (tf x variante); serializavel para persistir entre reinicios (Parte B)."""

    banca: float
    peak_banca: float
    banca_inicio_dia: float
    banca_inicio_semana: float
    open_positions: list[tuple[float, float]] = field(default_factory=list)
    dia_atual: Optional[str] = None
    perdas_seguidas: int = 0
    dia_pausado: bool = False
    semana_atual: Optional[str] = None
    semana_pausada: bool = False
    maior_queda_usd: float = 0.0
    maior_queda_pct: float = 0.0
    n_trades: int = 0
    n_lucro: int = 0
    soma_liq_pct: float = 0.0

    @classmethod
    def novo(cls, banca_inicial: float) -> "BankrollState":
        return cls(banca=banca_inicial, peak_banca=banca_inicial, banca_inicio_dia=banca_inicial, banca_inicio_semana=banca_inicial)

    def resumo(self) -> dict[str, Any]:
        n = self.n_trades
        return {
            "n_trades": n,
            "pct_com_lucro": (100.0 * self.n_lucro / n) if n else None,
            "lucro_liq_medio_pct": (self.soma_liq_pct / n) if n else None,
            "banca_final_usd": self.banca,
            "maior_queda_usd": self.maior_queda_usd,
            "maior_queda_pct": self.maior_queda_pct,
        }

    def to_json(self) -> str:
        d = dataclasses.asdict(self)
        d["open_positions"] = [list(p) for p in self.open_positions]
        return json.dumps(d)

    @classmethod
    def from_json(cls, text: str) -> "BankrollState":
        d = json.loads(text)
        d["open_positions"] = [tuple(p) for p in d.get("open_positions", [])]
        return cls(**d)


class BankrollLedger:
    """Um ajuste (tf x variante): `step` avanca com UMA entrada primaria ja sabida FECHADA pelo custo oficial
    (0,15 SOL), devolve a linha da tabela (sempre, inclusive "pulado") e muda o estado. `base_costs` e so o molde
    (terminal_pct/network_sol/multiplier); o `position_sol` de cada chamada vem da banca atual."""

    def __init__(self, detector_params: Params, base_costs: CostModel, params: BankrollParams = BankrollParams(),
                state: Optional[BankrollState] = None):
        self.detector_params = detector_params
        self.base_costs = base_costs
        self.params = params
        self.state = state or BankrollState.novo(params.banca_inicial_usd)

    def step(self, bars: list[Bar], ev: Event, variant: str, dex: str, l_bc: Optional[float],
             sol_at: Any, meta: dict[str, Any]) -> Optional[dict[str, Any]]:
        s = self.state
        j0 = ev.idx + 1
        if j0 >= len(bars):
            return None   # sem o candle de entrada ainda: o chamador so deve chamar apos o trade oficial fechar
        entry_ts = bars[j0].ts
        dia = _dia_utc(entry_ts)
        if dia != s.dia_atual:
            s.dia_atual, s.banca_inicio_dia, s.perdas_seguidas, s.dia_pausado = dia, s.banca, 0, False
        semana = _semana_utc(entry_ts)
        if semana != s.semana_atual:
            s.semana_atual, s.banca_inicio_semana, s.semana_pausada = semana, s.banca, False
        s.open_positions = [p for p in s.open_positions if p[1] > entry_ts]

        linha: dict[str, Any] = {**meta, "data_entrada": _iso_utc(entry_ts), "mc_entrada": None, "mc_saida": None,
                                 "tempo_no_trade_h": None, "lucro_bruto_pct": None, "taxas_pct": None,
                                 "lucro_liquido_pct": None, "tamanho_posicao_usd": None, "resultado_usd": None,
                                 "banca_depois_usd": None}
        if s.semana_pausada:
            return {**linha, "motivo_saida": "pulado: stop semanal"}
        if s.dia_pausado:
            return {**linha, "motivo_saida": "pulado: stop diário"}
        if len(s.open_positions) >= self.params.max_posicoes_abertas:
            return {**linha, "motivo_saida": "pulado: limite"}
        sol_usd_entry = sol_at(entry_ts)
        if not sol_usd_entry:
            return {**linha, "motivo_saida": "sem dado: sol/usd"}

        position_usd = s.banca * self.params.posicao_frac
        position_sol = position_usd / sol_usd_entry
        cost_model = dataclasses.replace(self.base_costs, position_sol=position_sol)
        res = simulate(bars, ev, variant, self.detector_params, cost_model, dex, l_bc, sol_at)
        if res.status != "fechado" or not res.legs:
            return {**linha, "motivo_saida": f"sem dado: {res.status}"}

        resultado_usd = position_usd * (res.net_ret or 0.0)
        banca_depois = s.banca + resultado_usd
        linha.update(mc_entrada=res.entry_price, mc_saida=res.legs[-1].price,
                     motivo_saida=_MOTIVO.get(res.reason, res.reason or "sem dado"),
                     tempo_no_trade_h=(res.bars_held or 0) * _TF_HOURS[meta["tf"]],
                     lucro_bruto_pct=(res.gross_ret or 0.0) * 100.0,
                     taxas_pct=((res.gross_ret or 0.0) - (res.net_ret or 0.0)) * 100.0,
                     lucro_liquido_pct=(res.net_ret or 0.0) * 100.0,
                     tamanho_posicao_usd=position_usd, resultado_usd=resultado_usd, banca_depois_usd=banca_depois)
        s.open_positions.append((entry_ts, res.legs[-1].ts))
        s.banca = banca_depois
        s.n_trades += 1
        if resultado_usd > 0:
            s.n_lucro += 1
            s.perdas_seguidas = 0
        else:
            s.perdas_seguidas += 1
        s.soma_liq_pct += linha["lucro_liquido_pct"]
        s.peak_banca = max(s.peak_banca, s.banca)
        queda_usd = s.peak_banca - s.banca
        if queda_usd > s.maior_queda_usd:
            s.maior_queda_usd = queda_usd
            s.maior_queda_pct = 100.0 * queda_usd / s.peak_banca if s.peak_banca else 0.0
        if s.banca - s.banca_inicio_dia <= -self.params.stop_diario_frac * s.banca_inicio_dia or s.perdas_seguidas >= self.params.stop_diario_perdas_seguidas:
            s.dia_pausado = True
        if s.banca - s.banca_inicio_semana <= -self.params.stop_semanal_frac * s.banca_inicio_semana:
            s.semana_pausada = True
        return linha


_TF_HOURS = {"5m": 5 / 60, "1h": 1.0, "4h": 4.0}


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
