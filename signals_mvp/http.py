"""Camada HTTP: limitador de taxa, pausa/backoff em 429 e erros tipados.

O GeckoTerminal publico limita ~30 chamadas/min por IP e responde 429 com
`retry-after: 0` (inutil), entao a pausa e calculada aqui, nao pelo header.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping, Optional

import requests

log = logging.getLogger("signals_mvp.http")

# BUG PRIORITARIO (2026-10-22, item 4): WARNING pra qualquer chamada de rede que passar disto -- sinaliza
# degradacao antes de virar travamento percebido pelo operador.
SLOW_CALL_WARN_S = 20.0


class ApiError(Exception):
    """Falha de API. `kind`: rate_limited | http | timeout | network | bad_json | not_found | budget."""

    def __init__(self, kind: str, message: str = "", status: int | None = None):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind
        self.status = status


class RateLimited(ApiError):
    def __init__(self, wait_s: float, message: str = ""):
        super().__init__("rate_limited", message or f"aguardar {wait_s:.0f}s", status=429)
        self.wait_s = wait_s


class RateLimiter:
    """Token bucket (`per_min` fichas/min, rajada `burst`) + pausa global apos 429 + ritmo ADAPTATIVO.

    O ritmo efetivo comeca em `per_min` (o maximo). A cada 429 ele CAI pela metade (piso = `min_per_min`) e
    volta a subir aos poucos a cada sucesso (aumento aditivo), como no TCP (AIMD). Assim o bot converge
    sozinho para o ritmo que o IP dele realmente aguenta, sem o operador mexer em nada.
    `clock` e `sleep` sao injetaveis para teste. Thread-safe.
    """

    def __init__(
        self,
        per_min: float,
        burst: int,
        pause_s: float = 30.0,
        pause_max_s: float = 240.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_per_min: float | None = None,
        recover_per_success: float = 0.5,
        jitter_s: float = 0.0,
    ):
        self.max_per_min = float(per_min)
        self.min_per_min = float(min_per_min) if min_per_min is not None else max(2.0, per_min * 0.25)
        self.per_min = float(per_min)           # ritmo efetivo atual
        self.recover = recover_per_success
        self.burst = float(max(1, burst))
        self.pause_s = pause_s
        self.pause_max_s = pause_max_s
        # EMENDA 2026-10-17 (cega a resultado, operacional -- desincroniza as chamadas da fronteira exata da
        # janela de 1min do provedor, para gastar menos 429/pausa de 30s no mesmo teto efetivo; so entra quando
        # a chamada JA ia esperar, nunca atrasa uma chamada que tinha ficha livre). 0.0 = sem jitter (default,
        # compatibilidade retroativa com todo chamador existente).
        self.jitter_s = max(0.0, jitter_s)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = self.burst
        self._stamp = clock()
        self._blocked_until = 0.0
        self._consecutive_429 = 0

    @property
    def rate(self) -> float:
        return self.per_min / 60.0

    # -- estado ---------------------------------------------------------------
    def blocked_for(self) -> float:
        return max(0.0, self._blocked_until - self._clock())

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
        self._stamp = now

    def available_within(self, seconds: float) -> int:
        """Quantas chamadas cabem nos proximos `seconds` s (fichas de hoje + as que enchem ate la). 0 se em pausa de 429."""
        with self._lock:
            if self.blocked_for() > seconds:
                return 0
            self._refill()
            usable = max(0.0, seconds - self.blocked_for())
            return int(min(self.burst, self._tokens) + self.rate * usable)

    # -- uso --------------------------------------------------------------------
    def acquire(self, max_wait_s: float = 5.0) -> None:
        """Bloqueia ate haver ficha. Se a espera passar de `max_wait_s`, levanta erro (sem dormir)."""
        with self._lock:
            blocked = self.blocked_for()
            if blocked > 0:
                raise RateLimited(blocked, f"em pausa por 429 ({blocked:.0f}s restantes)")
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self.rate if self.rate > 0 else float("inf")
            if wait > max_wait_s:
                raise ApiError("budget", f"limite de taxa: espera de {wait:.1f}s passa de {max_wait_s:.1f}s")
            if self.jitter_s > 0 and wait < float("inf"):
                wait += random.uniform(0.0, self.jitter_s)
            self._tokens = 0.0
            self._stamp = self._clock() + wait
        self._sleep(wait)

    def on_429(self) -> float:
        """Registra um 429: pausa `pause_s` (dobra a cada 429 seguido, ate `pause_max_s`) e reduz o ritmo pela metade."""
        with self._lock:
            self._consecutive_429 += 1
            pause = min(self.pause_max_s, self.pause_s * (2 ** (self._consecutive_429 - 1)))
            self._blocked_until = self._clock() + pause
            self._tokens = 0.0
            self.per_min = max(self.min_per_min, self.per_min / 2.0)
            return pause

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_429 = 0
            if self.per_min < self.max_per_min:
                self.per_min = min(self.max_per_min, self.per_min + self.recover)

    def on_error_pause(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)


class HttpClient:
    """GET JSON com limitador, timeouts e erros tipados."""

    def __init__(
        self,
        base_url: str,
        limiter: RateLimiter,
        timeout_s: float = 20.0,
        headers: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        name: str = "api",
        error_pause_s: float = 0.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.timeout = (5.0, timeout_s)
        self.headers = dict(headers or {})
        self.session = session or requests.Session()
        self.name = name
        self.error_pause_s = error_pause_s
        self.calls = 0
        self.errors = 0
        self.rate_limited = 0
        self.last_server_date: Optional[float] = None   # header `Date` da ultima resposta (epoch)
        self.last_local_at_response: Optional[float] = None

    def clock_skew_s(self) -> Optional[float]:
        """Relogio local menos relogio do servidor (positivo = PC adiantado). None se ainda nao ha resposta."""
        if self.last_server_date is None or self.last_local_at_response is None:
            return None
        return self.last_local_at_response - self.last_server_date

    def get_json(self, path: str, params: Mapping[str, Any] | None = None, max_wait_s: float = 5.0) -> Any:
        self.limiter.acquire(max_wait_s)
        url = f"{self.base_url}/{path.lstrip('/')}"
        self.calls += 1
        t0 = time.monotonic()
        try:
            response = self.session.get(url, params=params, headers=self.headers, timeout=self.timeout)
        except requests.Timeout as exc:
            self.errors += 1
            raise ApiError("timeout", f"{self.name}: {type(exc).__name__}") from None
        except requests.RequestException as exc:
            self.errors += 1
            raise ApiError("network", f"{self.name}: {type(exc).__name__}") from None
        finally:
            elapsed = time.monotonic() - t0
            if elapsed > SLOW_CALL_WARN_S:
                log.warning("%s: chamada lenta (%.1fs) em %s", self.name, elapsed, path)
        status = response.status_code
        date_header = getattr(response, "headers", {}).get("Date") if getattr(response, "headers", None) is not None else None
        if date_header:
            try:
                self.last_server_date = parsedate_to_datetime(date_header).timestamp()
                self.last_local_at_response = time.time()
            except (TypeError, ValueError):
                pass
        if status == 429:
            self.errors += 1
            self.rate_limited += 1
            pause = self.limiter.on_429()
            log.warning("%s: HTTP 429 — pausando chamadas por %.0fs", self.name, pause)
            raise RateLimited(pause)
        if status == 404:
            self.errors += 1
            raise ApiError("not_found", f"{self.name}: {path}", status)
        if status >= 400:
            self.errors += 1
            if status >= 500 and self.error_pause_s:
                self.limiter.on_error_pause(self.error_pause_s)
            raise ApiError("http", f"{self.name}: HTTP {status}", status)
        try:
            data = response.json()
        except ValueError:
            self.errors += 1
            raise ApiError("bad_json", f"{self.name}: resposta nao e JSON", status) from None
        self.limiter.on_success()
        return data


class CallBudget:
    """Orcamento de chamadas por ciclo (a fila de prioridade gasta daqui)."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def left(self) -> int:
        return max(0, self.limit - self.used)

    def take(self, n: int = 1, keep: int = 0) -> bool:
        """Reserva `n` chamadas deixando `keep` de folga; False (sem gastar) se nao couber."""
        if self.used + n + keep > self.limit:
            return False
        self.used += n
        return True

    def exhaust(self) -> None:
        """Esgota o orcamento do ciclo (ex.: apos 429)."""
        self.used = self.limit
