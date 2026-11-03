"""Cliente do DexPaprika (PEDIDO CONSOLIDADO, FASE 1): fonte SECUNDARIA de candles -- fallback de
atualizacao recente e conferencia cruzada da POS-RUNNER-V1. NUNCA substitui o GeckoTerminal na
reconstrucao do setup (tokens de 5-7 dias podem ter o pico fora da janela de 7 dias que o DexPaprika
cobre no plano gratuito).

Fatos confirmados (2026-10-26, chamada real sem chave a api.dexpaprika.com -- ver docs/DEXPAPRIKA.md):
  - base: https://api.dexpaprika.com; endpoint: GET /networks/{network}/pools/{pool_address}/ohlcv
  - parametros: start (obrigatorio; aceita timestamp unix, RFC3339 ou "-24h"/"-7d"), end (opcional),
    interval (1m|5m|10m|15m|30m|1h|6h|12h|24h, default 24h), limit (1-1000, default 10).
  - resposta: lista JSON de {time_open, time_close, open, high, low, close, volume} (sem campo "data"
    como no GeckoTerminal).
  - chave no header `Authorization` (valor cru, SEM prefixo "Bearer").
  - plano SEM chave ("keyless", medido ao vivo): 10 req/min (a documentacao estatica cita 15 -- o valor
    REAL observado no header `ratelimit-limit` e 10; confiar no header, nunca num numero fixo), 10.000
    creditos, so intervalo >= 1h, so ultimas 24h. Fora disso: HTTP 403 `{"error":"plan_required",...}`.
  - headers de toda resposta: `ratelimit-limit/-remaining/-reset`, `x-credits-limit/-remaining/-reset`,
    `x-api-plan` -- usados aqui para o orcamento de creditos (nunca um contador local re-inventado).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Optional

import requests

from .http import ApiError, RateLimited, RateLimiter
from .models import Candle
from .util import parse_iso, utc_now

log = logging.getLogger("signals_mvp.dexpaprika")

BASE_URL = "https://api.dexpaprika.com"
INTERVALS = ("1m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "24h")


def parse_ohlcv_dexpaprika(data: Any) -> list[Candle]:
    """Resposta e uma lista JSON direta (sem envelope `data`, diferente do GeckoTerminal). Linha malformada
    (campo ausente, preco <= 0, high < low) e descartada, nunca vira excecao (mesmo espirito de
    `geckoterminal.parse_ohlcv`)."""
    if not isinstance(data, list):
        raise ApiError("bad_json", "DexPaprika: resposta OHLCV nao e uma lista")
    out: list[Candle] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        ts = parse_iso(row.get("time_open"))
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            v = float(row.get("volume") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if ts is None or min(o, h, l, c) <= 0 or h < l:
            continue
        out.append(Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v))
    out.sort(key=lambda c: c.ts)
    return out


@dataclass
class _CreditInfo:
    """Snapshot dos headers de credito/limite da ULTIMA resposta (nunca um contador local reinventado --
    o DexPaprika ja devolve o estado real da janela movel de 30 dias em todo request, inclusive sem
    chave)."""

    ratelimit_limit: Optional[int] = None
    ratelimit_remaining: Optional[int] = None
    credits_limit: Optional[int] = None
    credits_remaining: Optional[int] = None
    credits_reset_s: Optional[int] = None
    api_plan: Optional[str] = None


def _header_int(headers: Mapping[str, str], name: str) -> Optional[int]:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


class DexPaprikaHttp:
    """GET JSON no DexPaprika: limitador proprio (token bucket, `RateLimiter` -- o mesmo de http.py,
    nunca reinventado), chave opcional no header `Authorization` (NUNCA logada, NUNCA na mensagem de
    erro), e leitura dos headers de credito/limite em TODA resposta (sucesso ou erro)."""

    def __init__(
        self,
        limiter: RateLimiter,
        api_key: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout_s: float = 15.0,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.timeout = (5.0, timeout_s)
        self.session = session or requests.Session()
        self.credits = _CreditInfo()
        self.calls = 0
        self.errors = 0
        self._api_key = api_key  # nunca exposto em __repr__/str nem em mensagem de ApiError

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = self._api_key  # valor cru, sem "Bearer" (confirmado no SDK oficial)
        return headers

    def _update_credits(self, headers: Mapping[str, str]) -> None:
        self.credits = _CreditInfo(
            ratelimit_limit=_header_int(headers, "ratelimit-limit"),
            ratelimit_remaining=_header_int(headers, "ratelimit-remaining"),
            credits_limit=_header_int(headers, "x-credits-limit"),
            credits_remaining=_header_int(headers, "x-credits-remaining"),
            credits_reset_s=_header_int(headers, "x-credits-reset"),
            api_plan=headers.get("x-api-plan"),
        )

    def get_json(self, path: str, params: Mapping[str, Any] | None = None, max_wait_s: float = 5.0) -> Any:
        self.limiter.acquire(max_wait_s)
        url = f"{self.base_url}/{path.lstrip('/')}"
        self.calls += 1
        try:
            response = self.session.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.Timeout:
            self.errors += 1
            raise ApiError("timeout", "DexPaprika: tempo esgotado") from None
        except requests.RequestException as exc:
            self.errors += 1
            raise ApiError("network", f"DexPaprika: {type(exc).__name__}") from None
        headers = getattr(response, "headers", {}) or {}
        self._update_credits(headers)
        status = response.status_code
        if status == 429:
            self.errors += 1
            pause = self.limiter.on_429()
            log.warning("DexPaprika: HTTP 429 -- pausando chamadas por %.0fs", pause)
            raise RateLimited(pause)
        if status == 403:
            self.errors += 1
            # plano/chave nao cobre o pedido (intervalo, janela de historico ou creditos esgotados) --
            # NUNCA fatal, quem chama trata como "indisponivel" (fato confirmado pelo operador).
            raise ApiError("plan_limit", "DexPaprika: fora do plano (interval/janela/creditos)", 403)
        if status == 404:
            self.errors += 1
            raise ApiError("not_found", f"DexPaprika: {path}", 404)
        if status >= 400:
            self.errors += 1
            raise ApiError("http", f"DexPaprika: HTTP {status}", status)
        try:
            data = response.json()
        except ValueError:
            self.errors += 1
            raise ApiError("bad_json", "DexPaprika: resposta nao e JSON") from None
        self.limiter.on_success()
        return data


class DexPaprikaClient:
    """Mesma interface de `geckoterminal.GtClient` para OHLCV: `ohlcv(network, pool, start_ts, end_ts, tf)`
    devolve candles em ordem crescente. Levanta ApiError/RateLimited; quem chama decide (mesmo padrao do
    GtClient -- "levanta ApiError; quem chama decide o que fazer")."""

    def __init__(self, http: DexPaprikaHttp, clock: Callable[[], float] = utc_now):
        self.http = http
        self.clock = clock

    def ohlcv(self, network: str, pool: str, start_ts: float, end_ts: float, interval: str = "1h",
             limit: int = 1000) -> list[Candle]:
        if interval not in INTERVALS:
            raise ValueError(f"interval invalido: {interval!r} (validos: {INTERVALS})")
        params = {"start": str(int(start_ts)), "end": str(int(end_ts)), "interval": interval,
                  "limit": max(1, min(1000, limit))}
        data = self.http.get_json(f"networks/{network}/pools/{pool}/ohlcv", params, max_wait_s=10.0)
        candles = parse_ohlcv_dexpaprika(data)
        return [c for c in candles if start_ts - 1 <= c.ts <= end_ts]
