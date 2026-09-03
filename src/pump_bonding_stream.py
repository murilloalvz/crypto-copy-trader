import asyncio
import base64
import json
import struct
import time
from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation


PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
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
class PumpLogNotification:
    signature: str
    slot: int
    observed_at: int
    events: tuple[PumpTradeEvent, ...]


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


def decode_program_data_log(line: str) -> PumpTradeEvent | None:
    prefix = "Program data: "
    if not str(line).startswith(prefix):
        return None
    encoded = str(line)[len(prefix) :].strip()
    if not encoded:
        raise ValueError("empty Program data log")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 Program data log") from exc
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
    for line in logs:
        event = decode_program_data_log(str(line))
        if event is not None:
            if learned_at < event.timestamp:
                raise ValueError("observed_at cannot precede Pump event timestamp")
            events.append(event)

    return PumpLogNotification(
        signature=signature,
        slot=slot,
        observed_at=learned_at,
        events=tuple(events),
    )


def persist_pump_notification(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
) -> int:
    """Persist decoded SOL-paired Pump trades into the market observation store.

    Pump now supports non-SOL quote assets. The stable TradeEvent prefix does not expose quote_mint
    until later in the payload, so this v1 adapter only persists events whose `sol_amount` is
    positive. It deliberately leaves USD notional and price missing rather than inventing them.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
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
                    if notification is not None and notification.events:
                        yield notification
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(reconnect_max_seconds, backoff * 2)
