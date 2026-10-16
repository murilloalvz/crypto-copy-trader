"""Detector causal incremental do POS-RUNNER-V0 — o MESMO codigo no Passo 0, no backtest (Parte A) e no bot (Parte B).

Recebe candles FECHADOS de um timeframe, um por vez (`update`). A decisao no candle i usa so os candles 0..i (um
teste roda o detector em todos os prefixos da serie e exige as mesmas decisoes).

Regras = decisoes do operador de 2026-10-16 (o que ele nao respondeu segue a opcao mais conservadora). Pico, queda,
suporte e resistencia pelos EXTREMOS dos candles (maxima/minima: o preco negociou ali); rompimento, recuperacao e
invalidacao pelo FECHAMENTO.

  fase 1  runner: pico (maxima) desde o inicio da onda, P_peak >= 300k. A faixa do pico e atributo.
  fase 2  a minima desde o pico chega a <= 0,20 x P_peak (queda >= 80%): a ZONA comeca nesse candle. Onda invalida
          (moeda morta) se a queda passar de 90% ou se o fundo ficar abaixo de 0,75 x L_bc.
  zona    S = minima da zona. O 1o REPIQUE (1o fechamento que recupera — ver abaixo) fixa o FUNDO da zona; R = maxima
          das tentativas de subida depois do fundo, INCLUINDO o 1o repique (se o proprio candle do fundo ja fecha
          recuperado — martelo —, a maxima dele entra em R). Antes do 1o repique nao ha R fixo.
  testes  teste de suporte = episodio de 1 ou muitos candles: estando o preco dentro da zona (depois de uma
          recuperacao), a minima desce a <= S x 1,10 (regiao do suporte) e depois o preco RECUPERA: fecha
          >= min((S + R) / 2, 1,25 x S) e acima da regiao do suporte. Sem limite de candles; o martelo de 1 candle e
          caso particular; episodios distintos sao separados por uma recuperacao completa. O fundo inicial e o
          1o repique nao sao teste. Fechamento < minima do ultimo teste x 0,98 = setup morto (a zona recomeca).
  fase 3  entrada: zona madura ate o candle anterior (>= 12 candles desde o fundo e >= 1 teste completo) e
          fechamento acima de R (R ate o candle anterior). Sem exigencia de volume (atributo). Veto: candle absurdo
          (a maxima cobre >= 50% do caminho de R ate P_peak). Power candle no rompimento = atributo. Comprar o 1o
          repique e impossivel por construcao: ele forma R e nao ha teste antes dele.
  idade   2-7 dias desde a CRIACAO do token, na entrada: filtro do sinal primario (fora = diagnostico). Sem a data de
          criacao a idade fica desconhecida e o setup nao e primario (falta de dado fica explicita).
Uma decisao (ENTRADA ou ABSURDO) por zona; depois dela a zona recomeca. Nova maxima acima de P_peak = nova onda.
Candle cuja minima mata a onda (queda > 90% ou fundo < 0,75 x L_bc) nunca e decisao: a onda morre nele.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .candles import Bar, tf_seconds
from .params import Params

PHASE_NONE, PHASE_RUNNER, PHASE_PULLBACK = 0, 1, 2


@dataclass
class Event:
    kind: str            # RUNNER | FASE2 | TESTE | WATCHLIST | INVALIDADO | ONDA_INVALIDA | ENTRADA | ABSURDO
    idx: int             # indice do candle que gerou o evento
    ts: int              # inicio desse candle (UTC)
    decision_ts: int     # fim desse candle: quando o evento passa a ser conhecido
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Zone:
    zid: int                                   # numero da zona na serie (chave de alerta)
    start: int                                 # 1o candle da zona
    S: Optional[float] = None                  # minima da zona (suporte)
    S_idx: Optional[int] = None
    anchor: Optional[int] = None               # fundo fixado pelo 1o repique
    R: Optional[float] = None                  # maxima depois do fundo (provisoria antes do 1o repique)
    R_idx: Optional[int] = None
    state: str = "fundo"                       # fundo (antes do 1o repique) | dentro | testando
    tests: list[dict[str, Any]] = field(default_factory=list)     # testes completos: start, end, low, low_idx
    cur: Optional[dict[str, Any]] = None       # teste em andamento

    def length(self, last: int) -> int:
        """Candles desde o fundo ate `last` (inclusive)."""
        return 0 if self.anchor is None else last - self.anchor + 1

    @property
    def last_test(self) -> Optional[dict[str, Any]]:
        return self.tests[-1] if self.tests else None


class Detector:
    def __init__(self, params: Params, tf: str, l_bc: Optional[float], grad_ts: Optional[float],
                 created_ts: Optional[float] = None):
        self.p = params
        self.tf = tf
        self.step = tf_seconds(tf)
        self.l_bc = l_bc
        self.grad_ts = grad_ts
        self.created_ts = created_ts
        self.bars: list[Bar] = []
        self.tr: list[float] = []
        self.events: list[Event] = []
        self.wave_no = 0
        self.zone_no = 0
        self.entries = 0
        self.primary_done = False
        self.zone: Optional[Zone] = None
        self.armed = False
        self._new_wave(0)

    # -- medida do pico/queda (EMENDA 2026-10-16: "extremos" ou "fechamentos") -----------
    def _hi(self, bar: Bar) -> float:
        return bar.close if self.p.queda_medida == "fechamentos" else bar.high

    def _lo(self, bar: Bar) -> float:
        return bar.close if self.p.queda_medida == "fechamentos" else bar.low

    # -- estado da onda -------------------------------------------------------
    def _new_wave(self, start: int) -> None:
        self.wave_no += 1
        self.wave_start = start
        self.phase = PHASE_NONE
        self.peak: Optional[float] = None
        self.peak_idx: Optional[int] = None
        if self.bars and start < len(self.bars):
            j = max(range(start, len(self.bars)), key=lambda k: self._hi(self.bars[k]))
            self.peak, self.peak_idx = self._hi(self.bars[j]), j
        self.trough: Optional[float] = None
        self.trough_idx: Optional[int] = None
        self.drop_idx: Optional[int] = None
        self.zone = None
        self.armed = False

    def _new_zone(self, start: int) -> None:
        self.zone_no += 1
        self.zone = Zone(self.zone_no, start)
        self.armed = False

    # -- utilidades -------------------------------------------------------------
    def atr_before(self, i: int) -> Optional[float]:
        n = self.p.atr_period
        if i < n:
            return None
        return sum(self.tr[i - n:i]) / n

    def age_days(self, i: int) -> Optional[float]:
        """Idade desde a CRIACAO do token no fim do candle i (None sem a data de criacao)."""
        if self.created_ts is None:
            return None
        return (self.bars[i].ts + self.step - self.created_ts) / 86400.0

    def grad_age_days(self, i: int) -> Optional[float]:
        if self.grad_ts is None:
            return None
        return (self.bars[i].ts + self.step - self.grad_ts) / 86400.0

    def in_age_window(self, i: int) -> bool:
        window = self.p.age_window(self.tf)
        age = self.age_days(i)
        return window is None or (age is not None and window[0] <= age <= window[1])

    def _emit(self, kind: str, i: int, **data: Any) -> Event:
        bar = self.bars[i]
        event = Event(kind, i, bar.ts, bar.ts + self.step, dict(data, onda=self.wave_no))
        self.events.append(event)
        return event

    def drop_pct(self) -> Optional[float]:
        if self.peak is None or self.trough is None:
            return None
        return 100.0 * (1.0 - self.trough / self.peak)

    def _kills_wave(self, low: float) -> bool:
        """A minima `low` leva a queda acima do teto ou o fundo abaixo de 0,75 x L_bc (a onda morre neste candle)."""
        assert self.peak is not None
        trough = low if self.trough is None else min(self.trough, low)
        return (1.0 - trough / self.peak > self.p.drop_max
                or (self.l_bc is not None and trough < self.p.support_min_lbc * self.l_bc))

    def _recovered(self, z: Zone, close: float) -> bool:
        """Recuperacao: fecha >= min((S+R)/2, 1,25 x S) e acima da regiao do suporte (S x 1,10)."""
        assert z.S is not None
        level = z.S * self.p.recover_mult if z.R is None else min((z.S + z.R) / 2.0, z.S * self.p.recover_mult)
        return close >= level and close > z.S * (1.0 + self.p.test_zone)

    # -- passo principal ------------------------------------------------------------
    def update(self, bar: Bar) -> list[Event]:
        if self.bars and bar.ts <= self.bars[-1].ts:
            raise ValueError("candles fora de ordem ou repetidos")
        i = len(self.bars)
        self.bars.append(bar)
        prev_close = self.bars[i - 1].close if i else bar.open
        self.tr.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
        before = len(self.events)

        # 1) decisoes sobre a zona formada ate o candle anterior
        if self.phase == PHASE_PULLBACK and self.zone is not None and self.zone.start < i:
            self._check_zone(i)

        # 2) pico / queda / fases com o candle atual
        self._update_wave(i)

        # 3) zona: suporte, resistencia, testes
        if self.phase == PHASE_PULLBACK and self.zone is not None and self.zone.start <= i:
            self._update_zone(i)
        return self.events[before:]

    def _check_zone(self, i: int) -> None:
        bar = self.bars[i]
        z = self.zone
        assert z is not None
        assert self.peak is not None
        if self._hi(bar) <= self.peak and self._kills_wave(self._lo(bar)):
            return                         # a onda morre neste candle (ONDA_INVALIDA logo a seguir): nao ha decisao
        last = z.last_test
        if last is not None and bar.close < last["low"] * (1.0 - self.p.test_break):
            self._emit("INVALIDADO", i, motivo="fechou abaixo da minima do ultimo teste", S=z.S, R=z.R,
                       teste_minima=last["low"], n_testes=len(z.tests), zona=z.zid)
            self._new_zone(i + 1)          # setup morto: uma zona nova so comeca depois deste candle
            return
        if not self.armed or z.R is None or bar.close <= z.R:
            return
        assert self.peak is not None and self.peak_idx is not None and z.anchor is not None and last is not None
        atr = self.atr_before(i)
        amp = bar.high - bar.low
        power = bool(atr) and amp >= self.p.power_atr_mult * atr
        span = self.peak - z.R
        coverage = (bar.high - z.R) / span if span > 0 else float("inf")
        zone_bars = self.bars[z.anchor:i]
        mean_vol = sum(b.volume for b in zone_bars) / len(zone_bars)
        age = self.age_days(i)
        in_window = self.in_age_window(i)
        data = dict(
            P_peak=self.peak, faixa_pico=self.p.peak_band(self.peak), peak_idx=self.peak_idx,
            peak_ts=self.bars[self.peak_idx].ts, L_bc=self.l_bc, queda_pct=self.drop_pct(),
            S=z.S, R=z.R, R_S=z.R / z.S if z.S else None,
            S_sobre_Lbc=(z.S / self.l_bc) if (self.l_bc and z.S) else None,
            S_acima_100k=bool(z.S is not None and z.S >= self.p.support_attr_mc),
            zona=z.zid, box_start=z.anchor, box_end=i - 1, box_start_ts=self.bars[z.anchor].ts, box_len=i - z.anchor,
            n_testes=len(z.tests), testes=[dict(t) for t in z.tests], ultimo_teste_minima=last["low"],
            ultimo_teste_idx=last["low_idx"], stop=last["low"] * (1.0 - self.p.stop_below_test),
            tp=self.p.tp_frac_of_peak * self.peak, close=bar.close,
            vol_ratio=(bar.volume / mean_vol) if mean_vol > 0 else None, atr=atr, amp_atr=(amp / atr) if atr else None,
            power_candle=power, cobertura=coverage, idade_dias=age, idade_grad_dias=self.grad_age_days(i),
            na_janela=in_window, drop_idx=self.drop_idx,
            # EMENDA 2026-10-16 (atributo secundario, nunca filtro): volume do candle do ultimo teste de suporte
            # (candle que fixou a minima testada) / media de volume dos candles da zona madura (mesma zona_bars/
            # mean_vol do vol_ratio do rompimento acima -- so troca o candle do numerador).
            teste_vol_ratio=((last.get("low_vol") / mean_vol) if (mean_vol > 0 and last.get("low_vol") is not None) else None),
        )
        # uma decisao por zona: depois dela a zona recomeca (setup seguinte = diagnostico; so o 1o setup elegivel por
        # token e timeframe e primario)
        self._new_zone(i + 1)
        if coverage >= self.p.absurd_frac:
            self._emit("ABSURDO", i, **data)
            return
        primary = in_window and not self.primary_done
        if primary:
            self.primary_done = True
        self.entries += 1
        self._emit("ENTRADA", i, primario=primary, n_entrada=self.entries, **data)

    def _update_wave(self, i: int) -> None:
        bar = self.bars[i]
        hi, lo = self._hi(bar), self._lo(bar)
        if self.peak is None or hi > self.peak:
            if self.phase == PHASE_PULLBACK:
                # passou do pico: a onda anterior acabou (com ou sem entrada); nova onda a partir daqui
                self._new_wave(self.wave_start)
            self.peak, self.peak_idx = hi, i
            self.trough, self.trough_idx = None, None
            if self.phase == PHASE_NONE and self.peak >= self.p.runner_min_mc:
                self.phase = PHASE_RUNNER
                self._emit("RUNNER", i, P_peak=self.peak, faixa_pico=self.p.peak_band(self.peak))
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
            self._new_zone(i)
        if self.phase == PHASE_PULLBACK:
            dead = drop > self.p.drop_max
            below = self.l_bc is not None and self.trough < self.p.support_min_lbc * self.l_bc
            if dead or below:
                motivo = (f"queda passou de {100 * self.p.drop_max:.0f}% (moeda morta)" if dead
                          else f"fundo abaixo de {self.p.support_min_lbc:.2f} x L_bc")
                self._emit("ONDA_INVALIDA", i, motivo=motivo, P_peak=self.peak, queda_pct=100.0 * drop,
                           minima=self.trough, L_bc=self.l_bc)
                self._new_wave(i + 1)

    def _update_zone(self, i: int) -> None:
        bar = self.bars[i]
        z = self.zone
        assert z is not None
        # suporte e resistencia
        if z.S is None or bar.low < z.S:
            z.S, z.S_idx = bar.low, i
            if z.anchor is None:          # antes do 1o repique o fundo ainda desce: R provisoria recomeca
                z.R, z.R_idx = None, None
        ref = z.anchor if z.anchor is not None else z.S_idx
        if ref is not None and i > ref and (z.R is None or bar.high > z.R):
            z.R, z.R_idx = bar.high, i
        # recuperacao e testes
        region = z.S * (1.0 + self.p.test_zone)
        if z.state == "fundo":
            if self._recovered(z, bar.close):
                z.anchor = z.S_idx        # o 1o repique fixa o fundo; R = maxima desde ele (inclui o repique)
                z.state = "dentro"
                if z.anchor == i and (z.R is None or bar.high > z.R):
                    z.R, z.R_idx = bar.high, i     # o proprio candle do fundo e o 1o repique (martelo)
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
        armed = z.anchor is not None and z.length(i) >= self.p.zone_min_candles and len(z.tests) >= self.p.tests_min
        if armed and not self.armed:
            self._emit("WATCHLIST", i, P_peak=self.peak, queda_pct=self.drop_pct(), L_bc=self.l_bc, S=z.S, R=z.R,
                       n_testes=len(z.tests), box_len=z.length(i), idade_dias=self.age_days(i), zona=z.zid)
        self.armed = armed


def run(bars: list[Bar], params: Params, tf: str, l_bc: Optional[float], grad_ts: Optional[float],
        created_ts: Optional[float] = None) -> Detector:
    det = Detector(params, tf, l_bc, grad_ts, created_ts)
    for bar in bars:
        det.update(bar)
    return det
