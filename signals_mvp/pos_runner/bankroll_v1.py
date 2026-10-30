"""Gestao de banca da POS-RUNNER-V1 (item 2.10 do PROMPT DEFINITIVO V1): mesmo padrao do V0
(`pos_runner/bankroll.py`, revisado e em producao), adaptado para o tamanho hibrido do professor (mao fixa
abaixo de um limite de banca, fracao da banca acima dele) e para a forma do trade da V1 (TP1 parcial + EXIT
FULL do resto, uma unica trajetoria -- nao os 2 variantes A/B do V0).

Regras (item 2.10, mesma logica de pausa do V0):
- banca < banca_fixa_limite_usd -> mao fixa (mao_fixa_usd); banca >= isso -> fracao da banca (posicao_frac);
- no maximo max_posicoes_abertas posicoes abertas ao mesmo tempo;
- stop diario: banca cai >= stop_diario_frac desde o inicio do dia (UTC) OU stop_diario_perdas_seguidas perdas
  seguidas -> pausa o resto do dia;
- stop semanal (ISO, UTC): banca cai >= stop_semanal_frac desde o inicio da semana -> pausa o resto da semana;
- so trades FECHADOS (TP1 realiza parcial, mas so fecha de verdade no EXIT FULL/stop) entram na tabela e na
  contagem de posicoes abertas.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .candles import Bar
from .costs import CostModel
from .detector_v1 import EventV1
from .params_v1 import ParamsV1
from .simulate_v1 import simulate_v1

COLUMNS: tuple[str, ...] = (
    "data_entrada", "token", "contrato", "launchpad", "tf", "mc_entrada", "mc_tp1", "mc_saida", "motivo_saida",
    "tempo_no_trade_h", "lucro_bruto_pct", "taxas_pct", "lucro_liquido_pct", "tamanho_posicao_usd",
    "resultado_usd", "banca_depois_usd",
)
HEADER_LABELS = {"lucro_bruto_pct": "lucro_bruto_%", "taxas_pct": "taxas_%", "lucro_liquido_pct": "lucro_liquido_%"}


def _dia_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _semana_utc(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tamanho_posicao_usd(banca: float, params: ParamsV1) -> float:
    """Item 2.10: gestao hibrida. Nunca maior que a propria banca (uma posicao nao pode exceder o caixa)."""
    tamanho = params.mao_fixa_usd if banca < params.banca_fixa_limite_usd else banca * params.posicao_frac
    return min(tamanho, banca) if banca > 0 else 0.0


@dataclass
class BankrollStateV1:
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
    def novo(cls, banca_inicial: float) -> "BankrollStateV1":
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
    def from_json(cls, text: str) -> "BankrollStateV1":
        d = json.loads(text)
        d["open_positions"] = [tuple(p) for p in d.get("open_positions", [])]
        return cls(**d)


class BankrollLedgerV1:
    """Um ajuste por tf. `step` avanca com UM sinal ENTRADA ja sabido FECHADO (TP1 realizado e/ou saida final),
    devolve a linha da tabela (sempre, inclusive "pulado") e muda o estado."""

    def __init__(self, params: ParamsV1, base_costs: CostModel, state: Optional[BankrollStateV1] = None):
        self.params = params
        self.base_costs = base_costs
        self.state = state or BankrollStateV1.novo(params.banca_inicial_usd)

    def step(self, bars: list[Bar], ev: EventV1, dex: str, l_bc: Optional[float], sol_at: Any,
             meta: dict[str, Any]) -> Optional[dict[str, Any]]:
        s = self.state
        j0 = ev.idx + 1
        if j0 >= len(bars):
            return None
        entry_ts = bars[j0].ts
        dia = _dia_utc(entry_ts)
        if dia != s.dia_atual:
            s.dia_atual, s.banca_inicio_dia, s.perdas_seguidas, s.dia_pausado = dia, s.banca, 0, False
        semana = _semana_utc(entry_ts)
        if semana != s.semana_atual:
            s.semana_atual, s.banca_inicio_semana, s.semana_pausada = semana, s.banca, False
        s.open_positions = [p for p in s.open_positions if p[1] > entry_ts]

        linha: dict[str, Any] = {**meta, "data_entrada": _iso_utc(entry_ts), "mc_entrada": None, "mc_tp1": None,
                                 "mc_saida": None, "tempo_no_trade_h": None, "lucro_bruto_pct": None, "taxas_pct": None,
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

        position_usd = tamanho_posicao_usd(s.banca, self.params)
        if position_usd <= 0:
            return {**linha, "motivo_saida": "sem dado: banca zerada"}
        position_sol = position_usd / sol_usd_entry
        cost_model = dataclasses.replace(self.base_costs, position_sol=position_sol)
        res = simulate_v1(bars, ev, self.params, cost_model, dex, l_bc, sol_at)
        if res.status != "fechado" or not res.legs:
            return {**linha, "motivo_saida": f"sem dado: {res.status}"}

        resultado_usd = position_usd * (res.net_ret or 0.0)
        banca_depois = s.banca + resultado_usd
        tp1_leg = next((leg for leg in res.legs if leg.reason == "tp1"), None)
        linha.update(mc_entrada=res.entry_price, mc_tp1=tp1_leg.price if tp1_leg else None, mc_saida=res.legs[-1].price,
                     motivo_saida=res.legs[-1].reason, tempo_no_trade_h=(res.bars_held or 0) * (bars[1].ts - bars[0].ts) / 3600.0,
                     lucro_bruto_pct=(res.gross_ret or 0.0) * 100.0, taxas_pct=((res.gross_ret or 0.0) - (res.net_ret or 0.0)) * 100.0,
                     lucro_liquido_pct=(res.net_ret or 0.0) * 100.0, tamanho_posicao_usd=position_usd,
                     resultado_usd=resultado_usd, banca_depois_usd=banca_depois)
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
        if (s.banca - s.banca_inicio_dia <= -self.params.stop_diario_frac * s.banca_inicio_dia
                or s.perdas_seguidas >= self.params.stop_diario_perdas_seguidas):
            s.dia_pausado = True
        if s.banca - s.banca_inicio_semana <= -self.params.stop_semanal_frac * s.banca_inicio_semana:
            s.semana_pausada = True
        return linha
