from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

from src.multichain_market_contract_v59 import (
    UnifiedLifecycleEventV59,
    UnifiedMarketTradeV59,
    canonical_asset_v59,
    namespaced_event_key_v59,
    validate_lifecycle_v59,
    validate_trade_v59,
)


ROBINHOOD_CHAIN_ID_V62 = 4663
PONS_ADAPTER_VERSION = "robinhood_pons_adapter_v62"
PONS_CURVE_VENUE = "pons_v2_curve"
PONS_SWEPT_VENUE = "pons_v2_swept_not_tradable"
PONS_GRADUATED_VENUE = "uniswap_v4"

_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class PonsLaunchV62:
    token_address: str
    curve_address: str
    deployer_address: str
    pair_token_address: str
    graduation_threshold_raw: int
    pair_token_decimals: int
    chain_time: int
    observed_at: int
    transaction_hash: str
    block_number: int
    event_index: int


@dataclass(frozen=True)
class PonsCurveTradeV62:
    token_address: str
    curve_address: str
    wallet_address: str
    side: str
    token_amount_raw: int
    quote_amount_raw: int
    quote_decimals: int
    chain_time: int
    observed_at: int
    transaction_hash: str
    block_number: int
    event_index: int
    notional_usd: float | None = None
    price_usd: float | None = None


@dataclass(frozen=True)
class PonsLifecycleEventV62:
    token_address: str
    phase: str
    chain_time: int
    observed_at: int
    transaction_hash: str
    block_number: int
    event_index: int


@dataclass(frozen=True)
class PonsStageSnapshotV62:
    method_version: str
    token_address: str
    as_of: int
    stage: str
    launch_known: bool
    sweep_known: bool
    graduation_known: bool
    market_tradable: bool | None
    seconds_since_launch: int | None
    seconds_between_sweep_and_graduation: int | None
    data_quality_flags: tuple[str, ...]


def _address(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not _EVM_ADDRESS_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be a 20-byte EVM address")
    return normalized.lower()


def _tx_hash(value: str) -> str:
    normalized = str(value).strip()
    if not _TX_HASH_RE.fullmatch(normalized):
        raise ValueError("transaction_hash must be a 32-byte hex hash")
    return normalized.lower()


def _clock(chain_time: int, observed_at: int) -> tuple[int, int]:
    chain = int(chain_time)
    observed = int(observed_at)
    if chain < 0 or observed < 0:
        raise ValueError("timestamps must be non-negative")
    if observed < chain:
        raise ValueError("observed_at cannot precede chain_time")
    return chain, observed


def _position(block_number: int, event_index: int) -> tuple[int, int]:
    block = int(block_number)
    index = int(event_index)
    if block < 0 or index < 0:
        raise ValueError("block_number and event_index must be non-negative")
    return block, index


def validate_launch_v62(item: PonsLaunchV62) -> None:
    _address(item.token_address, "token_address")
    _address(item.curve_address, "curve_address")
    _address(item.deployer_address, "deployer_address")
    _address(item.pair_token_address, "pair_token_address")
    if int(item.graduation_threshold_raw) <= 0:
        raise ValueError("graduation_threshold_raw must be positive")
    if not 0 <= int(item.pair_token_decimals) <= 255:
        raise ValueError("pair_token_decimals must be between 0 and 255")
    _clock(item.chain_time, item.observed_at)
    _tx_hash(item.transaction_hash)
    _position(item.block_number, item.event_index)


def validate_curve_trade_v62(item: PonsCurveTradeV62) -> None:
    _address(item.token_address, "token_address")
    _address(item.curve_address, "curve_address")
    _address(item.wallet_address, "wallet_address")
    if item.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if int(item.token_amount_raw) <= 0 or int(item.quote_amount_raw) <= 0:
        raise ValueError("raw trade amounts must be positive")
    if not 0 <= int(item.quote_decimals) <= 255:
        raise ValueError("quote_decimals must be between 0 and 255")
    _clock(item.chain_time, item.observed_at)
    _tx_hash(item.transaction_hash)
    _position(item.block_number, item.event_index)
    if item.notional_usd is not None:
        value = float(item.notional_usd)
        if not math.isfinite(value) or value < 0:
            raise ValueError("notional_usd must be finite and non-negative")
    if item.price_usd is not None:
        value = float(item.price_usd)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("price_usd must be finite and positive")


def validate_lifecycle_event_v62(item: PonsLifecycleEventV62) -> None:
    _address(item.token_address, "token_address")
    if item.phase not in {"launch_swept", "pool_graduated"}:
        raise ValueError("unsupported Pons lifecycle phase")
    _clock(item.chain_time, item.observed_at)
    _tx_hash(item.transaction_hash)
    _position(item.block_number, item.event_index)


def threshold_quote_units_v62(item: PonsLaunchV62) -> float:
    """Normalize the launch-specific threshold; never assume every launch uses 4.2 ETH."""

    validate_launch_v62(item)
    return int(item.graduation_threshold_raw) / float(10 ** int(item.pair_token_decimals))


def _native_event_key(transaction_hash: str, event_index: int, suffix: str) -> str:
    return f"{_tx_hash(transaction_hash)}:{int(event_index)}:{suffix}"


def launch_to_v59(item: PonsLaunchV62, *, source_provider: str) -> UnifiedLifecycleEventV59:
    validate_launch_v62(item)
    asset = canonical_asset_v59(
        namespace="eip155",
        reference=ROBINHOOD_CHAIN_ID_V62,
        address=item.token_address,
    )
    result = UnifiedLifecycleEventV59(
        event_key=namespaced_event_key_v59(
            asset,
            _native_event_key(item.transaction_hash, item.event_index, "token_launched"),
        ),
        source_provider=str(source_provider).strip(),
        asset=asset,
        event_type="market_started",
        chain_time=int(item.chain_time),
        observed_at=int(item.observed_at),
        venue=PONS_CURVE_VENUE,
        transaction_key=_tx_hash(item.transaction_hash),
        block_number=int(item.block_number),
        event_index=int(item.event_index),
    )
    validate_lifecycle_v59(result)
    return result


def curve_trade_to_v59(item: PonsCurveTradeV62, *, source_provider: str) -> UnifiedMarketTradeV59:
    validate_curve_trade_v62(item)
    asset = canonical_asset_v59(
        namespace="eip155",
        reference=ROBINHOOD_CHAIN_ID_V62,
        address=item.token_address,
    )
    result = UnifiedMarketTradeV59(
        event_key=namespaced_event_key_v59(
            asset,
            _native_event_key(item.transaction_hash, item.event_index, f"curve_{item.side}"),
        ),
        source_provider=str(source_provider).strip(),
        asset=asset,
        side=item.side,
        chain_time=int(item.chain_time),
        observed_at=int(item.observed_at),
        wallet_address=_address(item.wallet_address, "wallet_address"),
        notional_usd=item.notional_usd,
        price_usd=item.price_usd,
        venue=PONS_CURVE_VENUE,
        transaction_key=_tx_hash(item.transaction_hash),
        block_number=int(item.block_number),
        event_index=int(item.event_index),
    )
    validate_trade_v59(result)
    return result


def graduation_to_v59(
    item: PonsLifecycleEventV62,
    *,
    source_provider: str,
) -> UnifiedLifecycleEventV59:
    """Expose only completed PoolGraduated events to the generic v59 lifecycle contract.

    The intermediate launch_swept state is deliberately preserved only in the Pons-specific
    timeline because it is a non-tradable gap, not a completed venue transition.
    """

    validate_lifecycle_event_v62(item)
    if item.phase != "pool_graduated":
        raise ValueError("only pool_graduated can map to v59 graduated")
    asset = canonical_asset_v59(
        namespace="eip155",
        reference=ROBINHOOD_CHAIN_ID_V62,
        address=item.token_address,
    )
    result = UnifiedLifecycleEventV59(
        event_key=namespaced_event_key_v59(
            asset,
            _native_event_key(item.transaction_hash, item.event_index, "pool_graduated"),
        ),
        source_provider=str(source_provider).strip(),
        asset=asset,
        event_type="graduated",
        chain_time=int(item.chain_time),
        observed_at=int(item.observed_at),
        venue=PONS_GRADUATED_VENUE,
        prior_venue=PONS_SWEPT_VENUE,
        transaction_key=_tx_hash(item.transaction_hash),
        block_number=int(item.block_number),
        event_index=int(item.event_index),
    )
    validate_lifecycle_v59(result)
    return result


def build_stage_snapshot_v62(
    *,
    launch: PonsLaunchV62,
    lifecycle_events: Iterable[PonsLifecycleEventV62],
    as_of: int,
) -> PonsStageSnapshotV62:
    """Return the stage the collector could actually know by ``as_of``.

    Both market time and knowledge time are enforced. A historical event discovered after the
    requested ``as_of`` cannot retroactively change the stage.
    """

    validate_launch_v62(launch)
    cutoff = int(as_of)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")

    token = _address(launch.token_address, "token_address")
    launch_known = launch.chain_time <= cutoff and launch.observed_at <= cutoff

    eligible: list[PonsLifecycleEventV62] = []
    for event in lifecycle_events:
        validate_lifecycle_event_v62(event)
        if _address(event.token_address, "token_address") != token:
            continue
        if event.chain_time <= cutoff and event.observed_at <= cutoff:
            eligible.append(event)

    sweeps = sorted(
        (event for event in eligible if event.phase == "launch_swept"),
        key=lambda event: (event.chain_time, event.observed_at, event.block_number, event.event_index),
    )
    graduations = sorted(
        (event for event in eligible if event.phase == "pool_graduated"),
        key=lambda event: (event.chain_time, event.observed_at, event.block_number, event.event_index),
    )
    sweep = sweeps[0] if sweeps else None
    graduation = graduations[0] if graduations else None

    flags: list[str] = []
    if not launch_known:
        stage = "UNKNOWN_PRE_LAUNCH_OR_NOT_YET_OBSERVED"
        tradable = None
        seconds_since_launch = None
    else:
        seconds_since_launch = max(0, cutoff - int(launch.chain_time))
        if graduation is not None:
            stage = "GRADUATED_V4"
            tradable = True
            if sweep is None:
                flags.append("graduation_known_without_sweep_observation")
        elif sweep is not None:
            stage = "SWEPT_NOT_TRADABLE"
            tradable = False
        else:
            stage = "CURVE_TRADING"
            tradable = True

    gap = None
    if sweep is not None and graduation is not None:
        if graduation.chain_time < sweep.chain_time:
            flags.append("graduation_precedes_sweep_clock")
        else:
            gap = int(graduation.chain_time) - int(sweep.chain_time)

    return PonsStageSnapshotV62(
        method_version=PONS_ADAPTER_VERSION,
        token_address=token,
        as_of=cutoff,
        stage=stage,
        launch_known=launch_known,
        sweep_known=sweep is not None,
        graduation_known=graduation is not None,
        market_tradable=tradable,
        seconds_since_launch=seconds_since_launch,
        seconds_between_sweep_and_graduation=gap,
        data_quality_flags=tuple(flags),
    )
