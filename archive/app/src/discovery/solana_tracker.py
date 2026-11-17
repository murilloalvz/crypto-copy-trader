import json
import ssl
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.config import settings
from src.discovery.birdeye import is_solana_address
from src.discovery.models import (
    DailyWalletActivity,
    LiquidMarket,
    TokenPosition,
    TokenTraderSeed,
    TraderSnapshot,
    WaveTokenSnapshot,
    WalletHistory,
    WalletPositions,
)

SOLANA_TRACKER_BASE_URL = "https://data.solanatracker.io"


class SolanaTrackerError(RuntimeError):
    pass


class SolanaTrackerConfigurationError(SolanaTrackerError):
    pass


class SolanaTrackerAuthenticationError(SolanaTrackerError):
    pass


class SolanaTrackerRateLimitError(SolanaTrackerError):
    pass


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _optional_integer(value) -> int | None:
    return None if value is None else _integer(value)


def _optional_positive_integer(value) -> int | None:
    parsed = _optional_integer(value)
    return parsed if parsed is not None and parsed > 0 else None


def _optional_number(value) -> float | None:
    return None if value is None else _number(value)


def _timestamp_ms(value) -> int | None:
    timestamp = _optional_integer(value)
    if timestamp is None or timestamp <= 0:
        return None
    return timestamp * 1_000 if timestamp < 1_000_000_000_000 else timestamp


def _tls12_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def _is_ssl_error(error: BaseException) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(error, ssl.SSLError) or isinstance(reason, ssl.SSLError)


def _is_connection_reset(error: BaseException) -> bool:
    reason = getattr(error, "reason", error)
    return isinstance(reason, ConnectionResetError) or getattr(reason, "winerror", None) == 10054


class SolanaTrackerClient:
    """Read-only client for Solana Tracker's PnL V2 discovery endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = SOLANA_TRACKER_BASE_URL,
        timeout: int | None = None,
        max_attempts: int | None = None,
        request_interval_seconds: float = 0.75,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        configured = settings.solana_tracker_api_key if api_key is None else api_key
        self.api_key = configured.strip()
        self.base_url = base_url.rstrip("/")
        configured_timeout = (
            settings.solana_tracker_timeout_seconds if timeout is None else timeout
        )
        configured_attempts = (
            settings.solana_tracker_max_attempts
            if max_attempts is None
            else max_attempts
        )
        self.timeout = max(1, int(configured_timeout))
        self.max_attempts = max(1, int(configured_attempts))
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self._sleeper = sleeper
        self._clock = clock
        self._last_request_at: float | None = None

    def _require_key(self) -> None:
        if not self.api_key:
            raise SolanaTrackerConfigurationError(
                "SOLANA_TRACKER_API_KEY não configurada. Crie uma chave no painel do "
                "Solana Tracker e coloque somente o valor no arquivo .env."
            )

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            remaining = self.request_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
        self._last_request_at = self._clock()

    def _read_payload(
        self, request: Request, context: ssl.SSLContext | None = None
    ) -> dict:
        options = {"timeout": self.timeout}
        if context is not None:
            options["context"] = context
        with urlopen(request, **options) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _http_error_message(error: HTTPError) -> str:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            return str(payload.get("error") or payload.get("message") or error.reason)
        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
            return str(error.reason)

    def _request(self, path: str, params: dict) -> dict:
        self._require_key()
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "x-api-key": self.api_key,
                "User-Agent": "crypto-copy-trader/0.2",
            },
            method="GET",
        )
        last_error: BaseException | None = None
        for attempt in range(self.max_attempts):
            self._throttle()
            try:
                payload = self._read_payload(request)
            except HTTPError as exc:
                message = self._http_error_message(exc)
                if exc.code in {401, 403}:
                    raise SolanaTrackerAuthenticationError(
                        f"Solana Tracker recusou a API key (HTTP {exc.code}): {message}"
                    ) from exc
                last_error = exc
                if exc.code == 429:
                    if attempt + 1 == self.max_attempts:
                        raise SolanaTrackerRateLimitError(
                            "Limite do Solana Tracker atingido após novas tentativas."
                        ) from exc
                elif exc.code < 500:
                    raise SolanaTrackerError(
                        f"Solana Tracker HTTP {exc.code}: {message}"
                    ) from exc
            except (URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as exc:
                last_error = exc
                if _is_ssl_error(exc) or _is_connection_reset(exc):
                    try:
                        payload = self._read_payload(request, _tls12_context())
                    except (URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as tls_exc:
                        last_error = tls_exc
                    else:
                        return self._validate_payload(payload)
            else:
                return self._validate_payload(payload)
            if attempt + 1 < self.max_attempts:
                self._sleeper(min(2**attempt, 8))
        network_hint = (
            " A conexão foi redefinida pela rede/host; tente outra rede ou verifique "
            "proxy, VPN e antivírus."
            if last_error is not None and _is_connection_reset(last_error)
            else ""
        )
        raise SolanaTrackerError(
            f"Solana Tracker indisponível após {self.max_attempts} tentativas: "
            f"{last_error}.{network_hint}"
        )

    @staticmethod
    def _validate_payload(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise SolanaTrackerError("Resposta inválida do Solana Tracker.")
        if payload.get("error"):
            raise SolanaTrackerError(str(payload["error"]))
        return payload

    @staticmethod
    def _snapshot(item: dict, pnl_mode: str) -> TraderSnapshot | None:
        address = str(item.get("wallet") or "")
        if not is_solana_address(address):
            return None
        period = item.get("period") or {}
        period_days = period.get("days") or {}
        counts = item.get("counts") or {}
        tokens = item.get("tokens") or {}
        timing = item.get("timing") or {}
        return TraderSnapshot(
            address=address,
            realized_pnl_usd=_number(period.get("realized")),
            volume_usd=_number(period.get("volume")),
            trading_days=_integer(period.get("tradingDays")),
            profitable_days=_integer(period_days.get("profitable")),
            losing_days=_integer(period_days.get("losing")),
            max_single_day_pnl_usd=_number(period_days.get("maxSinglePnl")),
            roi_pct=_number(period.get("roi")),
            invested_usd=_number(item.get("invested")),
            proceeds_usd=_number(item.get("proceeds")),
            buys=_integer(counts.get("buys")),
            sells=_integer(counts.get("sells")),
            trades=_integer(counts.get("trades")),
            tokens_traded=_integer(counts.get("tokensTraded")),
            profitable_tokens=_integer(tokens.get("profitable")),
            losing_tokens=_integer(tokens.get("losing")),
            closed_tokens=_integer(tokens.get("closed")),
            win_rate_pct=_number(item.get("winRate")),
            first_trade_ms=_optional_integer(timing.get("firstTrade")),
            last_trade_ms=_optional_integer(timing.get("lastTrade")),
            pnl_mode=pnl_mode,
        )

    def top_traders(
        self,
        limit: int = 250,
        *,
        sort_by: str = "realized",
        direction: str = "desc",
        days: int = 30,
        min_trades: int = 20,
        min_win_rate: float = 45,
        min_roi: float = 0,
        min_closed_tokens: int = 5,
        max_single_token_pct: float = 50,
        min_invested_usd: float = 1,
        min_trading_days: int = 3,
    ) -> list[TraderSnapshot]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit precisa estar entre 1 e 10000")
        if days not in {1, 7, 30, 90}:
            raise ValueError("days precisa ser 1, 7, 30 ou 90")
        if sort_by not in {
            "realized", "volume", "days", "roi", "win_percentage", "trades", "tokens"
        }:
            raise ValueError("ordenação inválida para o leaderboard")
        if direction not in {"asc", "desc"}:
            raise ValueError("direção inválida para o leaderboard")

        results: list[TraderSnapshot] = []
        seen: set[str] = set()
        cursor = None
        while len(results) < limit:
            page_size = min(100, limit - len(results))
            payload = self._request(
                "/v2/pnl/leaderboard/top",
                {
                    "sort": sort_by,
                    "direction": direction,
                    "limit": page_size,
                    "cursor": cursor,
                    "excludeArbitrage": "true",
                    "pnlMode": "strict",
                    "days": days,
                    "minTrades": min_trades,
                    "minInvested": min_invested_usd,
                    "minDays": min_trading_days,
                    "minWinRate": min_win_rate,
                    "minRoi": min_roi,
                    "minClosedTokens": min_closed_tokens,
                    "maxSingleTokenPct": max_single_token_pct,
                },
            )
            items = payload.get("traders") or []
            pagination = payload.get("pagination") or {}
            if not isinstance(items, list):
                raise SolanaTrackerError("Resposta inválida: traders não é uma lista.")
            pnl_mode = str(pagination.get("pnlMode") or "strict")
            for item in items:
                snapshot = self._snapshot(item, pnl_mode) if isinstance(item, dict) else None
                if snapshot and snapshot.address not in seen:
                    seen.add(snapshot.address)
                    results.append(snapshot)
                    if len(results) == limit:
                        break
            next_cursor = pagination.get("nextCursor")
            if not pagination.get("hasMore") or not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)
        return results

    def liquid_markets(
        self,
        limit: int = 12,
        *,
        min_liquidity_usd: float = 250_000,
        min_volume_24h_usd: float = 100_000,
    ) -> list[LiquidMarket]:
        """Find active liquid tokens through the documented token search endpoint."""
        if not 1 <= limit <= 500:
            raise ValueError("limit precisa estar entre 1 e 500")
        payload = self._request(
            "/search",
            {
                "sortBy": "volume_24h",
                "sortOrder": "desc",
                "minLiquidity": min_liquidity_usd,
                "minVolume": min_volume_24h_usd,
                "volumeTimeframe": "24h",
                "limit": limit,
            },
        )
        markets = []
        seen = set()
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            token = str(item.get("mint") or "")
            if not is_solana_address(token) or token in seen:
                continue
            liquidity = _number(item.get("liquidityUsd"))
            volume = _number(item.get("volume_24h"))
            if liquidity < min_liquidity_usd or volume < min_volume_24h_usd:
                continue
            seen.add(token)
            markets.append(
                LiquidMarket(
                    token=token,
                    symbol=str(item["symbol"]) if item.get("symbol") else None,
                    liquidity_usd=liquidity,
                    volume_usd_24h=volume,
                    pool_address=(
                        str(item["poolAddress"]) if item.get("poolAddress") else None
                    ),
                )
            )
        return markets

    def wave_tokens(
        self,
        limit: int = 100,
        *,
        min_liquidity_usd: float = 50_000,
        min_volume_5m_usd: float = 5_000,
    ) -> list[WaveTokenSnapshot]:
        """Return active tokens with documented market and risk fields."""
        if not 1 <= limit <= 100:
            raise ValueError("limit precisa estar entre 1 e 100")
        payload = self._request(
            "/search",
            {
                "sortBy": "volume_5m",
                "sortOrder": "desc",
                "minLiquidity": min_liquidity_usd,
                "minVolume": min_volume_5m_usd,
                "volumeTimeframe": "5m",
                "limit": limit,
            },
        )
        source_items = payload.get("data") or []
        snapshots = []
        seen = set()
        invalid_count = duplicate_count = 0
        for item in source_items:
            if not isinstance(item, dict):
                invalid_count += 1
                continue
            token = str(item.get("mint") or "")
            if not is_solana_address(token):
                invalid_count += 1
                continue
            if token in seen:
                duplicate_count += 1
                continue
            seen.add(token)
            token_details = item.get("tokenDetails") or {}
            created_at = item.get("createdAt")
            if created_at is None:
                created_at = token_details.get("time")
            snapshots.append(
                WaveTokenSnapshot(
                    token=token,
                    name=str(item["name"]) if item.get("name") else None,
                    symbol=str(item["symbol"]) if item.get("symbol") else None,
                    price_usd=_number(item.get("priceUsd")),
                    liquidity_usd=_number(item.get("liquidityUsd")),
                    market_cap_usd=_number(item.get("marketCapUsd")),
                    created_at_ms=_timestamp_ms(created_at),
                    # A zero holder count alongside active trades is an indexing gap,
                    # not proof that the token truly has no holders.
                    holders=_optional_positive_integer(item.get("holders")),
                    buys=_integer(item.get("buys")),
                    sells=_integer(item.get("sells")),
                    total_transactions=_integer(item.get("totalTransactions")),
                    volume_5m_usd=_number(item.get("volume_5m")),
                    volume_1h_usd=_number(item.get("volume_1h")),
                    volume_24h_usd=_number(item.get("volume_24h")),
                    top10_pct=_optional_number(item.get("top10")),
                    dev_pct=_optional_number(item.get("dev")),
                    insiders_pct=_optional_number(item.get("insiders")),
                    snipers_pct=_optional_number(item.get("snipers")),
                    risk_score=_optional_number(item.get("riskScore")),
                    lp_burn_pct=_optional_number(item.get("lpBurn")),
                    mint_authority=(
                        str(item["mintAuthority"])
                        if item.get("mintAuthority")
                        else None
                    ),
                    freeze_authority=(
                        str(item["freezeAuthority"])
                        if item.get("freezeAuthority")
                        else None
                    ),
                    market=str(item["market"]) if item.get("market") else None,
                    pool_address=(
                        str(item["poolAddress"])
                        if item.get("poolAddress")
                        else None
                    ),
                )
            )
        self.last_wave_diagnostics = {
            "requested_limit": limit,
            "source_item_count": len(source_items),
            "source_invalid_count": invalid_count,
            "source_duplicate_count": duplicate_count,
            "returned_count": len(snapshots),
            "cache_used": False,
        }
        return snapshots

    def token_traders(
        self,
        token: str,
        *,
        limit: int = 10,
        min_trades: int = 3,
        sort_by: str = "realized",
        direction: str = "desc",
        active_only: bool = False,
    ) -> list[TokenTraderSeed]:
        """Return real wallet addresses seen trading one selected liquid token."""
        if not is_solana_address(token):
            raise ValueError("mint Solana inválido")
        if not 1 <= limit <= 200:
            raise ValueError("limit precisa estar entre 1 e 200")
        if sort_by not in {
            "holding", "value", "pnl", "realized", "unrealized", "invested",
            "roi", "last_trade", "first_trade",
        }:
            raise ValueError("ordenação inválida para traders do token")
        if direction not in {"asc", "desc"}:
            raise ValueError("direção inválida para traders do token")
        payload = self._request(
            f"/v2/pnl/tokens/{token}/traders",
            {
                "sort": sort_by,
                "direction": direction,
                "limit": limit,
                "excludeArbitrage": "true",
                "excludeZeroBuys": "true",
                "activeOnly": str(active_only).lower(),
                "minTrades": min_trades,
            },
        )
        seeds = []
        seen = set()
        for item in payload.get("traders") or []:
            if not isinstance(item, dict):
                continue
            address = str(item.get("wallet") or "")
            identity = item.get("identity") or {}
            tags = {str(tag).lower() for tag in identity.get("tags") or []}
            if (
                not is_solana_address(address)
                or address in seen
                or str(identity.get("type") or "").lower() == "developer"
                or "developer" in tags
            ):
                continue
            seen.add(address)
            seeds.append(TokenTraderSeed(address=address, token=token))
        return seeds

    def wallet_history(self, address: str, period: str = "90d") -> WalletHistory:
        if not is_solana_address(address):
            raise ValueError("endereço público Solana inválido")
        if period not in {"1d", "7d", "14d", "30d", "90d", "all"}:
            raise ValueError("período inválido para o histórico da wallet")
        payload = self._request(
            f"/v2/pnl/wallets/{address}/history",
            {"period": period, "currency": "usd", "limit": 365},
        )
        activities = []
        for item in payload.get("days") or []:
            if not isinstance(item, dict) or not item.get("date"):
                continue
            activity = item.get("activity") or {}
            counts = activity.get("counts") or {}
            averages = activity.get("averages") or {}
            volume = activity.get("volume") or {}
            hold_time = averages.get("holdTimeSecs")
            activities.append(
                DailyWalletActivity(
                    date=str(item["date"]),
                    realized_pnl_usd=_number((activity.get("pnl") or {}).get("realized")),
                    buys=_integer(counts.get("buys")),
                    sells=_integer(counts.get("sells")),
                    invested_usd=_number(volume.get("costUsd")),
                    volume_usd=_number(volume.get("total")),
                    avg_hold_seconds=None if hold_time is None else _number(hold_time),
                )
            )
        return WalletHistory(address=address, days=tuple(sorted(activities, key=lambda day: day.date)))

    def wallet_positions(
        self,
        address: str,
        *,
        period: str = "30d",
        limit: int = 50,
    ) -> WalletPositions:
        """Return recent positions and current token liquidity without writing locally."""
        if not is_solana_address(address):
            raise ValueError("endereço público Solana inválido")
        if period not in {"1d", "7d", "14d", "30d", "90d", "all"}:
            raise ValueError("período inválido para as posições da wallet")
        if not 1 <= limit <= 200:
            raise ValueError("limit precisa estar entre 1 e 200")
        payload = self._request(
            f"/v2/pnl/wallets/{address}/positions",
            {
                "pnlMode": "strict",
                "sort": "last_trade",
                "direction": "desc",
                "period": period,
                "filter": "all",
                "limit": limit,
            },
        )
        positions = []
        for item in payload.get("positions") or []:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token") or "")
            if not is_solana_address(token):
                continue
            meta = item.get("meta") or {}
            counts = item.get("counts") or {}
            timing = item.get("timing") or {}
            averages = item.get("averages") or {}
            positions.append(
                TokenPosition(
                    token=token,
                    symbol=str(meta["symbol"]) if meta.get("symbol") else None,
                    realized_pnl_usd=_number((item.get("pnl") or {}).get("realized")),
                    invested_usd=_number(item.get("invested")),
                    roi_pct=_number(item.get("roi")),
                    trades=_integer(counts.get("total")),
                    average_buy_usd=_optional_number(averages.get("buy")),
                    hold_time_seconds=_optional_number(timing.get("holdTimeSecs")),
                    last_trade_ms=_optional_integer(timing.get("lastTrade")),
                    liquidity_usd=_optional_number(meta.get("liquidity")),
                    market_cap_usd=_optional_number(meta.get("marketCap")),
                    primary_market=(
                        str(meta["primaryMarket"])
                        if meta.get("primaryMarket")
                        else None
                    ),
                )
            )
        pagination = payload.get("pagination") or {}
        return WalletPositions(
            address=address,
            positions=tuple(positions),
            total_available=_integer(pagination.get("total"), len(positions)),
            pnl_mode=str(pagination.get("pnlMode") or "strict"),
        )
