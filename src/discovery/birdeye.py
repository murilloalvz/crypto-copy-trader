import json
import ssl
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.config import settings
from src.discovery.models import LeaderboardWallet, WalletPeriodMetrics

BIRDEYE_BASE_URL = "https://public-api.birdeye.so"
BASE58_ALPHABET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


class BirdeyeError(RuntimeError):
    """Base exception for a safe, read-only Birdeye request."""


class BirdeyeConfigurationError(BirdeyeError):
    pass


class BirdeyeAuthenticationError(BirdeyeError):
    pass


class BirdeyeRateLimitError(BirdeyeError):
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


def is_solana_address(value: str) -> bool:
    """Validate that a Base58 string decodes to one 32-byte Solana public key."""
    if not 32 <= len(value) <= 44 or any(char not in BASE58_ALPHABET for char in value):
        return False
    number = 0
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    for char in value:
        number = number * 58 + alphabet.index(char)
    decoded_length = (number.bit_length() + 7) // 8 if number else 0
    decoded_length += len(value) - len(value.lstrip("1"))
    return decoded_length == 32


def _tls12_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def _is_ssl_error(error: BaseException) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(error, ssl.SSLError) or isinstance(reason, ssl.SSLError)


class BirdeyeClient:
    """Small stdlib client for Birdeye's discovery and wallet PnL endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BIRDEYE_BASE_URL,
        timeout: int = 30,
        max_attempts: int = 3,
        request_interval_seconds: float = 1.05,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.api_key = (settings.birdeye_api_key if api_key is None else api_key).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self._sleeper = sleeper
        self._clock = clock
        self._last_request_at: float | None = None

    def _require_key(self) -> None:
        if not self.api_key:
            raise BirdeyeConfigurationError(
                "BIRDEYE_API_KEY não configurada. Crie uma chave no Birdeye Data "
                "Services e coloque somente o valor no arquivo .env."
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
    def _error_message(error: HTTPError) -> str:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            return str(payload.get("message") or payload.get("error") or error.reason)
        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
            return str(error.reason)

    def _request(self, path: str, params: dict) -> dict:
        self._require_key()
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "X-API-KEY": self.api_key,
                "x-chain": "solana",
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
                message = self._error_message(exc)
                if exc.code in {401, 403}:
                    raise BirdeyeAuthenticationError(
                        f"Birdeye recusou a API key (HTTP {exc.code}): {message}"
                    ) from exc
                last_error = exc
                if exc.code == 429:
                    if attempt + 1 == self.max_attempts:
                        raise BirdeyeRateLimitError(
                            "Limite de requisições do Birdeye atingido após novas tentativas."
                        ) from exc
                elif exc.code < 500:
                    raise BirdeyeError(f"Birdeye HTTP {exc.code}: {message}") from exc
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

        raise BirdeyeError(f"Birdeye indisponível após {self.max_attempts} tentativas: {last_error}")

    @staticmethod
    def _validate_payload(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise BirdeyeError("Resposta inválida do Birdeye: objeto JSON esperado.")
        if payload.get("success") is not True:
            raise BirdeyeError(str(payload.get("message") or "Birdeye retornou success=false."))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BirdeyeError("Resposta inválida do Birdeye: campo data ausente.")
        return data

    def trader_leaderboard(
        self,
        limit: int = 250,
        *,
        period: str = "30d",
        sort_by: str = "realized_pnl",
    ) -> list[LeaderboardWallet]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit precisa estar entre 1 e 10000")
        if period not in {"today", "yesterday", "1W", "30d", "90d"}:
            raise ValueError("período inválido para o leaderboard")
        if sort_by not in {"PnL", "realized_pnl", "unrealized_pnl"}:
            raise ValueError("ordenação inválida para o leaderboard")

        results: list[LeaderboardWallet] = []
        seen: set[str] = set()
        offset = 0
        while len(results) < limit:
            page_size = min(100, limit - len(results))
            data = self._request(
                "/trader/gainers-losers",
                {
                    "type": period,
                    "sort_by": sort_by,
                    "sort_type": "desc",
                    "offset": offset,
                    "limit": page_size,
                },
            )
            items = data.get("items") or []
            if not isinstance(items, list):
                raise BirdeyeError("Resposta inválida do leaderboard: items não é uma lista.")
            offset += len(items)
            before = len(results)
            for item in items:
                if not isinstance(item, dict):
                    continue
                address = str(item.get("address") or "")
                if address in seen or not is_solana_address(address):
                    continue
                seen.add(address)
                results.append(
                    LeaderboardWallet(
                        address=address,
                        pnl_usd=_number(item.get("pnl")),
                        volume_usd=_number(item.get("volume")),
                        trade_count=_integer(item.get("trade_count")),
                    )
                )
                if len(results) == limit:
                    break
            if len(items) < page_size or offset >= 10_000:
                break
        return results

    def wallet_pnl(self, address: str, period: str = "30d") -> WalletPeriodMetrics:
        if not is_solana_address(address):
            raise ValueError("endereço público Solana inválido")
        if period not in {"24h", "7d", "30d", "90d", "all"}:
            raise ValueError("período inválido para o PnL da wallet")
        data = self._request(
            "/wallet/v2/pnl/summary",
            {
                "wallet": address,
                "duration": period,
                "position_scope": "duration_only",
            },
        )
        summary = data.get("summary") or {}
        counts = summary.get("counts") or {}
        cashflow = summary.get("cashflow_usd") or {}
        pnl = summary.get("pnl") or {}
        current_value = cashflow.get("current_value")
        return WalletPeriodMetrics(
            period=period,
            unique_tokens=_integer(summary.get("unique_tokens")),
            total_buy=_integer(counts.get("total_buy")),
            total_sell=_integer(counts.get("total_sell")),
            total_trade=_integer(counts.get("total_trade")),
            total_win=_integer(counts.get("total_win")),
            total_loss=_integer(counts.get("total_loss")),
            win_rate_pct=_number(counts.get("win_rate")),
            total_invested_usd=_number(cashflow.get("total_invested")),
            total_sold_usd=_number(cashflow.get("total_sold")),
            current_value_usd=None if current_value is None else _number(current_value),
            realized_pnl_usd=_number(pnl.get("realized_profit_usd")),
            roi_pct=_number(pnl.get("realized_profit_percent")),
            unrealized_pnl_usd=_number(pnl.get("unrealized_usd")),
            total_pnl_usd=_number(pnl.get("total_usd")),
            avg_profit_per_trade_usd=_number(pnl.get("avg_profit_per_trade_usd")),
        )
