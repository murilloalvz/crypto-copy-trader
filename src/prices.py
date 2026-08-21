import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.assets import STABLECOIN_MINTS
from src.database import connection


class PriceProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pool:
    address: str
    token_side: str
    reserve_usd: float
    volume_usd_24h: float


class GeckoTerminalPriceProvider:
    base_url = "https://api.geckoterminal.com/api/v2"

    def __init__(self, timeout: int = 30, min_interval_seconds: float = 2.1):
        self.timeout = timeout
        self.min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0

    def _get(self, path: str, query: dict | None = None) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
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
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._last_request_at = time.monotonic()
                return payload
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise PriceProviderError(f"GeckoTerminal indisponível: {last_error}") from last_error

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
            raise PriceProviderError(f"Nenhum pool com preço encontrado para {token_mint}")
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

    def price_at(self, token_mint: str, timestamp: int) -> float:
        minute_ts = timestamp - timestamp % 60
        if token_mint in STABLECOIN_MINTS:
            return 1.0
        with connection() as conn:
            row = conn.execute(
                "SELECT price_usd FROM price_cache WHERE token_mint=? AND minute_ts=?",
                (token_mint, minute_ts),
            ).fetchone()
        if row:
            return float(row["price_usd"])

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
        candles = (
            payload.get("data", {}).get("attributes", {}).get("ohlcv_list") or []
        )
        if not candles:
            raise PriceProviderError(f"Sem candle histórico para {token_mint} em {minute_ts}")
        candle = candles[0]
        candle_ts, close_price = int(candle[0]), float(candle[4])
        if abs(candle_ts - minute_ts) > 3_600:
            raise PriceProviderError(f"Preço histórico distante demais para {token_mint}")
        with connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_cache
                (token_mint, minute_ts, price_usd, pool_address) VALUES (?, ?, ?, ?)""",
                (token_mint, minute_ts, close_price, pool.address),
            )
        return close_price
