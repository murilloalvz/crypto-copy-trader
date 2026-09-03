import asyncio
import base64
import json
import struct
import time
from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
PUMP_CREATE_EVENT_DISCRIMINATOR = bytes([27, 114, 169, 77, 222, 235, 99, 118])
LAMPORTS_PER_SOL = 1_000_000_000
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True)
class PumpTradeEvent:
    mint: str
    sol_amount: int
    token_amount: int
    is_buy: bool
    user: str
    timestamp: int


@dataclass(frozen=True)
class PumpCreateEvent:
    mint: str
    bonding_curve: str
    user: str
    creator: str
    timestamp: int


@dataclass(frozen=True)
class PumpLogNotification:
    signature: str
    slot: int
    observed_at: int
    events: tuple[PumpTradeEvent, ...]
    lifecycle_events: tuple[PumpCreateEvent, ...] = ()


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


def _read_borsh_string(payload: bytes, offset: int, *, field_name: str) -> tuple[str, int]:
    if offset + 4 > len(payload):
        raise ValueError(f"truncated Pump CreateEvent {field_name} length")
    length = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    end = offset + length
    if end > len(payload):
        raise ValueError(f"truncated Pump CreateEvent {field_name}")
    try:
        value = payload[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 Pump CreateEvent {field_name}") from exc
    return value, end


def rpc_http_to_ws_url(rpc_url: str) -> str:
    raw = _required(rpc_url, "rpc_url")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("rpc_url must use http(s) or ws(s)")
    scheme = {
        "http": "ws",
        "https": "wss",
        "ws": "ws",
        "wss": "wss",
    }[parsed.scheme]
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
            {"mentions": [PUMP_PROGRAM_ID]},
            {"commitment": commitment},
        ],
    }


def decode_pump_trade_event_payload(payload: bytes) -> PumpTradeEvent | None:
    """Decode the stable causal prefix of Pump's Anchor TradeEvent.

    The public Pump IDL currently defines the event prefix as:
    discriminator, mint(pubkey), sol_amount(u64), token_amount(u64), is_buy(bool),
    user(pubkey), timestamp(i64). Later fields are intentionally ignored here.

    Events with a different discriminator are not Pump TradeEvents.
    """

    if len(payload) < 8 or payload[:8] != PUMP_TRADE_EVENT_DISCRIMINATOR:
        return None
    minimum = 8 + 32 + 8 + 8 + 1 + 32 + 8
    if len(payload) < minimum:
        raise ValueError("truncated Pump TradeEvent payload")

    offset = 8
    mint = _b58encode(payload[offset : offset + 32])
    offset += 32
    sol_amount = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    token_amount = struct.unpack_from("<Q", payload, offset)[0]
    offset += 8
    is_buy_raw = payload[offset]
    offset += 1
    if is_buy_raw not in {0, 1}:
        raise ValueError("invalid Pump TradeEvent is_buy flag")
    user = _b58encode(payload[offset : offset + 32])
    offset += 32
    timestamp = struct.unpack_from("<q", payload, offset)[0]

    if timestamp < 0:
        raise ValueError("Pump TradeEvent timestamp cannot be negative")
    if token_amount <= 0:
        raise ValueError("Pump TradeEvent token_amount must be positive")

    return PumpTradeEvent(
        mint=mint,
        sol_amount=int(sol_amount),
        token_amount=int(token_amount),
        is_buy=bool(is_buy_raw),
        user=user,
        timestamp=int(timestamp),
    )


def decode_pump_create_event_payload(payload: bytes) -> PumpCreateEvent | None:
    """Decode the causal prefix needed from Pump's public Anchor CreateEvent.

    CreateEvent begins with three Borsh strings (name, symbol, uri), followed by mint,
    bonding_curve, user, creator and timestamp. Later reserve/config fields are intentionally
    ignored because lifecycle acquisition only needs token identity and market start time.
    """

    if len(payload) < 8 or payload[:8] != PUMP_CREATE_EVENT_DISCRIMINATOR:
        return None
    offset = 8
    for field_name in ("name", "symbol", "uri"):
        _, offset = _read_borsh_string(payload, offset, field_name=field_name)

    minimum_tail = 32 * 4 + 8
    if offset + minimum_tail > len(payload):
        raise ValueError("truncated Pump CreateEvent identity prefix")
    mint = _b58encode(payload[offset : offset + 32])
    offset += 32
    bonding_curve = _b58encode(payload[offset : offset + 32])
    offset += 32
    user = _b58encode(payload[offset : offset + 32])
    offset += 32
    creator = _b58encode(payload[offset : offset + 32])
    offset += 32
    timestamp = struct.unpack_from("<q", payload, offset)[0]
    if timestamp < 0:
        raise ValueError("Pump CreateEvent timestamp cannot be negative")
    return PumpCreateEvent(
        mint=mint,
        bonding_curve=bonding_curve,
        user=user,
        creator=creator,
        timestamp=int(timestamp),
    )


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


def decode_program_data_log(line: str) -> PumpTradeEvent | None:
    """Backward-compatible helper that returns only Pump TradeEvents."""

    raw = _decode_program_data_bytes(line)
    if raw is None:
        return None
    return decode_pump_trade_event_payload(raw)


def parse_logs_notification(
    message: dict,
    *,
    observed_at: int | None = None,
) -> PumpLogNotification | None:
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

    events: list[PumpTradeEvent] = []
    lifecycle_events: list[PumpCreateEvent] = []
    for line in logs:
        raw = _decode_program_data_bytes(str(line))
        if raw is None:
            continue
        trade_event = decode_pump_trade_event_payload(raw)
        if trade_event is not None:
            if learned_at < trade_event.timestamp:
                raise ValueError("observed_at cannot precede Pump event timestamp")
            events.append(trade_event)
            continue
        create_event = decode_pump_create_event_payload(raw)
        if create_event is not None:
            if learned_at < create_event.timestamp:
                raise ValueError("observed_at cannot precede Pump create timestamp")
            lifecycle_events.append(create_event)

    return PumpLogNotification(
        signature=signature,
        slot=slot,
        observed_at=learned_at,
        events=tuple(events),
        lifecycle_events=tuple(lifecycle_events),
    )


def persist_pump_notification(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
) -> int:
    """Persist decoded Pump lifecycle and SOL-paired trades into the market store.

    The return value remains the count of newly persisted TradeEvents for backward compatibility.
    CreateEvents are persisted separately as lifecycle observations. Pump now supports non-SOL
    quote assets; the stable TradeEvent prefix does not expose quote_mint until later in the
    payload, so this v1 adapter only persists trades whose `sol_amount` is positive. USD notional
    and price remain missing rather than being invented.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")

    for index, event in enumerate(notification.lifecycle_events):
        record_market_lifecycle(
            acquisition_run_key=run_key,
            event_key=f"pump-create:{notification.signature}:{index}",
            source_provider="solana_logs_subscribe",
            observation=MarketLifecycleObservation(
                token_mint=event.mint,
                market_started_at=event.timestamp,
                observed_at=notification.observed_at,
                venue="pump_bonding_curve",
            ),
        )

    inserted = 0
    for index, event in enumerate(notification.events):
        if event.sol_amount <= 0:
            continue
        observation = MarketTradeObservation(
            token_mint=event.mint,
            side="buy" if event.is_buy else "sell",
            chain_time=event.timestamp,
            observed_at=notification.observed_at,
            wallet_address=event.user,
            notional_usd=None,
            price_usd=None,
            venue="pump_bonding_curve",
            transaction_key=notification.signature,
        )
        if record_market_trade(
            acquisition_run_key=run_key,
            event_key=f"pump:{notification.signature}:{index}",
            source_provider="solana_logs_subscribe",
            observation=observation,
        ):
            inserted += 1
    return inserted


async def iter_pump_log_notifications(
    *,
    rpc_url: str,
    commitment: str = "confirmed",
    reconnect_initial_seconds: float = 1.0,
    reconnect_max_seconds: float = 30.0,
) -> AsyncIterator[PumpLogNotification]:
    """Yield successful Pump log notifications with bounded reconnect backoff."""

    if reconnect_initial_seconds <= 0 or reconnect_max_seconds < reconnect_initial_seconds:
        raise ValueError("invalid reconnect backoff")

    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
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
                        notification.events or notification.lifecycle_events
                    ):
                        yield notification
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(reconnect_max_seconds, backoff * 2)
