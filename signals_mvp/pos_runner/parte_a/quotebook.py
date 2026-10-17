"""Referencia USD de qualquer token de cotacao (SOL, USDC, DKNG, ZEC, EMBER...), escolhida de forma automatica
e REGISTRADA (o mesmo pool vale para a coleta inteira).

Regra: estavel (USDC/USDT/USD1) = 1; SOL = Orca SOL/USDC; outro token = o pool de maior liquidez desse token contra
USDC/USDT/SOL no GeckoTerminal que ja existia antes do periodo; sem pool assim = "sem_referencia" (o pool que usa
essa cotacao sai da amostra com motivo explicito, nunca convertido no chute).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from ...http import ApiError
from ...util import parse_iso, to_float
from ..candles import OhlcvStore
from ..examples import QUOTE_REFERENCES
from ..quotes import SOL_MINT, STABLES, UsdSeries, load_usd_series, stable_series

ANCHORS = set(STABLES) | {SOL_MINT}


def pick_reference(pools_json: Any, quote_mint: str, not_after_ts: int) -> Optional[tuple[str, str]]:
    """(pool, lado do token de cotacao) a partir da resposta de `tokens/{mint}/pools`."""
    best: Optional[tuple[float, str, str]] = None
    for p in (pools_json or {}).get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id", "").split("_", 1)[-1]
        quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id", "").split("_", 1)[-1]
        if quote_mint not in (base, quote):
            continue
        other = quote if base == quote_mint else base
        if other not in ANCHORS:
            continue
        created = parse_iso(a.get("pool_created_at"))
        if created is None or created > not_after_ts:
            continue
        liq = to_float(a.get("reserve_in_usd")) or 0.0
        side = "base" if base == quote_mint else "quote"
        if best is None or liq > best[0]:
            best = (liq, a.get("address"), side)
    return (best[1], best[2]) if best else None


class QuoteBook:
    def __init__(self, ohlcv: OhlcvStore, registry_path: Path, fetch_pools: Optional[Callable[[str], Any]] = None):
        self.ohlcv = ohlcv
        self.path = Path(registry_path)
        self.registry: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self._fetch = fetch_pools or (lambda mint: ohlcv.http.get_json(f"networks/{ohlcv.network}/tokens/{mint}/pools",
                                                                       {"page": 1}, max_wait_s=600.0))
        self._series: dict[str, UsdSeries] = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.registry, indent=1, sort_keys=True), encoding="utf-8")

    def reference(self, quote_mint: str, period_start: int) -> Optional[tuple[str, str]]:
        if quote_mint in self.registry:
            ref = self.registry[quote_mint]
            return None if ref is None else (ref[0], ref[1])
        if quote_mint in QUOTE_REFERENCES:
            ref = QUOTE_REFERENCES[quote_mint]
        else:
            try:
                ref = pick_reference(self._fetch(quote_mint), quote_mint, period_start)
            except ApiError:
                return None       # falha de rede: nao registra, tenta de novo depois
        self.registry[quote_mint] = None if ref is None else [ref[0], ref[1]]
        self._save()
        return ref

    def series(self, quote_mint: str, start_ts: int, end_ts: int, period_start: int) -> Optional[UsdSeries]:
        if quote_mint in STABLES:
            return stable_series()
        ref = self.reference(quote_mint, period_start)
        if ref is None:
            return None
        key = f"{quote_mint}:{start_ts}:{end_ts}"
        if key not in self._series:
            self._series[key] = load_usd_series(self.ohlcv, ref[0], ref[1], start_ts, end_ts)
        return self._series[key]
