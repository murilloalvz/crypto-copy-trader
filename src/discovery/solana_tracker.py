import json
import ssl
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.config import settings
from src.discovery.birdeye import is_solana_address
from src.discovery.models import DailyWalletActivity, TraderSnapshot, WalletHistory

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


def _tls12_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def _is_ssl_error(error: BaseException) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(error, ssl.SSLError) or isinstance(reason, ssl.SSLError)


class SolanaTrackerClient:
    """Read-only client for Solana Tracker's PnL V2 discovery endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = SOLANA_TRACKER_BASE_URL,
        timeout: int = 30,
        max_attempts: int = 3,
        request_interval_seconds: float = 0.36,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        configured = settings.solana_tracker_api_key if api_key is None else api_key
        self.api_key = configured.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
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
                if _is_ssl_error(exc):
                    try:
                        payload = self._read_payload(request, _tls12_context())
                    except (URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as tls_exc:
                        last_error = tls_exc
                    else:
                        return self._validate_payload(payload)
            else:
                return self._validate_payload(payload)
            if attempt + 1 < self.max_attempts:
                self._sleeper(min(2**attempt, 4))
        raise SolanaTrackerError(
            f"Solana Tracker indisponível após {self.max_attempts} tentativas: {last_error}"
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

        results: list[TraderSnapshot] = []
        seen: set[str] = set()
        cursor = None
        while len(results) < limit:
            page_size = min(100, limit - len(results))
            payload = self._request(
                "/v2/pnl/leaderboard/top",
                {
                    "sort": sort_by,
                    "direction": "desc",
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
