"""Detector causal incremental da estrategia POS-RUNNER-V1 ("regras do professor", PROMPT DEFINITIVO). Mesmo
principio do V0 (`detector.py`): consome candles FECHADOS, um por vez, decisao no candle i usa so 0..i.

Reaproveita a classe `Zone` do V0 (item 3.1 do prompt: "definicao de wick e caixa: reaproveitar o detector
existente") -- mesma mecanica de suporte/resistencia/testes (S = minima da zona, R = maxima depois do fundo
fixado pelo 1o repique, teste = episodio de mínima dentro da regiao do suporte seguido de recuperacao). O que e
NOVO em relacao ao V0 esta documentado em docs/pos-runner-v1/INTERPRETACOES.md:

  fase 1  runner: pico (maxima) da onda >= runner_min_mc (filtro); >= peak_attr_mc e so ATRIBUTO.
  fase 2  queda >= drop_min desde o pico inicia a zona. Onda invalida (ONDA_INVALIDA) se a queda passar de
          drop_max OU a minima furar o proprio L_bc (item 2.5: "furar o nivel de graduacao = invalido" -- SEM
          o fator de tolerancia 0,75x que o V0 usa; aqui e literal).
  zona    igual ao V0: S/R/testes via `Zone`. Madura (armed) quando length >= zone_min_candles E o numero de
          testes completos esta entre wicks_min e wicks_max (item 2.5: "consolidacao de >= 12 candles com 1 a 3
          wicks de rejeicao inferior"). Sem o reset `test_break`/INVALIDADO de zona do V0: o prompt V1 so pede
          invalidacao no nivel da ONDA (queda/L_bc); a propria mecanica herdada de `Zone` ja deixa S/R se
          ajustarem a novas minimas mais baixas antes do 1o repique.
  gatilhos (item 2.6, zona madura, decisao no FECHAMENTO, execucao no open do candle seguinte -- feito por
          `simulate_v1.py`, nao aqui):
    (a) reacao_suporte: candle verde cujo fechamento fecha ACIMA DA MAXIMA do ultimo teste (wick) de suporte,
        com a minima desse teste dentro de S x (1 +- test_zone).
    (b) power_candle_rompimento: candle verde, amplitude >= power_atr_mult x ATR(20), fechando acima de R.
    (c) rompimento_volume: fechamento acima de R com volume >= vol_mult x a media de volume da caixa.
    Os 3 nao sao exclusivos: um candle pode disparar mais de um ao mesmo tempo (todos vao para `gatilho`).
  idade   filtro REAL (item 2.2 + INTERPRETACOES.md #10a): fora de age_window_days a zona nao gera ENTRADA
          (fica WATCHLIST/registro, nunca alerta) -- contado como `filtrado_idade` por quem chama o detector.
Uma decisao (ENTRADA) por zona; depois dela a zona recomeca. Nova maxima acima de P_peak = nova onda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .candles import Bar, tf_seconds
from .detector import Zone
from .params_v1 import ParamsV1

PHASE_NONE, PHASE_RUNNER, PHASE_PULLBACK = 0, 1, 2
GATILHOS = ("reacao_suporte", "power_candle_rompimento", "rompimento_volume")


@dataclass
class EventV1:
    kind: str            # RUNNER | FASE2 | TESTE | WATCHLIST | ONDA_INVALIDA | ENTRADA
    idx: int
    ts: int
    decision_ts: int
    data: dict[str, Any] = field(default_factory=dict)


class DetectorV1:
    def __init__(self, params: ParamsV1, tf: str, l_bc: Optional[float], grad_ts: Optional[float],
                 created_ts: Optional[float] = None):
        self.p = params
        self.tf = tf
        self.step = tf_seconds(tf)
        self.l_bc = l_bc
        self.grad_ts = grad_ts
        self.created_ts = created_ts
        self.bars: list[Bar] = []
        self.tr: list[float] = []
        self.events: list[EventV1] = []
        self.wave_no = 0
        self.zone_no = 0
        self.zone: Optional[Zone] = None
        self.armed = False
        self._new_wave(0)

    # -- estado da onda ---------------------------------------------------------
    def _new_wave(self, start: int) -> None:
        self.wave_no += 1
        self.wave_start = start
        self.phase = PHASE_NONE
        self.peak: Optional[float] = None
        self.peak_idx: Optional[int] = None
        if self.bars and start < len(self.bars):
            j = max(range(start, len(self.bars)), key=lambda k: self.bars[k].high)
            self.peak, self.peak_idx = self.bars[j].high, j
        self.trough: Optional[float] = None
        self.trough_idx: Optional[int] = None
        self.drop_idx: Optional[int] = None
        self.zone = None
        self.armed = False

    def _new_zone(self, start: int) -> None:
        self.zone_no += 1
        self.zone = Zone(self.zone_no, start)
        self.armed = False

    # -- utilidades ---------------------------------------------------------------
    def atr_before(self, i: int) -> Optional[float]:
        n = self.p.atr_period
        if i < n:
            return None
        return sum(self.tr[i - n:i]) / n

    def age_days(self, i: int) -> Optional[float]:
        if self.created_ts is None:
            return None
        return (self.bars[i].ts + self.step - self.created_ts) / 86400.0

    def grad_age_days(self, i: int) -> Optional[float]:
        if self.grad_ts is None:
            return None
        return (self.bars[i].ts + self.step - self.grad_ts) / 86400.0

    def in_age_window(self, i: int) -> bool:
        age = self.age_days(i)
        return age is not None and self.p.age_window_days[0] <= age <= self.p.age_window_days[1]

    def _emit(self, kind: str, i: int, **data: Any) -> EventV1:
        bar = self.bars[i]
        event = EventV1(kind, i, bar.ts, bar.ts + self.step, dict(data, onda=self.wave_no))
        self.events.append(event)
        return event

    def drop_pct(self) -> Optional[float]:
        if self.peak is None or self.trough is None:
            return None
        return 100.0 * (1.0 - self.trough / self.peak)

    def _kills_wave(self, low: float) -> bool:
        """Item 2.5: queda > drop_max OU a minima fura o proprio nivel de graduacao (L_bc) -- literal, sem
        fator de tolerancia (diferente do V0, que usa 0,75 x L_bc)."""
        assert self.peak is not None
        trough = low if self.trough is None else min(self.trough, low)
        return (1.0 - trough / self.peak > self.p.drop_max) or (self.l_bc is not None and trough < self.l_bc)

    def _recovered(self, z: Zone, close: float) -> bool:
        assert z.S is not None
        level = z.S * self.p.recover_mult if z.R is None else min((z.S + z.R) / 2.0, z.S * self.p.recover_mult)
        return close >= level and close > z.S * (1.0 + self.p.test_zone)

    # -- passo principal ------------------------------------------------------------
    def update(self, bar: Bar) -> list[EventV1]:
        if self.bars and bar.ts <= self.bars[-1].ts:
            raise ValueError("candles fora de ordem ou repetidos")
        i = len(self.bars)
        self.bars.append(bar)
        prev_close = self.bars[i - 1].close if i else bar.open
        self.tr.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        before = len(self.events)

        if self.phase == PHASE_PULLBACK and self.zone is not None and self.zone.start < i:
            self._check_zone(i)
        self._update_wave(i)
        if self.phase == PHASE_PULLBACK and self.zone is not None and self.zone.start <= i:
            self._update_zone(i)
        return self.events[before:]

    def _gatilhos(self, i: int, z: Zone) -> list[str]:
        """Os 3 gatilhos do item 2.6 (nao exclusivos). So avaliados com a zona madura (self.armed) e R fixado."""
        bar = self.bars[i]
        green = bar.close > bar.open
        hits: list[str] = []
        last = z.last_test
        if green and last is not None:
            wick_low = last["low"]
            if z.S * (1.0 - self.p.test_zone) <= wick_low <= z.S * (1.0 + self.p.test_zone) and bar.close > self.bars[last["low_idx"]].high:
                hits.append("reacao_suporte")
        if z.R is not None and bar.close > z.R:
            atr = self.atr_before(i)
            amp = bar.high - bar.low
            if green and atr and amp >= self.p.power_atr_mult * atr:
                hits.append("power_candle_rompimento")
            zone_bars = self.bars[z.anchor:i] if z.anchor is not None else []
            mean_vol = (sum(b.volume for b in zone_bars) / len(zone_bars)) if zone_bars else 0.0
            if mean_vol > 0 and bar.volume >= self.p.vol_mult * mean_vol:
                hits.append("rompimento_volume")
        return hits

    def _check_zone(self, i: int) -> None:
        bar = self.bars[i]
        z = self.zone
        assert z is not None and self.peak is not None
        if bar.high <= self.peak and self._kills_wave(bar.low):
            return                         # a onda morre neste candle (ONDA_INVALIDA a seguir): sem decisao
        if not self.armed or z.R is None:
            return
        hits = self._gatilhos(i, z)
        if not hits:
            return
        assert z.anchor is not None
        last = z.last_test
        atr = self.atr_before(i)
        amp = bar.high - bar.low
        min_wick_low = min((t["low"] for t in z.tests), default=z.S)
        stop = min_wick_low * (1.0 - self.p.stop_below_wick_pct)
        risk = (bar.close - stop) / bar.close if bar.close else None
        age = self.age_days(i)
        in_window = self.in_age_window(i)
        zone_bars = self.bars[z.anchor:i]
        mean_vol = sum(b.volume for b in zone_bars) / len(zone_bars) if zone_bars else None
        data = dict(
            gatilho=hits, P_peak=self.peak, peak_idx=self.peak_idx, peak_ts=self.bars[self.peak_idx].ts,
            L_bc=self.l_bc, queda_pct=self.drop_pct(), S=z.S, R=z.R, TOPO=self.peak,
            zona=z.zid, box_start=z.anchor, box_end=i - 1, box_start_ts=self.bars[z.anchor].ts, box_len=i - z.anchor,
            n_testes=len(z.tests), testes=[dict(t) for t in z.tests], min_wick_low=min_wick_low,
            stop=stop, risco_pct=None if risk is None else 100.0 * risk,
            risco_fora_da_faixa=bool(risk is not None and not (self.p.risk_min <= risk <= self.p.risk_max)),
            close=bar.close, atr=atr, amp_atr=(amp / atr) if atr else None,
            vol_ratio=(bar.volume / mean_vol) if mean_vol else None,
            idade_dias=age, idade_grad_dias=self.grad_age_days(i), na_janela_idade=in_window,
            dentro_da_faixa_de_pico_atributo=bool(self.peak >= self.p.peak_attr_mc),
        )
        self._new_zone(i + 1)   # uma decisao por zona
        if not in_window:
            self._emit("FORA_DA_IDADE", i, **data)
            return
        self._emit("ENTRADA", i, **data)

    def _update_wave(self, i: int) -> None:
        bar = self.bars[i]
        if self.peak is None or bar.high > self.peak:
            if self.phase == PHASE_PULLBACK:
                self._new_wave(self.wave_start)
            self.peak, self.peak_idx = bar.high, i
            self.trough, self.trough_idx = None, None
            if self.phase == PHASE_NONE and self.peak >= self.p.runner_min_mc:
                self.phase = PHASE_RUNNER
                self._emit("RUNNER", i, P_peak=self.peak, atributo_pico_500k=bool(self.peak >= self.p.peak_attr_mc))
            return
        if self.phase == PHASE_NONE:
            return
        if self.trough is None or bar.low < self.trough:
            self.trough, self.trough_idx = bar.low, i
        drop = 1.0 - self.trough / self.peak
        if self.phase == PHASE_RUNNER and drop >= self.p.drop_min:
            self.phase = PHASE_PULLBACK
            self.drop_idx = i
            self._emit("FASE2", i, P_peak=self.peak, queda_pct=100.0 * drop)
            self._new_zone(i)
        if self.phase == PHASE_PULLBACK:
            dead = drop > self.p.drop_max
            below = self.l_bc is not None and self.trough < self.l_bc
            if dead or below:
                motivo = f"queda passou de {100 * self.p.drop_max:.0f}%" if dead else "furou o nivel de graduacao (L_bc)"
                self._emit("ONDA_INVALIDA", i, motivo=motivo, P_peak=self.peak, queda_pct=100.0 * drop,
                           minima=self.trough, L_bc=self.l_bc)
                self._new_wave(i + 1)

    def _update_zone(self, i: int) -> None:
        bar = self.bars[i]
        z = self.zone
        assert z is not None
        if z.S is None or bar.low < z.S:
            z.S, z.S_idx = bar.low, i
            if z.anchor is None:
                z.R, z.R_idx = None, None
        ref = z.anchor if z.anchor is not None else z.S_idx
        if ref is not None and i > ref and (z.R is None or bar.high > z.R):
            z.R, z.R_idx = bar.high, i
        region = z.S * (1.0 + self.p.test_zone)
        if z.state == "fundo":
            if self._recovered(z, bar.close):
                z.anchor = z.S_idx
                z.state = "dentro"
                if z.anchor == i and (z.R is None or bar.high > z.R):
                    z.R, z.R_idx = bar.high, i
        else:
            if z.state == "dentro" and bar.low <= region:
                z.state = "testando"
                z.cur = {"start": i, "low": bar.low, "low_idx": i, "low_vol": bar.volume}
            elif z.state == "testando" and z.cur is not None and bar.low < z.cur["low"]:
                z.cur["low"], z.cur["low_idx"], z.cur["low_vol"] = bar.low, i, bar.volume
            if z.state == "testando" and z.cur is not None and self._recovered(z, bar.close):
                test = dict(z.cur, end=i)
                z.tests.append(test)
                z.cur = None
                z.state = "dentro"
                self._emit("TESTE", i, n=len(z.tests), minima=test["low"], minima_idx=test["low_idx"],
                           inicio=test["start"], S=z.S, R=z.R, zona=z.zid)
        armed = (z.anchor is not None and z.length(i) >= self.p.zone_min_candles
                 and self.p.wicks_min <= len(z.tests) <= self.p.wicks_max)
        if armed and not self.armed:
            self._emit("WATCHLIST", i, P_peak=self.peak, queda_pct=self.drop_pct(), L_bc=self.l_bc, S=z.S, R=z.R,
                       n_testes=len(z.tests), box_len=z.length(i), idade_dias=self.age_days(i), zona=z.zid)
        self.armed = armed


def run(bars: list[Bar], params: ParamsV1, tf: str, l_bc: Optional[float], grad_ts: Optional[float],
        created_ts: Optional[float] = None) -> DetectorV1:
    det = DetectorV1(params, tf, l_bc, grad_ts, created_ts)
    for bar in bars:
        det.update(bar)
    return det
