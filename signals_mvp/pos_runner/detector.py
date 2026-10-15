"""Detector causal incremental do POS-RUNNER-V0 — o MESMO codigo no backtest (Parte A) e no bot (Parte B).

Recebe candles FECHADOS de um timeframe, um por vez (`update`). Cada decisao no candle i usa so os candles
0..i. Nada do futuro: pico, queda, caixa (S/R), wicks e rompimento sao recalculados de forma incremental.
Um teste prova isso rodando o detector em todos os prefixos da serie.

Fases (por "onda"):
  0/1  runner: pico de MC desde o inicio da onda (`P_peak`); fase 1 quando P_peak >= piso (300k).
  2    pullback: a MC cai ate <= (1 - drop_min) x P_peak. Onda invalida se a queda passar de drop_max ou a
       minima furar L_bc (MC na graduacao). Depois do 1o repique, a caixa e o maior trecho RECENTE contido
       (R/S <= box_max_ratio): S = minima, R = maxima. Arma com >= box_min_candles e >= wick_min wicks.
  3    entrada: fechamento > R com volume >= breakout_vol_mult x media da caixa. Executa no open seguinte
       (quem executa e o simulador). Um candle "absurdo" (cobre >= absurd_frac de R -> P_peak) nao entra.
Uma decisao de entrada por onda. Nova maxima acima de P_peak = nova onda (o padrao pode se repetir).

Interpretacoes do texto do handoff (a confirmar no Passo 0, estao no relatorio):
  - "caixa depois da queda, R excluindo o 1o repique": o 1o repique e o 1o topo fractal (k candles de cada
    lado) depois que a queda chegou a 80%; a caixa so comeca depois dele. Antes disso nao ha entrada (o que
    tambem cumpre "nao entrar no primeiro pulo").
  - "caixa contida R/S <= 3": a caixa e o maior trecho RECENTE (sufixo) depois do 1o repique que cabe em
    R/S <= 3. Picos antigos que estouram a razao saem da caixa em vez de matar o setup.
  - volume medio da caixa inclui os intervalos sem negociacao (volume 0): e volume por intervalo de tempo.
  - ATR(20) usa os 20 candles ANTERIORES ao candle avaliado (o power candle nao infla o proprio ATR).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from .candles import Bar, tf_seconds
from .params import Params

PHASE_NONE, PHASE_RUNNER, PHASE_PULLBACK = 0, 1, 2


@dataclass
class Event:
    kind: str            # RUNNER | FASE2 | WATCHLIST | INVALIDADO | ONDA_INVALIDA | ENTRADA | ABSURDO
    idx: int             # indice do candle que gerou o evento
    ts: int              # inicio desse candle (UTC)
    decision_ts: int     # fim desse candle: quando o evento passa a ser conhecido
    data: dict[str, Any] = field(default_factory=dict)


def is_hammer(bar: Bar, body_mult: float) -> bool:
    """Pavio inferior >= body_mult x corpo (e > 0). Candle preenchido (sem negociacao) nunca conta."""
    if bar.filled:
        return False
    lower = min(bar.open, bar.close) - bar.low
    body = abs(bar.close - bar.open)
    return lower > 0 and lower >= body_mult * body


@dataclass
class BoxState:
    start: int
    end: int             # ultimo candle da caixa (inclusive)
    S: float
    R: float
    mean_vol: float
    wicks: list[int]     # indices dos candles-wick (ordem de tempo)

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def ratio(self) -> float:
        return self.R / self.S if self.S > 0 else float("inf")


class Detector:
    def __init__(self, params: Params, tf: str, l_bc: Optional[float], grad_ts: Optional[float]):
        self.p = params
        self.tf = tf
        self.step = tf_seconds(tf)
        self.l_bc = l_bc
        self.grad_ts = grad_ts
        self.bars: list[Bar] = []
        self.hammer: list[bool] = []
        self.tr: list[float] = []
        self.events: list[Event] = []
        self.wave_no = 0
        self.entries = 0
        self.primary_done = False
        self._new_wave(0)

    # -- estado da onda -------------------------------------------------------
    def _new_wave(self, start: int) -> None:
        self.wave_no += 1
        self.wave_start = start
        self.phase = PHASE_NONE
        self.peak: Optional[float] = None
        self.peak_idx: Optional[int] = None
        # topo real (maxima) desde o inicio da onda: e o "ultimo topo" do alvo
        self.peak_wick: Optional[float] = None
        self.peak_wick_idx: Optional[int] = None
        if self.bars and start < len(self.bars):
            j = max(range(start, len(self.bars)), key=lambda k: self.bars[k].high)
            self.peak_wick, self.peak_wick_idx = self.bars[j].high, j
        self.trough: Optional[float] = None
        self.trough_idx: Optional[int] = None
        self.drop_idx: Optional[int] = None
        self.bounce_idx: Optional[int] = None
        self.box_floor: Optional[int] = None
        self.armed = False
        self._reset_box(None)

    def _reset_box(self, floor: Optional[int]) -> None:
        self.box_floor = floor
        self.win_start = floor
        self.maxq: deque[int] = deque()
        self.minq: deque[int] = deque()
        self.vol_sum = 0.0
        self.box: Optional[BoxState] = None
        self.decided = False           # esta caixa ja gerou uma decisao (ENTRADA/ABSURDO)

    # -- utilidades -------------------------------------------------------------
    def _hi(self, i: int) -> float:
        """Topo do candle na medida escolhida: pavio (maxima), fechamento ou corpo (max(abertura, fechamento))."""
        b = self.bars[i]
        if self.p.measure == "wick":
            return b.high
        if self.p.measure == "close":
            return b.close
        return max(b.open, b.close)

    def _lo(self, i: int) -> float:
        b = self.bars[i]
        if self.p.measure == "wick":
            return b.low
        if self.p.measure == "close":
            return b.close
        return min(b.open, b.close)

    def target_peak(self) -> float:
        """Pico usado no alvo e no teste de candle absurdo: o topo real (maxima) ou o da medida da estrutura."""
        assert self.peak is not None
        if self.p.tp_reference == "wick" and self.peak_wick is not None:
            return max(self.peak_wick, self.peak)
        return self.peak

    def atr_before(self, i: int) -> Optional[float]:
        n = self.p.atr_period
        if i < n:
            return None
        return sum(self.tr[i - n:i]) / n

    def age_days(self, i: int) -> Optional[float]:
        if self.grad_ts is None:
            return None
        return (self.bars[i].ts + self.step - self.grad_ts) / 86400.0

    def _emit(self, kind: str, i: int, **data: Any) -> Event:
        bar = self.bars[i]
        event = Event(kind, i, bar.ts, bar.ts + self.step, dict(data, onda=self.wave_no))
        self.events.append(event)
        return event

    # -- caixa (sufixo contido com filas monotonicas) ----------------------------
    def _box_push(self, i: int) -> None:
        bars = self.bars
        hi_of, lo_of = self._hi, self._lo
        while self.maxq and hi_of(self.maxq[-1]) <= hi_of(i):
            self.maxq.pop()
        self.maxq.append(i)
        while self.minq and lo_of(self.minq[-1]) >= lo_of(i):
            self.minq.pop()
        self.minq.append(i)
        self.vol_sum += bars[i].volume
        while self.win_start is not None and self.win_start < i:
            hi = hi_of(self.maxq[0])
            lo = lo_of(self.minq[0])
            if lo > 0 and hi / lo <= self.p.box_max_ratio:
                break
            self.vol_sum -= bars[self.win_start].volume
            self.win_start += 1
            if self.maxq[0] < self.win_start:
                self.maxq.popleft()
            if self.minq[0] < self.win_start:
                self.minq.popleft()
        start, end = self.win_start, i
        S = lo_of(self.minq[0])
        R = hi_of(self.maxq[0])
        zone_top = S * (1.0 + self.p.wick_zone)
        if self.p.measure == "wick":
            # S e a minima da caixa: a wick toca a zona [S, S + 5%] e fecha acima de S
            wicks = [j for j in range(start, end + 1) if self.hammer[j] and bars[j].low <= zone_top and bars[j].close > S]
        else:
            # S pelos corpos/fechamentos: a wick toca a zona ou fura S por baixo e fecha de volta >= S
            wicks = [j for j in range(start, end + 1) if self.hammer[j] and bars[j].low <= zone_top and bars[j].close >= S]
        self.box = BoxState(start, end, S, R, self.vol_sum / (end - start + 1), wicks)

    def _box_armed(self) -> bool:
        box = self.box
        return box is not None and box.length >= self.p.box_min_candles and len(box.wicks) >= self.p.wick_min

    # -- passo principal ------------------------------------------------------------
    def update(self, bar: Bar) -> list[Event]:
        if self.bars and bar.ts <= self.bars[-1].ts:
            raise ValueError("candles fora de ordem ou repetidos")
        i = len(self.bars)
        self.bars.append(bar)
        self.hammer.append(is_hammer(bar, self.p.wick_body_mult))
        prev_close = self.bars[i - 1].close if i else bar.open
        self.tr.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        before = len(self.events)

        # 1) decisoes sobre a caixa formada ate o candle anterior
        if self.phase == PHASE_PULLBACK and self.box is not None:
            self._check_box(i)

        # 2) pico / queda / fases com o candle atual
        self._update_wave(i)

        # 3) caixa: 1o repique e sufixo contido
        if self.phase == PHASE_PULLBACK:
            self._update_box(i)
        return self.events[before:]

    def _check_box(self, i: int) -> None:
        bar = self.bars[i]
        box = self.box
        assert box is not None
        armed = self._box_armed()
        if self.decided:
            return
        if armed and box.wicks:
            last_low = self.bars[box.wicks[-1]].low
            if bar.close < last_low * (1.0 - self.p.wick_break):
                self._emit("INVALIDADO", i, motivo="fechou abaixo da minima da ultima wick", S=box.S, R=box.R,
                           wick_low=last_low, n_wicks=len(box.wicks))
                self.armed = False
                # setup perdido: uma caixa nova so comeca DEPOIS deste candle (precisa amadurecer de novo)
                self._reset_box(i + 1)
                return
        if not armed:
            return
        if bar.close <= box.R:
            return
        vol_ratio = bar.volume / box.mean_vol if box.mean_vol > 0 else float("inf")
        if vol_ratio < self.p.breakout_vol_mult:
            return
        assert self.peak is not None and self.peak_idx is not None
        atr = self.atr_before(i)
        amp = bar.high - bar.low
        amp_atr = amp / atr if atr else None
        power = bool(atr) and amp >= self.p.power_atr_mult * atr
        top = self.target_peak()
        span = top - box.R
        coverage = (bar.high - box.R) / span if span > 0 else float("inf")
        last_wick = box.wicks[-1]
        last_wick_low = self.bars[last_wick].low
        age = self.age_days(i)
        window = self.p.age_window(self.tf)
        in_window = window is None or (age is not None and window[0] <= age <= window[1])
        data = dict(
            P_peak=self.peak, peak_idx=self.peak_idx, peak_ts=self.bars[self.peak_idx].ts, L_bc=self.l_bc,
            P_peak_topo=top, topo_idx=self.peak_wick_idx if self.p.tp_reference == "wick" else self.peak_idx,
            queda_pct=100.0 * (1.0 - self.trough / self.peak) if self.trough else None,
            S=box.S, R=box.R, R_S=box.ratio, box_start=box.start, box_end=box.end, box_len=box.length,
            box_start_ts=self.bars[box.start].ts, n_wicks=len(box.wicks), wicks=list(box.wicks),
            last_wick_idx=last_wick, last_wick_low=last_wick_low,
            stop=last_wick_low * (1.0 - self.p.stop_below_wick), tp=self.p.tp_frac_of_peak * top,
            close=bar.close, vol_ratio=vol_ratio, atr=atr, amp_atr=amp_atr, power_candle=power,
            cobertura=coverage, idade_dias=age, na_janela=in_window, drop_idx=self.drop_idx,
            bounce_idx=self.bounce_idx,
        )
        # uma decisao por caixa: depois dela a caixa recomeca (um setup seguinte precisa amadurecer de novo e
        # vira diagnostico — so o 1o setup elegivel por token e timeframe e primario)
        self._reset_box(i + 1)
        self.armed = False
        if coverage >= self.p.absurd_frac:
            self._emit("ABSURDO", i, **data)
            return
        primary = in_window and not self.primary_done
        if primary:
            self.primary_done = True
        self.entries += 1
        self._emit("ENTRADA", i, primario=primary, n_entrada=self.entries, **data)

    def _update_wave(self, i: int) -> None:
        hi, lo = self._hi(i), self._lo(i)
        if i >= self.wave_start and (self.peak_wick is None or self.bars[i].high > self.peak_wick):
            self.peak_wick, self.peak_wick_idx = self.bars[i].high, i
        if self.peak is None or hi > self.peak:
            if self.phase == PHASE_PULLBACK:
                # passou do pico: a onda anterior acabou (com ou sem entrada); nova onda a partir daqui
                self._new_wave(self.wave_start)
            self.peak, self.peak_idx = hi, i
            self.trough, self.trough_idx = None, None
            if self.phase == PHASE_NONE and self.peak >= self.p.runner_min_mc:
                self.phase = PHASE_RUNNER
                self._emit("RUNNER", i, P_peak=self.peak)
            return
        if self.phase == PHASE_NONE:
            return
        if self.trough is None or lo < self.trough:
            self.trough, self.trough_idx = lo, i
        drop = 1.0 - self.trough / self.peak
        if self.phase == PHASE_RUNNER and drop >= self.p.drop_min:
            self.phase = PHASE_PULLBACK
            self.drop_idx = i
            self._emit("FASE2", i, P_peak=self.peak, queda_pct=100.0 * drop)
        if self.phase == PHASE_PULLBACK:
            broke_lbc = self.l_bc is not None and self.trough <= self.l_bc
            if drop > self.p.drop_max or broke_lbc:
                motivo = "minima furou L_bc" if broke_lbc else f"queda passou de {100 * self.p.drop_max:.0f}%"
                self._emit("ONDA_INVALIDA", i, motivo=motivo, P_peak=self.peak, queda_pct=100.0 * drop,
                           minima=self.trough, L_bc=self.l_bc)
                self._new_wave(i + 1)

    def _update_box(self, i: int) -> None:
        if self.box_floor is None:
            k = self.p.bounce_fractal
            j = i - k
            assert self.drop_idx is not None
            if j >= self.drop_idx and j - k >= 0:
                hj = self.bars[j].high
                left = all(self.bars[x].high < hj for x in range(j - k, j))
                right = all(self.bars[x].high < hj for x in range(j + 1, i + 1))
                if left and right:
                    self.bounce_idx = j
                    self._reset_box(j + 1)
                    for x in range(j + 1, i + 1):
                        self._box_push(x)
            return
        if i < self.box_floor:
            return
        self._box_push(i)
        armed = self._box_armed()
        if armed and not self.armed and not self.decided:
            box = self.box
            assert box is not None and self.peak is not None
            self._emit("WATCHLIST", i, P_peak=self.peak, queda_pct=100.0 * (1.0 - (self.trough or self.peak) / self.peak),
                       L_bc=self.l_bc, S=box.S, R=box.R, n_wicks=len(box.wicks), box_len=box.length,
                       idade_dias=self.age_days(i))
        self.armed = armed


def run(bars: list[Bar], params: Params, tf: str, l_bc: Optional[float], grad_ts: Optional[float]) -> Detector:
    det = Detector(params, tf, l_bc, grad_ts)
    for bar in bars:
        det.update(bar)
    return det
