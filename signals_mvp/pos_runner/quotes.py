"""Conversao para USD a partir do preco do pool EM TOKEN DE COTACAO (fonte primaria) x cotacao/USD de referencia.

Por que nao usar direto o OHLCV em USD do GeckoTerminal: medido em 2026-10-15 no pool ZILLIONS/ZEC (cotado em
ZEC), o USD do GT ficou "travado" em ~1,0M de MC por um dia inteiro (18->19/09) enquanto a taxa real do pool
(em ZEC) caiu ~80%. A taxa em token de cotacao vem direto dos swaps do pool; o USD so entra pela serie de
referencia da cotacao (SOL/USDC, ZEC/USDC...). O USD do GT continua util como CONFERENCIA (`compare_usd`).

Conversao de cada candle: preco em cotacao x (cotacao/USD no FECHAMENTO do candle), interpolado dentro da hora
da serie de referencia de 1h. O erro e o quanto a cotacao se move dentro do candle (SOL: ~1% em 4h), pequeno
perto do movimento de uma memecoin. Sem referencia no instante = candle sem USD (fica de fora, nunca inventado).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable, Optional

from .candles import Bar, OhlcvStore, tf_seconds

SOL_MINT = "So11111111111111111111111111111111111111112"
STABLES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB": "USD1",
}
# pools de referencia (cotacao, lado do token no pool). SOL: Orca SOL/USDC (liquidez ~US$28M em 2026-10-15)
REFERENCE_POOLS: dict[str, tuple[str, str]] = {
    SOL_MINT: ("Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE", "base"),
}


@dataclass
class UsdSeries:
    """Cotacao/USD de 1h: `at(ts)` interpola dentro da hora; None fora da cobertura."""

    ts: list[int]
    opens: list[float]
    closes: list[float]
    step: int = 3600
    constant: Optional[float] = None

    def at(self, t: float) -> Optional[float]:
        if self.constant is not None:
            return self.constant
        if not self.ts or t < self.ts[0]:
            return None
        i = bisect.bisect_right(self.ts, t) - 1
        start = self.ts[i]
        if t >= start + self.step:
            # hora sem negociacao no pool de referencia: vale o ultimo fechamento (no maximo 6h de folga)
            return self.closes[i] if t - (start + self.step) <= 6 * 3600 else None
        frac = (t - start) / self.step
        return self.opens[i] + (self.closes[i] - self.opens[i]) * frac


def stable_series() -> UsdSeries:
    return UsdSeries([], [], [], constant=1.0)


def load_usd_series(store: OhlcvStore, ref_pool: str, side: str, start_ts: int, end_ts: int) -> UsdSeries:
    bars = store.history(ref_pool, "1h", start_ts, end_ts, currency="usd", side=side)
    return UsdSeries([b.ts for b in bars], [b.open for b in bars], [b.close for b in bars])


def to_mc_bars(token_bars: list[Bar], tf: str, usd: UsdSeries, supply: float) -> tuple[list[Bar], int]:
    """Candles em token de cotacao -> candles de MC em USD (volume em USD). Devolve (candles, quantos sem USD)."""
    step = tf_seconds(tf)
    out: list[Bar] = []
    missing = 0
    for b in token_bars:
        f = usd.at(b.ts + step)
        if f is None or f <= 0:
            missing += 1
            continue
        k = f * supply
        out.append(Bar(b.ts, b.open * k, b.high * k, b.low * k, b.close * k, b.volume * f, b.filled))
    return out, missing


def compare_usd(mc_bars: list[Bar], gt_usd_bars: list[Bar], supply: float, tolerance: float = 0.05) -> list[tuple[int, float]]:
    """Candles em que o fechamento convertido difere do USD do GT por mais que `tolerance` (ts, diferenca relativa)."""
    gt = {b.ts: b.close * supply for b in gt_usd_bars}
    bad = []
    for b in mc_bars:
        ref = gt.get(b.ts)
        if ref and b.close > 0:
            diff = abs(ref / b.close - 1.0)
            if diff > tolerance:
                bad.append((b.ts, diff))
    return bad


UsdAt = Callable[[float], Optional[float]]
