"""Serie de MC (USD) de um pool por timeframe: taxa em token de cotacao x cotacao/USD de referencia.

Usada igual no Passo 0, no backtest e no bot. `L_bc` (MC na graduacao) = abertura do 1o candle de 5m do pool de
graduacao (1o negocio depois da migracao) convertida para USD — no pump.fun isso da ~411 SOL de MC, o fim da curva.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .candles import Bar, OhlcvStore, fill_gaps, tf_seconds
from .quotes import STABLES, UsdSeries, compare_usd, load_usd_series, stable_series, to_mc_bars


@dataclass
class PoolSeries:
    pool: str
    supply: float
    bars: dict[str, list[Bar]] = field(default_factory=dict)       # tf -> candles de MC (com lacunas preenchidas)
    l_bc: Optional[float] = None
    missing_usd: dict[str, int] = field(default_factory=dict)      # candles sem cotacao/USD no instante
    usd_mismatch: dict[str, list[tuple[int, float]]] = field(default_factory=dict)   # conferencia com o USD do GT


def quote_usd(store: OhlcvStore, quote_mint: str, references: dict[str, tuple[str, str]], start_ts: int, end_ts: int) -> Optional[UsdSeries]:
    if quote_mint in STABLES:
        return stable_series()
    ref = references.get(quote_mint)
    if ref is None:
        return None
    return load_usd_series(store, ref[0], ref[1], start_ts - 3 * 3600, end_ts)


def build_series(
    store: OhlcvStore,
    pool: str,
    grad_ts: int,
    end_ts: int,
    supply: float,
    usd: UsdSeries,
    tfs: tuple[str, ...] = ("5m", "1h", "4h"),
    cross_check: bool = False,
    tolerance: float = 0.05,
) -> PoolSeries:
    out = PoolSeries(pool=pool, supply=supply)
    for tf in tfs:
        step = tf_seconds(tf)
        raw = store.history(pool, tf, grad_ts, end_ts, currency="token")
        mc, missing = to_mc_bars([b for b in raw if b.ts + step <= end_ts], tf, usd, supply)
        out.missing_usd[tf] = missing
        out.bars[tf] = fill_gaps(mc, step)
        if cross_check:
            gt_usd = store.history(pool, tf, grad_ts, end_ts, currency="usd")
            out.usd_mismatch[tf] = compare_usd(mc, gt_usd, supply, tolerance)
    first = out.bars.get("5m") or out.bars.get("1h") or []
    if first:
        out.l_bc = first[0].open
    return out
