"""Causal backlog/live classification for Robinhood Nitro feed captures.

The requested sequencer MessageIndex is not inferred from eth_blockNumber. A
capture instead freezes the RPC head before the WebSocket handshake. Feed frames
are clocked immediately and classified later. A feed message is only eligible as
a post-anchor live candidate when its feed block hash resolves to an L2 block
strictly newer than the frozen pre-handshake head.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from src.robinhood_nitro_feed_v0 import NitroFeedMessageV0


BACKLOG_CONFIRMED = "BACKLOG_CONFIRMED_PRECONNECT_HEAD"
LIVE_CANDIDATE = "LIVE_CANDIDATE_POST_ANCHOR"
UNKNOWN_NO_BLOCK_HASH = "UNKNOWN_NO_FEED_BLOCK_HASH"
UNKNOWN_BLOCK_UNRESOLVED = "UNKNOWN_FEED_BLOCK_HASH_UNRESOLVED"


@dataclass(frozen=True)
class RpcHeadAnchorV0:
    block_number: int
    block_hash: str
    block_timestamp_s: int
    captured_at_ns: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeedBootstrapClassificationV0:
    sequence_number: int
    feed_block_hash: str | None
    feed_observed_at_ns: int
    classification: str
    resolved_block_number: int | None
    anchor_block_number: int
    eligible_for_feed_latency: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hex_hash(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a hex string")
    normalized = value.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 66:
        raise ValueError(f"invalid {name}")
    int(normalized[2:], 16)
    return normalized


def _quantity(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} cannot be bool")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(value, 16 if value.lower().startswith("0x") else 10)
    else:
        raise TypeError(f"{name} must be int-compatible")
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def make_rpc_head_anchor_v0(
    block_row: Mapping[str, Any],
    *,
    captured_at_ns: int,
) -> RpcHeadAnchorV0:
    if not isinstance(block_row, Mapping):
        raise TypeError("block_row must be a mapping")
    if captured_at_ns < 0:
        raise ValueError("captured_at_ns must be non-negative")
    return RpcHeadAnchorV0(
        block_number=_quantity(block_row.get("number"), "block number"),
        block_hash=_hex_hash(block_row.get("hash"), "block hash"),
        block_timestamp_s=_quantity(block_row.get("timestamp"), "block timestamp"),
        captured_at_ns=captured_at_ns,
    )


def anchor_is_still_canonical_v0(
    anchor: RpcHeadAnchorV0,
    current_anchor_block_row: Mapping[str, Any] | None,
) -> bool:
    if current_anchor_block_row is None:
        return False
    try:
        number = _quantity(current_anchor_block_row.get("number"), "block number")
        block_hash = _hex_hash(current_anchor_block_row.get("hash"), "block hash")
    except (TypeError, ValueError):
        return False
    return number == anchor.block_number and block_hash == anchor.block_hash


def classify_feed_message_against_anchor_v0(
    message: NitroFeedMessageV0,
    *,
    anchor: RpcHeadAnchorV0,
    resolved_block_row: Mapping[str, Any] | None,
) -> FeedBootstrapClassificationV0:
    """Classify one feed message using post-capture block-hash resolution.

    ``resolved_block_row`` may be fetched after capture. It is only used to map
    the already-observed feed block hash to its canonical block number relative
    to the frozen pre-handshake anchor; it does not alter the receive clock.
    """
    if message.observed_at_ns < anchor.captured_at_ns:
        raise ValueError("feed observation predates the pre-handshake anchor")
    if message.block_hash is None:
        return FeedBootstrapClassificationV0(
            sequence_number=message.sequence_number,
            feed_block_hash=None,
            feed_observed_at_ns=message.observed_at_ns,
            classification=UNKNOWN_NO_BLOCK_HASH,
            resolved_block_number=None,
            anchor_block_number=anchor.block_number,
            eligible_for_feed_latency=False,
        )
    if resolved_block_row is None:
        return FeedBootstrapClassificationV0(
            sequence_number=message.sequence_number,
            feed_block_hash=message.block_hash,
            feed_observed_at_ns=message.observed_at_ns,
            classification=UNKNOWN_BLOCK_UNRESOLVED,
            resolved_block_number=None,
            anchor_block_number=anchor.block_number,
            eligible_for_feed_latency=False,
        )

    resolved_hash = _hex_hash(resolved_block_row.get("hash"), "resolved block hash")
    if resolved_hash != message.block_hash.lower():
        raise ValueError("resolved block hash does not match feed block hash")
    resolved_number = _quantity(resolved_block_row.get("number"), "resolved block number")
    if resolved_number <= anchor.block_number:
        classification = BACKLOG_CONFIRMED
        eligible = False
    else:
        classification = LIVE_CANDIDATE
        eligible = True
    return FeedBootstrapClassificationV0(
        sequence_number=message.sequence_number,
        feed_block_hash=message.block_hash,
        feed_observed_at_ns=message.observed_at_ns,
        classification=classification,
        resolved_block_number=resolved_number,
        anchor_block_number=anchor.block_number,
        eligible_for_feed_latency=eligible,
    )
