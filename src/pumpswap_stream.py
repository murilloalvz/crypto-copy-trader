import asyncio
import base64
import json
import struct
import time
from dataclasses import dataclass, replace
from typing import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.pumpswap_pool_store import (
    PumpSwapPoolMapping,
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)
from src.solana import SolanaClient, SolanaRPCError


PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMPSWAP_BUY_EVENT_DISCRIMINATOR = bytes([103, 244, 82, 31, 44, 245, 119, 119])
PUMPSWAP_SELL_EVENT_DISCRIMINATOR = bytes([62, 47, 55, 10, 165, 3, 220, 42])
PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR = bytes([177, 49, 12, 210, 160, 118, 167, 116])
PUMPSWAP_POOL_ACCOUNT_DISCRIMINATOR = bytes([241, 154, 109, 4, 17, 177, 109, 188])
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True)
class PumpSwapTradeEvent:
    side: str
    pool: str
    user: str
    timestamp: int
    base_amount_raw: int
    quote_amount_raw: int
    event_index: int = 0


@dataclass(frozen=True)
class PumpSwapCreatePoolEvent:
    pool: str
    creator: str
    base_mint: str
    quote_mint: str
    base_mint_decimals: int
    quote_mint_decimals: int
    timestamp: int
    event_index: int = 0


@dataclass(frozen=True)
class PumpSwapLogNotification:
    signature: str
    slot: int
    observed_at: int
    trade_events: tuple[PumpSwapTradeEvent, ...]
    lifecycle_events: tuple[PumpSwapCreatePoolEvent, ...] = ()


@dataclass(frozen=True)
class PumpSwapPersistResult:
    newly_persisted_trades: int
    duplicate_or_replayed_trades: int
    unresolved_trades: int
    newly_persisted_lifecycle: int


@dataclass(frozen=True)
class PumpSwapPoolAccount:
    base_mint: str
    quote_mint: str


class PumpSwapPoolResolver:
    """Resolve PumpSwap pool identity while preserving first-known availability time."""

    def __init__(
        self,
        *,
        acquisition_run_key: str,
        commitment: str = "confirmed",
        rpc_url: str | None = None,
        fallback_urls: tuple[str, ...] | list[str] | None = None,
        timeout: int = 10,
        client: SolanaClient | None = None,
    ):
        self.acquisition_run_key = _required(acquisition_run_key, "acquisition_run_key")
        normalized = str(commitment).strip().lower()
        if normalized not in {"processed", "confirmed", "finalized"}:
            raise ValueError("unsupported commitment")
        self.commitment = normalized
        self.client = client or SolanaClient(
            rpc_url=rpc_url,
            timeout=timeout,
            fallback_urls=fallback_urls,
        )
        self._cache: dict[str, PumpSwapPoolMapping] = {}
        self.cache_hits = 0
        self.store_hits = 0
        self.hydration_attempts = 0
        self.hydration_successes = 0
        self.hydration_failures = 0

    def learn_from_create(
        self,
        event: PumpSwapCreatePoolEvent,
        *,
        observed_at: int,
    ) -> PumpSwapPoolMapping:
        learned_at = int(observed_at)
        if learned_at < event.timestamp:
            raise ValueError("pool mapping observed_at cannot precede CreatePoolEvent timestamp")
        existing = load_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=event.pool,
        )
        if existing is not None:
            if (existing.base_mint, existing.quote_mint) != (event.base_mint, event.quote_mint):
                raise ValueError("CreatePoolEvent conflicts with persisted PumpSwap pool mapping")
            if learned_at < existing.observed_at:
                raise ValueError("CreatePoolEvent cannot backdate PumpSwap pool mapping")
            self._cache[event.pool] = existing
            return existing

        record_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=event.pool,
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
            observed_at=learned_at,
            source_provider="solana_logs_subscribe_create_pool",
        )
        mapping = PumpSwapPoolMapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=event.pool,
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
            observed_at=learned_at,
            source_provider="solana_logs_subscribe_create_pool",
        )
        self._cache[event.pool] = mapping
        return mapping

    async def resolve(
        self,
        pool_address: str,
        *,
        as_of: int,
    ) -> PumpSwapPoolMapping | None:
        pool = _required(pool_address, "pool_address")
        decision_time = int(as_of)
        if decision_time < 0:
            raise ValueError("as_of must be non-negative")

        cached = self._cache.get(pool)
        if cached is not None and cached.observed_at <= decision_time:
            self.cache_hits += 1
            return cached

        stored = load_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
            as_of=decision_time,
        )
        if stored is not None:
            self.store_hits += 1
            self._cache[pool] = stored
            return stored

        self.hydration_attempts += 1
        try:
            account = await asyncio.to_thread(self._load_pool_account, pool)
        except (SolanaRPCError, ValueError, TypeError, KeyError):
            self.hydration_failures += 1
            return None
        if account is None:
            self.hydration_failures += 1
            return None

        learned_at = int(time.time())
        record_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
            base_mint=account.base_mint,
            quote_mint=account.quote_mint,
            observed_at=learned_at,
            source_provider="solana_get_account_info",
        )
        mapping = PumpSwapPoolMapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
            base_mint=account.base_mint,
            quote_mint=account.quote_mint,
            observed_at=learned_at,
            source_provider="solana_get_account_info",
        )
        self._cache[pool] = mapping
        self.hydration_successes += 1
        return mapping

    def _load_pool_account(self, pool_address: str) -> PumpSwapPoolAccount | None:
        result = self.client.call(
            "getAccountInfo",
            [
                pool_address,
                {
                    "encoding": "base64",
                    "commitment": self.commitment,
                },
            ],
        ) or {}
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            return None
        owner = value.get("owner")
        if owner != PUMPSWAP_PROGRAM_ID:
            raise ValueError("PumpSwap pool account has unexpected owner")
        data = value.get("data")
        if not isinstance(data, (list, tuple)) or not data:
            raise ValueError("PumpSwap pool account missing base64 data")
        try:
            raw = base64.b64decode(str(data[0]), validate=True)
        except Exception as exc:
            raise ValueError("invalid PumpSwap pool account base64") from exc
        return decode_pumpswap_pool_account(raw)


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _b58encode(raw: bytes) -> str:
    if not raw:
        return ""
    zeros = 0
    for item in raw:
        if item != 0:
            break
        zeros += 1
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    return "1" * zeros + encoded


def rpc_http_to_ws_url(rpc_url: str) -> str:
    raw = _required(rpc_url, "rpc_url")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("rpc_url must use http(s) or ws(s)")
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}[parsed.scheme]
    return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def build_logs_subscribe_request(
    *,
    request_id: int = 1,
    commitment: str = "confirmed",
) -> dict:
    if request_id <= 0:
        raise ValueError("request_id must be positive")
    if commitment not in {"processed", "confirmed", "finalized"}:
        raise ValueError("unsupported commitment")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [PUMPSWAP_PROGRAM_ID]},
            {"commitment": commitment},
        ],
    }


def _decode_trade_event_payload(payload: bytes, *, side: str) -> PumpSwapTradeEvent | None:
    discriminator = (
        PUMPSWAP_BUY_EVENT_DISCRIMINATOR if side == "buy" else PUMPSWAP_SELL_EVENT_DISCRIMINATOR
    )
    if len(payload) < 8 or payload[:8] != discriminator:
        return None
    minimum = 8 + 8 + (13 * 8) + 32 + 32
    if len(payload) < minimum:
        raise ValueError(f"truncated PumpSwap {side} event payload")

    offset = 8
    timestamp = struct.unpack_from("<q", payload, offset)[0]
    offset += 8
    amounts = struct.unpack_from("<13Q", payload, offset)
    offset += 13 * 8
    pool = _b58encode(payload[offset : offset + 32])
    offset += 32
    user = _b58encode(payload[offset : offset + 32])

    if timestamp < 0:
        raise ValueError("PumpSwap trade timestamp cannot be negative")
    if amounts[0] <= 0:
        raise ValueError("PumpSwap base amount must be positive")
    return PumpSwapTradeEvent(
        side=side,
        pool=pool,
        user=user,
        timestamp=int(timestamp),
        base_amount_raw=int(amounts[0]),
        quote_amount_raw=int(amounts[6]),
    )


def decode_pumpswap_buy_event_payload(payload: bytes) -> PumpSwapTradeEvent | None:
    return _decode_trade_event_payload(payload, side="buy")


def decode_pumpswap_sell_event_payload(payload: bytes) -> PumpSwapTradeEvent | None:
    return _decode_trade_event_payload(payload, side="sell")


def decode_pumpswap_create_pool_event_payload(payload: bytes) -> PumpSwapCreatePoolEvent | None:
    if len(payload) < 8 or payload[:8] != PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR:
        return None
    minimum = 8 + 8 + 2 + (32 * 3) + 2 + (7 * 8) + 1 + 32
    if len(payload) < minimum:
        raise ValueError("truncated PumpSwap CreatePoolEvent payload")

    offset = 8
    timestamp = struct.unpack_from("<q", payload, offset)[0]
    offset += 8
    offset += 2  # index u16
    creator = _b58encode(payload[offset : offset + 32])
    offset += 32
    base_mint = _b58encode(payload[offset : offset + 32])
    offset += 32
    quote_mint = _b58encode(payload[offset : offset + 32])
    offset += 32
    base_decimals = int(payload[offset])
    quote_decimals = int(payload[offset + 1])
    offset += 2
    offset += 7 * 8
    offset += 1  # pool_bump
    pool = _b58encode(payload[offset : offset + 32])

    if timestamp < 0:
        raise ValueError("PumpSwap CreatePoolEvent timestamp cannot be negative")
    return PumpSwapCreatePoolEvent(
        pool=pool,
        creator=creator,
        base_mint=base_mint,
        quote_mint=quote_mint,
        base_mint_decimals=base_decimals,
        quote_mint_decimals=quote_decimals,
        timestamp=int(timestamp),
    )


def decode_pumpswap_pool_account(payload: bytes) -> PumpSwapPoolAccount:
    minimum = 8 + 1 + 2 + 32 + 32 + 32
    if len(payload) < minimum:
        raise ValueError("truncated PumpSwap Pool account")
    if payload[:8] != PUMPSWAP_POOL_ACCOUNT_DISCRIMINATOR:
        raise ValueError("unexpected PumpSwap Pool account discriminator")
    offset = 8
    offset += 1  # pool_bump
    offset += 2  # index
    offset += 32  # creator
    base_mint = _b58encode(payload[offset : offset + 32])
    offset += 32
    quote_mint = _b58encode(payload[offset : offset + 32])
    return PumpSwapPoolAccount(base_mint=base_mint, quote_mint=quote_mint)


def _decode_program_data_bytes(line: str) -> bytes | None:
    prefix = "Program data: "
    if not str(line).startswith(prefix):
        return None
    encoded = str(line)[len(prefix) :].strip()
    if not encoded:
        raise ValueError("empty Program data log")
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 Program data log") from exc


def parse_logs_notification(
    message: dict,
    *,
    observed_at: int | None = None,
) -> PumpSwapLogNotification | None:
    if message.get("method") != "logsNotification":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        raise ValueError("logsNotification missing params")
    result = params.get("result")
    if not isinstance(result, dict):
        raise ValueError("logsNotification missing result")
    context = result.get("context")
    value = result.get("value")
    if not isinstance(context, dict) or not isinstance(value, dict):
        raise ValueError("logsNotification missing context/value")
    if value.get("err") is not None:
        return None

    signature = _required(value.get("signature", ""), "signature")
    slot = int(context.get("slot"))
    logs = value.get("logs")
    if slot < 0 or not isinstance(logs, list):
        raise ValueError("invalid logsNotification slot/logs")
    learned_at = int(time.time()) if observed_at is None else int(observed_at)
    if learned_at < 0:
        raise ValueError("observed_at must be non-negative")

    trades: list[PumpSwapTradeEvent] = []
    lifecycle: list[PumpSwapCreatePoolEvent] = []
    program_data_index = 0
    for line in logs:
        raw = _decode_program_data_bytes(str(line))
        if raw is None:
            continue
        event_index = program_data_index
        program_data_index += 1

        buy = decode_pumpswap_buy_event_payload(raw)
        if buy is not None:
            if learned_at < buy.timestamp:
                raise ValueError("observed_at cannot precede PumpSwap buy timestamp")
            trades.append(replace(buy, event_index=event_index))
            continue
        sell = decode_pumpswap_sell_event_payload(raw)
        if sell is not None:
            if learned_at < sell.timestamp:
                raise ValueError("observed_at cannot precede PumpSwap sell timestamp")
            trades.append(replace(sell, event_index=event_index))
            continue
        create = decode_pumpswap_create_pool_event_payload(raw)
        if create is not None:
            if learned_at < create.timestamp:
                raise ValueError("observed_at cannot precede PumpSwap create timestamp")
            lifecycle.append(replace(create, event_index=event_index))

    return PumpSwapLogNotification(
        signature=signature,
        slot=slot,
        observed_at=learned_at,
        trade_events=tuple(trades),
        lifecycle_events=tuple(lifecycle),
    )


async def persist_pumpswap_notification(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
) -> PumpSwapPersistResult:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("PumpSwap resolver run key does not match persistence run key")

    newly_persisted_lifecycle = 0
    for event in notification.lifecycle_events:
        resolver.learn_from_create(event, observed_at=notification.observed_at)
        if record_market_lifecycle(
            acquisition_run_key=run_key,
            event_key=f"pumpswap-create:{notification.signature}:{event.event_index}",
            source_provider="solana_logs_subscribe",
            observation=MarketLifecycleObservation(
                token_mint=event.base_mint,
                market_started_at=event.timestamp,
                observed_at=notification.observed_at,
                venue="pumpswap",
            ),
        ):
            newly_persisted_lifecycle += 1

    inserted = 0
    duplicates = 0
    unresolved = 0
    for event in notification.trade_events:
        mapping = await resolver.resolve(event.pool, as_of=notification.observed_at)
        if mapping is None:
            unresolved += 1
            continue
        effective_observed_at = max(notification.observed_at, mapping.observed_at)
        observation = MarketTradeObservation(
            token_mint=mapping.base_mint,
            side=event.side,
            chain_time=event.timestamp,
            observed_at=effective_observed_at,
            wallet_address=event.user,
            notional_usd=None,
            price_usd=None,
            venue="pumpswap",
            transaction_key=notification.signature,
        )
        if record_market_trade(
            acquisition_run_key=run_key,
            event_key=f"pumpswap-{event.side}:{notification.signature}:{event.event_index}",
            source_provider="solana_logs_subscribe",
            observation=observation,
        ):
            inserted += 1
        else:
            duplicates += 1

    return PumpSwapPersistResult(
        newly_persisted_trades=inserted,
        duplicate_or_replayed_trades=duplicates,
        unresolved_trades=unresolved,
        newly_persisted_lifecycle=newly_persisted_lifecycle,
    )


async def iter_pumpswap_log_notifications(
    *,
    rpc_url: str,
    commitment: str = "confirmed",
    reconnect_initial_seconds: float = 1.0,
    reconnect_max_seconds: float = 30.0,
) -> AsyncIterator[PumpSwapLogNotification]:
    if reconnect_initial_seconds <= 0 or reconnect_max_seconds < reconnect_initial_seconds:
        raise ValueError("invalid reconnect backoff")
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("websockets dependency is required") from exc

    ws_url = rpc_http_to_ws_url(rpc_url)
    backoff = reconnect_initial_seconds
    while True:
        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_queue=4096,
            ) as websocket:
                await websocket.send(json.dumps(build_logs_subscribe_request(commitment=commitment)))
                ack_raw = await asyncio.wait_for(websocket.recv(), timeout=15)
                ack = json.loads(ack_raw)
                if "error" in ack:
                    raise RuntimeError(f"logsSubscribe failed: {ack['error']}")
                if not isinstance(ack.get("result"), int):
                    raise RuntimeError("logsSubscribe returned no subscription id")
                backoff = reconnect_initial_seconds

                async for raw in websocket:
                    decoded = json.loads(raw)
                    notification = parse_logs_notification(decoded)
                    if notification is not None and (
                        notification.trade_events or notification.lifecycle_events
                    ):
                        yield notification
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(reconnect_max_seconds, backoff * 2)
