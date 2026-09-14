"""Robinhood/Nitro sequencer-feed V0 parser.

This is an INTENT-ONLY parser. Nitro's sequencer feed carries L2 messages before
execution; it does not prove EVM success, emitted logs, final reserves, or fills.
Executed Pons evidence remains sourced from RPC receipts/logs and is reconciled
later through a separate shadow-parity step.

The implementation mirrors the currently published Nitro V1 feed JSON envelope
and the subset of ``parseL2Message`` required for ordinary signed Ethereum
transactions and nested L2 batches. It intentionally does not guess semantics
for unsupported L2 message kinds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
import json
from typing import Any, Iterable, Mapping


FEED_VERSION = 1
L1_MESSAGE_TYPE_L2_MESSAGE = 3
L2_MESSAGE_KIND_BATCH = 3
L2_MESSAGE_KIND_SIGNED_TX = 4
MAX_L2_MESSAGE_SIZE = 256 * 1024
MAX_BATCH_DEPTH = 16

INTENT_ONLY = "INTENT_ONLY_NOT_EXECUTION_PROOF"


def _nonnegative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _hex_address(value: str | None, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a hex address string")
    normalized = value.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValueError(f"invalid {name}: {value!r}")
    int(normalized[2:], 16)
    return normalized


def _hex_hash(value: Any, name: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a hex string")
    normalized = value.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 66:
        raise ValueError(f"invalid {name}: {value!r}")
    int(normalized[2:], 16)
    return normalized


def _base64_bytes(value: Any, name: str, *, allow_none: bool = False) -> bytes:
    if value is None and allow_none:
        return b""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError(f"invalid base64 for {name}") from exc


def _bigint_json(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} cannot be bool")
    if isinstance(value, int):
        return _nonnegative_int(value, name)
    if isinstance(value, str):
        text = value.strip().lower()
        base = 16 if text.startswith("0x") else 10
        parsed = int(text, base)
        return _nonnegative_int(parsed, name)
    raise TypeError(f"{name} must be integer-compatible")


@dataclass(frozen=True)
class NitroFeedMessageV0:
    sequence_number: int
    block_hash: str | None
    l1_kind: int
    sender: str
    l1_block_number: int
    l1_timestamp: int
    request_id: str | None
    l1_base_fee_raw: int | None
    delayed_messages_read: int
    l2_message_raw: bytes
    signature_raw: bytes
    block_metadata_raw: bytes
    observed_at_ns: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["l2_message_raw"] = "0x" + self.l2_message_raw.hex()
        payload["signature_raw"] = "0x" + self.signature_raw.hex()
        payload["block_metadata_raw"] = "0x" + self.block_metadata_raw.hex()
        return payload


@dataclass(frozen=True)
class NitroSignedTxIntentV0:
    sequence_number: int
    batch_path: tuple[int, ...]
    tx_envelope_type: str
    tx_type_byte: int | None
    to: str | None
    value_raw: int
    calldata_raw: bytes
    calldata_selector: str | None
    raw_tx: bytes
    raw_tx_sha256: str
    l1_timestamp: int
    feed_block_hash: str | None
    observed_at_ns: int
    evidence_scope: str = INTENT_ONLY
    execution_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["batch_path"] = list(self.batch_path)
        payload["calldata_raw"] = "0x" + self.calldata_raw.hex()
        payload["raw_tx"] = "0x" + self.raw_tx.hex()
        return payload


@dataclass(frozen=True)
class PonsFeedIntentV0:
    sequence_number: int
    batch_path: tuple[int, ...]
    target: str
    intent_kind: str
    calldata_selector: str | None
    value_raw: int
    raw_tx_sha256: str
    observed_at_ns: int
    evidence_scope: str = INTENT_ONLY
    execution_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["batch_path"] = list(self.batch_path)
        return payload


def parse_broadcast_message_v0(raw: str | bytes, *, observed_at_ns: int) -> tuple[NitroFeedMessageV0, ...]:
    """Parse one Nitro ``BroadcastMessage`` JSON payload.

    Unknown top-level fields are ignored, matching Nitro's forward-compatible
    JSON behavior. V0 only accepts feed version 1 for message extraction.
    Confirmed-sequence-number-only frames yield an empty tuple.
    """
    _nonnegative_int(observed_at_ns, "observed_at_ns")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        raise TypeError("raw feed message must be str or bytes")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("broadcast payload must be a JSON object")
    version = payload.get("version")
    if version != FEED_VERSION:
        raise ValueError(f"unsupported Nitro feed version: {version!r}")
    messages = payload.get("messages")
    if messages is None:
        return ()
    if not isinstance(messages, list):
        raise ValueError("broadcast messages must be a list")

    output: list[NitroFeedMessageV0] = []
    for index, item in enumerate(messages):
        if not isinstance(item, dict):
            raise ValueError(f"messages[{index}] must be an object")
        sequence = _nonnegative_int(item.get("sequenceNumber"), f"messages[{index}].sequenceNumber")
        metadata = item.get("message")
        if not isinstance(metadata, dict):
            raise ValueError(f"messages[{index}].message must be an object")
        incoming = metadata.get("message")
        if not isinstance(incoming, dict):
            raise ValueError(f"messages[{index}].message.message must be an object")
        header = incoming.get("header")
        if not isinstance(header, dict):
            raise ValueError(f"messages[{index}] header must be an object")
        sender = _hex_address(header.get("sender"), "sender")
        assert sender is not None
        output.append(
            NitroFeedMessageV0(
                sequence_number=sequence,
                block_hash=_hex_hash(item.get("blockHash"), "blockHash", allow_none=True),
                l1_kind=_nonnegative_int(header.get("kind"), "kind"),
                sender=sender,
                l1_block_number=_nonnegative_int(header.get("blockNumber"), "blockNumber"),
                l1_timestamp=_nonnegative_int(header.get("timestamp"), "timestamp"),
                request_id=_hex_hash(header.get("requestId"), "requestId", allow_none=True),
                l1_base_fee_raw=_bigint_json(header.get("baseFeeL1"), "baseFeeL1"),
                delayed_messages_read=_nonnegative_int(
                    metadata.get("delayedMessagesRead"), "delayedMessagesRead"
                ),
                l2_message_raw=_base64_bytes(incoming.get("l2Msg"), "l2Msg"),
                signature_raw=_base64_bytes(item.get("signatureV2"), "signatureV2", allow_none=True),
                block_metadata_raw=_base64_bytes(
                    item.get("blockMetadata"), "blockMetadata", allow_none=True
                ),
                observed_at_ns=observed_at_ns,
            )
        )
    return tuple(output)


class RlpDecodeError(ValueError):
    pass


def _be_length(data: bytes, start: int, count: int) -> int:
    end = start + count
    if count <= 0 or end > len(data):
        raise RlpDecodeError("invalid RLP length-of-length")
    if data[start] == 0:
        raise RlpDecodeError("non-canonical RLP length")
    return int.from_bytes(data[start:end], "big")


def _rlp_one(data: bytes, offset: int = 0):
    if offset >= len(data):
        raise RlpDecodeError("unexpected end of RLP")
    prefix = data[offset]
    if prefix <= 0x7F:
        return bytes([prefix]), offset + 1
    if prefix <= 0xB7:
        size = prefix - 0x80
        start = offset + 1
        end = start + size
        if end > len(data):
            raise RlpDecodeError("short RLP string")
        if size == 1 and data[start] <= 0x7F:
            raise RlpDecodeError("non-canonical short RLP string")
        return data[start:end], end
    if prefix <= 0xBF:
        count = prefix - 0xB7
        size = _be_length(data, offset + 1, count)
        if size < 56:
            raise RlpDecodeError("non-canonical long RLP string")
        start = offset + 1 + count
        end = start + size
        if end > len(data):
            raise RlpDecodeError("short long RLP string")
        return data[start:end], end
    if prefix <= 0xF7:
        size = prefix - 0xC0
        start = offset + 1
        end = start + size
        if end > len(data):
            raise RlpDecodeError("short RLP list")
        items = []
        cursor = start
        while cursor < end:
            item, cursor = _rlp_one(data, cursor)
            items.append(item)
        if cursor != end:
            raise RlpDecodeError("RLP list boundary mismatch")
        return items, end

    count = prefix - 0xF7
    size = _be_length(data, offset + 1, count)
    if size < 56:
        raise RlpDecodeError("non-canonical long RLP list")
    start = offset + 1 + count
    end = start + size
    if end > len(data):
        raise RlpDecodeError("short long RLP list")
    items = []
    cursor = start
    while cursor < end:
        item, cursor = _rlp_one(data, cursor)
        items.append(item)
    if cursor != end:
        raise RlpDecodeError("long RLP list boundary mismatch")
    return items, end


def _rlp_top_list(data: bytes) -> list[Any]:
    value, end = _rlp_one(data, 0)
    if end != len(data):
        raise RlpDecodeError("trailing bytes after RLP payload")
    if not isinstance(value, list):
        raise RlpDecodeError("transaction RLP must be a list")
    return value


def _bytes_field(fields: list[Any], index: int, name: str) -> bytes:
    if index >= len(fields) or not isinstance(fields[index], bytes):
        raise RlpDecodeError(f"{name} is not an RLP byte string")
    return fields[index]


def _decode_signed_transaction(raw_tx: bytes) -> tuple[str, int | None, str | None, int, bytes]:
    if not raw_tx:
        raise ValueError("empty signed transaction")
    first = raw_tx[0]
    if first >= 0xC0:
        tx_type = None
        envelope = "legacy"
        fields = _rlp_top_list(raw_tx)
        to_index, value_index, data_index = 3, 4, 5
        if len(fields) < 9:
            raise RlpDecodeError("legacy signed transaction has too few fields")
    elif first == 1:
        tx_type = 1
        envelope = "eip2930"
        fields = _rlp_top_list(raw_tx[1:])
        to_index, value_index, data_index = 4, 5, 6
        if len(fields) < 11:
            raise RlpDecodeError("EIP-2930 signed transaction has too few fields")
    elif first == 2:
        tx_type = 2
        envelope = "eip1559"
        fields = _rlp_top_list(raw_tx[1:])
        to_index, value_index, data_index = 5, 6, 7
        if len(fields) < 12:
            raise RlpDecodeError("EIP-1559 signed transaction has too few fields")
    else:
        raise ValueError(f"unsupported signed Ethereum transaction type byte: {first}")

    to_raw = _bytes_field(fields, to_index, "to")
    if len(to_raw) == 0:
        to = None
    elif len(to_raw) == 20:
        to = "0x" + to_raw.hex()
    else:
        raise RlpDecodeError("transaction to field must be empty or 20 bytes")
    value_raw = int.from_bytes(_bytes_field(fields, value_index, "value"), "big")
    calldata = _bytes_field(fields, data_index, "data")
    return envelope, tx_type, to, value_raw, calldata


def extract_signed_tx_intents_v0(message: NitroFeedMessageV0) -> tuple[NitroSignedTxIntentV0, ...]:
    """Extract ordinary signed Ethereum transaction intents from one feed message.

    Only L1 kind 3 (L2 message), nested L2 batch kind 3, and signed transaction
    kind 4 are interpreted. Other kinds are ignored rather than guessed.
    """
    if message.l1_kind != L1_MESSAGE_TYPE_L2_MESSAGE:
        return ()
    if len(message.l2_message_raw) > MAX_L2_MESSAGE_SIZE:
        raise ValueError("L2 message exceeds Nitro maximum")

    output: list[NitroSignedTxIntentV0] = []

    def visit(raw: bytes, path: tuple[int, ...], depth: int) -> None:
        if depth > MAX_BATCH_DEPTH:
            raise ValueError("Nitro L2 batch exceeds maximum depth")
        if not raw:
            raise ValueError("empty L2 message")
        kind = raw[0]
        body = raw[1:]
        if kind == L2_MESSAGE_KIND_SIGNED_TX:
            envelope, tx_type, to, value_raw, calldata = _decode_signed_transaction(body)
            output.append(
                NitroSignedTxIntentV0(
                    sequence_number=message.sequence_number,
                    batch_path=path,
                    tx_envelope_type=envelope,
                    tx_type_byte=tx_type,
                    to=to,
                    value_raw=value_raw,
                    calldata_raw=calldata,
                    calldata_selector=("0x" + calldata[:4].hex()) if len(calldata) >= 4 else None,
                    raw_tx=body,
                    raw_tx_sha256=hashlib.sha256(body).hexdigest(),
                    l1_timestamp=message.l1_timestamp,
                    feed_block_hash=message.block_hash,
                    observed_at_ns=message.observed_at_ns,
                )
            )
            return
        if kind == L2_MESSAGE_KIND_BATCH:
            cursor = 0
            child_index = 0
            while cursor < len(body):
                if len(body) - cursor < 8:
                    raise ValueError("truncated Nitro batch length prefix")
                size = int.from_bytes(body[cursor : cursor + 8], "big")
                cursor += 8
                if size > MAX_L2_MESSAGE_SIZE:
                    raise ValueError("nested Nitro L2 message exceeds maximum")
                end = cursor + size
                if end > len(body):
                    raise ValueError("truncated Nitro nested L2 message")
                visit(body[cursor:end], path + (child_index,), depth + 1)
                child_index += 1
                cursor = end
            return
        # All other L2 kinds are deliberately outside V0.

    visit(message.l2_message_raw, (), 0)
    return tuple(output)


def classify_pons_intent_v0(
    intent: NitroSignedTxIntentV0,
    *,
    factory_address: str,
    known_curve_addresses: Iterable[str] = (),
    buy_selector: str | None = None,
    sell_selector: str | None = None,
) -> PonsFeedIntentV0 | None:
    """Classify a transaction target without claiming EVM execution.

    A transaction to the active factory is retained as a generic factory-target
    intent because launchToken is overloaded and deployment generations can move.
    Known curve targets may be labelled BUY/SELL by selectors obtained from a
    causal/deployed ABI surface (for example via ``web3_sha3`` preflight).
    """
    if intent.to is None:
        return None
    factory = _hex_address(factory_address, "factory_address")
    assert factory is not None
    curves = {
        address
        for value in known_curve_addresses
        if (address := _hex_address(value, "known_curve_address")) is not None
    }
    selector = intent.calldata_selector.lower() if intent.calldata_selector else None
    if intent.to == factory:
        kind = "PONS_FACTORY_TARGET_INTENT"
    elif intent.to in curves:
        if buy_selector is not None and selector == buy_selector.lower():
            kind = "PONS_CURVE_BUY_INTENT"
        elif sell_selector is not None and selector == sell_selector.lower():
            kind = "PONS_CURVE_SELL_INTENT"
        else:
            kind = "PONS_CURVE_OTHER_INTENT"
    else:
        return None
    return PonsFeedIntentV0(
        sequence_number=intent.sequence_number,
        batch_path=intent.batch_path,
        target=intent.to,
        intent_kind=kind,
        calldata_selector=selector,
        value_raw=intent.value_raw,
        raw_tx_sha256=intent.raw_tx_sha256,
        observed_at_ns=intent.observed_at_ns,
    )


def parse_feed_intents_v0(raw: str | bytes, *, observed_at_ns: int) -> dict[str, Any]:
    messages = parse_broadcast_message_v0(raw, observed_at_ns=observed_at_ns)
    intents = []
    ignored_non_l2 = 0
    for message in messages:
        if message.l1_kind != L1_MESSAGE_TYPE_L2_MESSAGE:
            ignored_non_l2 += 1
            continue
        intents.extend(extract_signed_tx_intents_v0(message))
    return {
        "method_version": "robinhood_nitro_feed_intent_parser_v0",
        "feed_version": FEED_VERSION,
        "message_count": len(messages),
        "signed_tx_intent_count": len(intents),
        "ignored_non_l2_message_count": ignored_non_l2,
        "messages": [message.to_dict() for message in messages],
        "intents": [intent.to_dict() for intent in intents],
        "evidence_scope": INTENT_ONLY,
        "execution_confirmed": False,
        "economic_outcomes_opened": False,
    }
