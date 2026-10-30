import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.assets import STABLECOIN_MINTS
from src.database import connection


GECKOTERMINAL_MIN_INTERVAL_SECONDS = 2.1
GECKOTERMINAL_RATE_LIMIT_INTERVAL_SECONDS = 12.0
GECKOTERMINAL_RATE_LIMIT_WINDOW_SECONDS = 300.0
GECKOTERMINAL_MAX_HTTP_ATTEMPTS = 2
GECKOTERMINAL_MAX_CYCLE_SECONDS = 52.0
PRICE_RUNTIME_VERSION = "exit_runtime_v3_adaptive_provider_budget"


class PriceProviderError(RuntimeError):
    code = "provider_error"
    retryable = False


class TemporaryPriceProviderError(PriceProviderError):
    code = "temporary_provider_error"
    retryable = True


class ProviderCycleBudgetExhausted(TemporaryPriceProviderError):
    code = "provider_cycle_budget_exhausted"
    counts_toward_retry = False


class PermanentPriceProviderError(PriceProviderError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Pool:
    address: str
    token_side: str
    reserve_usd: float
    volume_usd_24h: float


class GeckoTerminalPriceProvider:
    base_url = "https://api.geckoterminal.com/api/v2"
    _global_last_request_at = 0.0
    _global_cooldown_until = 0.0
    _global_rate_limited_until = 0.0

    def __init__(
        self,
        timeout: int = 30,
        min_interval_seconds: float = GECKOTERMINAL_MIN_INTERVAL_SECONDS,
        rate_limit_interval_seconds: float = GECKOTERMINAL_RATE_LIMIT_INTERVAL_SECONDS,
        rate_limit_window_seconds: float = GECKOTERMINAL_RATE_LIMIT_WINDOW_SECONDS,
        max_http_attempts: int = GECKOTERMINAL_MAX_HTTP_ATTEMPTS,
        max_cycle_seconds: float | None = GECKOTERMINAL_MAX_CYCLE_SECONDS,
    ):
        self.timeout = timeout
        self.min_interval_seconds = min_interval_seconds
        self.rate_limit_interval_seconds = rate_limit_interval_seconds
        self.rate_limit_window_seconds = rate_limit_window_seconds
        self.max_http_attempts = max(1, int(max_http_attempts))
        self.max_cycle_seconds = max_cycle_seconds
        self._cycle_started_at = time.monotonic()
        self._cycle_deadline = (
            self._cycle_started_at + max_cycle_seconds
            if max_cycle_seconds is not None
            else None
        )
        # One provider instance is shared by checkpoints + exit engine in a cycle.
        # Cache failures only for that cycle so the same token/target does not
        # immediately hammer the provider twice after an exhausted logical call.
        self._failure_cache: dict[tuple[str, int, int], PriceProviderError] = {}

    @classmethod
    def reset_global_rate_limit_state(cls) -> None:
        cls._global_last_request_at = 0.0
        cls._global_cooldown_until = 0.0
        cls._global_rate_limited_until = 0.0

    def _control_mode(self, now: float) -> str:
        return (
            "rate_limited"
            if now < type(self)._global_rate_limited_until
            else "normal"
        )

    def _wait_for_turn(self) -> tuple[float, str]:
        now = time.monotonic()
        cls = type(self)
        control_mode = self._control_mode(now)
        interval = (
            self.rate_limit_interval_seconds
            if control_mode == "rate_limited"
            else self.min_interval_seconds
        )
        earliest = max(
            cls._global_last_request_at + max(0.0, interval),
            cls._global_cooldown_until,
        )
        wait_seconds = max(0.0, earliest - now)
        if (
            self._cycle_deadline is not None
            and now + wait_seconds > self._cycle_deadline
        ):
            raise ProviderCycleBudgetExhausted(
                "Orçamento temporal do ciclo esgotado antes da próxima chamada GeckoTerminal."
            )
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return wait_seconds, control_mode

    def _note_rate_limit(self, retry_after: str | None) -> None:
        now = time.monotonic()
        try:
            delay = float(retry_after) if retry_after is not None else 0.0
        except (TypeError, ValueError):
            delay = 0.0
        if delay <= 0:
            delay = self.rate_limit_interval_seconds
        delay = min(delay, 30.0)
        cls = type(self)
        cls._global_cooldown_until = max(cls._global_cooldown_until, now + delay)
        cls._global_rate_limited_until = max(
            cls._global_rate_limited_until,
            now + self.rate_limit_window_seconds,
        )

    def _sleep_with_cycle_budget(self, seconds: float) -> None:
        seconds = max(0.0, seconds)
        now = time.monotonic()
        if self._cycle_deadline is not None and now + seconds > self._cycle_deadline:
            raise ProviderCycleBudgetExhausted(
                "Orçamento temporal do ciclo esgotado durante retry do GeckoTerminal."
            )
        if seconds > 0:
            time.sleep(seconds)

    def _record_http_attempt(
        self, *, path: str, attempt: int, status_code: int | None,
        latency_ms: float, retry_after: str | None, outcome: str, error: str | None,
        wait_ms: float, control_mode: str,
    ) -> None:
        # Best-effort telemetry must never break price collection.
        try:
            with connection() as conn:
                conn.execute(
                    """INSERT INTO provider_http_attempts
                    (runtime_version, requested_at, provider, path, attempt_number,
                     status_code, latency_ms, retry_after, outcome, error,
                     wait_ms, control_mode)
                    VALUES (?, ?, 'geckoterminal', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        PRICE_RUNTIME_VERSION, int(time.time()), path, attempt,
                        status_code, latency_ms, retry_after, outcome, error,
                        wait_ms, control_mode,
                    ),
                )
        except Exception:
            pass

    def _get(self, path: str, query: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "crypto-copy-trader/0.2",
            },
        )
        last_error = None
        for attempt in range(self.max_http_attempts):
            wait_seconds, control_mode = self._wait_for_turn()
            started = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    status_code = getattr(response, "status", 200)
                finished = time.monotonic()
                type(self)._global_last_request_at = finished
                self._record_http_attempt(
                    path=path, attempt=attempt + 1, status_code=status_code,
                    latency_ms=(finished - started) * 1000,
                    retry_after=None, outcome="completed", error=None,
                    wait_ms=wait_seconds * 1000,
                    control_mode=control_mode,
                )
                return payload
            except HTTPError as exc:
                last_error = exc
                finished = time.monotonic()
                type(self)._global_last_request_at = finished
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self._record_http_attempt(
                    path=path, attempt=attempt + 1, status_code=exc.code,
                    latency_ms=(finished - started) * 1000,
                    retry_after=retry_after, outcome="failed", error=str(exc),
                    wait_ms=wait_seconds * 1000,
                    control_mode=control_mode,
                )
                retryable = exc.code == 429 or exc.code in {408, 425} or exc.code >= 500
                if not retryable:
                    raise PermanentPriceProviderError(
                        f"GeckoTerminal recusou a consulta (HTTP {exc.code}).",
                        code=f"http_{exc.code}",
                    ) from exc
                if exc.code == 429:
                    self._note_rate_limit(retry_after)
                elif attempt + 1 < self.max_http_attempts:
                    self._sleep_with_cycle_budget(4.0)
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                finished = time.monotonic()
                type(self)._global_last_request_at = finished
                self._record_http_attempt(
                    path=path, attempt=attempt + 1, status_code=None,
                    latency_ms=(finished - started) * 1000,
                    retry_after=None, outcome="failed", error=str(exc),
                    wait_ms=wait_seconds * 1000,
                    control_mode=control_mode,
                )
                if attempt + 1 < self.max_http_attempts:
                    self._sleep_with_cycle_budget(4.0)
        raise TemporaryPriceProviderError(
            f"GeckoTerminal temporariamente indisponível: {last_error}"
        ) from last_error

    @staticmethod
    def _mint_from_relationship(pool: dict, side: str) -> str | None:
        token_id = (
            pool.get("relationships", {})
            .get(f"{side}_token", {})
            .get("data", {})
            .get("id")
        )
        return token_id.removeprefix("solana_") if token_id else None

    def _cached_pool(self, token_mint: str) -> Pool | None:
        with connection() as conn:
            row = conn.execute(
                """SELECT pool_address, token_side, reserve_usd, volume_usd_24h, updated_at
                FROM token_pool_cache WHERE token_mint=?""",
                (token_mint,),
            ).fetchone()
        if (
            row
            and row["volume_usd_24h"] > 0
            and int(time.time()) - row["updated_at"] < 86_400
        ):
            return Pool(
                row["pool_address"], row["token_side"],
                row["reserve_usd"], row["volume_usd_24h"],
            )
        return None

    def _resolve_pool(self, token_mint: str) -> Pool:
        cached = self._cached_pool(token_mint)
        if cached:
            return cached
        payload = self._get(f"/networks/solana/tokens/{token_mint}/pools", {"page": 1})
        candidates = []
        for item in payload.get("data") or []:
            if self._mint_from_relationship(item, "base") == token_mint:
                token_side = "base"
            elif self._mint_from_relationship(item, "quote") == token_mint:
                token_side = "quote"
            else:
                continue
            attributes = item.get("attributes") or {}
            address = attributes.get("address")
            if address:
                candidates.append(
                    Pool(
                        address,
                        token_side,
                        float(attributes.get("reserve_in_usd") or 0),
                        float((attributes.get("volume_usd") or {}).get("h24") or 0),
                    )
                )
        if not candidates:
            raise PermanentPriceProviderError(
                f"Nenhum pool encontrado para {token_mint}.", code="no_pool"
            )
        pool = max(candidates, key=lambda item: (item.volume_usd_24h, item.reserve_usd))
        with connection() as conn:
            conn.execute(
                """INSERT INTO token_pool_cache
                (token_mint, pool_address, token_side, reserve_usd, volume_usd_24h, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_mint) DO UPDATE SET
                    pool_address=excluded.pool_address,
                    token_side=excluded.token_side,
                    reserve_usd=excluded.reserve_usd,
                    volume_usd_24h=excluded.volume_usd_24h,
                    updated_at=excluded.updated_at""",
                (
                    token_mint, pool.address, pool.token_side, pool.reserve_usd,
                    pool.volume_usd_24h, int(time.time()),
                ),
            )
        return pool

    def market_for(self, token_mint: str) -> Pool:
        """Return the current chosen pool metrics used for signal eligibility."""
        return self._resolve_pool(token_mint)

    def price_at(
        self,
        token_mint: str,
        timestamp: int,
        *,
        max_distance_seconds: int = 3_600,
    ) -> float:
        minute_ts = timestamp - timestamp % 60
        failure_key = (token_mint, minute_ts, int(max_distance_seconds))
        cached_failure = self._failure_cache.get(failure_key)
        if cached_failure is not None:
            raise cached_failure
        if token_mint in STABLECOIN_MINTS:
            return 1.0
        with connection() as conn:
            row = conn.execute(
                "SELECT price_usd FROM price_cache WHERE token_mint=? AND minute_ts=?",
                (token_mint, minute_ts),
            ).fetchone()
        if row:
            return float(row["price_usd"])

        try:
            pool = self._resolve_pool(token_mint)
            payload = self._get(
                f"/networks/solana/pools/{pool.address}/ohlcv/minute",
                {
                    "aggregate": 1,
                    "before_timestamp": minute_ts + 60,
                    "limit": 1,
                    "currency": "usd",
                    "token": pool.token_side,
                },
            )
        except PriceProviderError as exc:
            self._failure_cache[failure_key] = exc
            raise
        candles = (
            payload.get("data", {}).get("attributes", {}).get("ohlcv_list") or []
        )
        if not candles:
            error = PermanentPriceProviderError(
                f"Sem candle histórico para {token_mint} em {minute_ts}.",
                code="no_historical_candle",
            )
            self._failure_cache[failure_key] = error
            raise error
        candle = candles[0]
        candle_ts, close_price = int(candle[0]), float(candle[4])
        if abs(candle_ts - minute_ts) > max_distance_seconds:
            error = PermanentPriceProviderError(
                f"Candle disponível está distante demais do horário do sinal para {token_mint}.",
                code="distant_historical_candle",
            )
            self._failure_cache[failure_key] = error
            raise error
        with connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_cache
                (token_mint, minute_ts, price_usd, pool_address) VALUES (?, ?, ?, ?)""",
                (token_mint, minute_ts, close_price, pool.address),
            )
        return close_price
