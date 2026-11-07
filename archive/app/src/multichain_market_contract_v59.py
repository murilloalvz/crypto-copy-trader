from __future__ import annotations

from dataclasses import dataclass
import math
import re

from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


MULTICHAIN_MARKET_CONTRACT_VERSION = "multichain_market_contract_v59"
SUPPORTED_NAMESPACES = {"solana", "eip155"}
LIFECYCLE_EVENT_TYPES = {"market_started", "pool_created", "graduated", "venue_changed"}
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class ChainNetworkV59:
    namespace: str
    reference: str


@dataclass(frozen=True)
class ChainAssetV59:
    network: ChainNetworkV59
    address: str


@dataclass(frozen=True)
class UnifiedMarketTradeV59:
    event_key: str
    source_provider: str
    asset: ChainAssetV59
    side: str
    chain_time: int
    observed_at: int
    wallet_address: str | None = None
    notional_usd: float | None = None
    price_usd: float | None = None
    venue: str | None = None
    transaction_key: str | None = None
    block_number: int | None = None
    event_index: int | None = None


@dataclass(frozen=True)
class UnifiedLifecycleEventV59:
    event_key: str
    source_provider: str
    asset: ChainAssetV59
    event_type: str
    chain_time: int
    observed_at: int
    venue: str | None = None
    prior_venue: str | None = None
    transaction_key: str | None = None
    block_number: int | None = None
    event_index: int | None = None


def canonical_network_v59(namespace: str, reference: str | int) -> ChainNetworkV59:
    ns = str(namespace).strip().lower()
    ref = str(reference).strip().lower()
    if ns not in SUPPORTED_NAMESPACES:
        raise ValueError("unsupported chain namespace")
    if not ref:
        raise ValueError("chain reference cannot be empty")
    if ns == "eip155":
        try:
            chain_id = int(ref)
        except ValueError as exc:
            raise ValueError("eip155 reference must be a positive integer chain id") from exc
        if chain_id <= 0:
            raise ValueError("eip155 chain id must be positive")
        ref = str(chain_id)
    return ChainNetworkV59(namespace=ns, reference=ref)


def canonical_asset_v59(
    *,
    namespace: str,
    reference: str | int,
    address: str,
) -> ChainAssetV59:
    network = canonical_network_v59(namespace, reference)
    raw = str(address).strip()
    if not raw:
        raise ValueError("asset address cannot be empty")
    if network.namespace == "eip155":
        if not _EVM_ADDRESS_RE.fullmatch(raw):
            raise ValueError("eip155 asset address must be a 20-byte hex address")
        raw = raw.lower()
    return ChainAssetV59(network=network, address=raw)


def namespaced_event_key_v59(asset: ChainAssetV59, native_event_key: str) -> str:
    native = str(native_event_key).strip()
    if not native:
        raise ValueError("native_event_key cannot be empty")
    return (
        f"{asset.network.namespace}:{asset.network.reference}:"
        f"{asset.address}:{native}"
    )


def _optional_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _validate_clock(chain_time: int, observed_at: int) -> None:
    if int(chain_time) < 0 or int(observed_at) < 0:
        raise ValueError("timestamps must be non-negative")
    if int(observed_at) < int(chain_time):
        raise ValueError("observed_at cannot precede chain_time")


def validate_trade_v59(item: UnifiedMarketTradeV59) -> None:
    if not item.event_key.strip() or not item.source_provider.strip():
        raise ValueError("event_key and source_provider are required")
    if item.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    canonical_asset_v59(
        namespace=item.asset.network.namespace,
        reference=item.asset.network.reference,
        address=item.asset.address,
    )
    _validate_clock(item.chain_time, item.observed_at)
    _optional_text(item.wallet_address, "wallet_address")
    _optional_text(item.venue, "venue")
    _optional_text(item.transaction_key, "transaction_key")
    if item.notional_usd is not None:
        value = float(item.notional_usd)
        if not math.isfinite(value) or value < 0:
            raise ValueError("notional_usd must be finite and non-negative")
    if item.price_usd is not None:
        value = float(item.price_usd)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("price_usd must be finite and positive")
    if item.block_number is not None and int(item.block_number) < 0:
        raise ValueError("block_number must be non-negative")
    if item.event_index is not None and int(item.event_index) < 0:
        raise ValueError("event_index must be non-negative")


def validate_lifecycle_v59(item: UnifiedLifecycleEventV59) -> None:
    if not item.event_key.strip() or not item.source_provider.strip():
        raise ValueError("event_key and source_provider are required")
    if item.event_type not in LIFECYCLE_EVENT_TYPES:
        raise ValueError("unsupported lifecycle event type")
    canonical_asset_v59(
        namespace=item.asset.network.namespace,
        reference=item.asset.network.reference,
        address=item.asset.address,
    )
    _validate_clock(item.chain_time, item.observed_at)
    _optional_text(item.venue, "venue")
    _optional_text(item.prior_venue, "prior_venue")
    _optional_text(item.transaction_key, "transaction_key")
    if item.block_number is not None and int(item.block_number) < 0:
        raise ValueError("block_number must be non-negative")
    if item.event_index is not None and int(item.event_index) < 0:
        raise ValueError("event_index must be non-negative")


def solana_trade_to_v59(
    *,
    native_event_key: str,
    source_provider: str,
    observation: MarketTradeObservation,
) -> UnifiedMarketTradeV59:
    """Wrap the existing Solana detector input without changing its semantics."""

    asset = canonical_asset_v59(
        namespace="solana",
        reference="mainnet",
        address=observation.token_mint,
    )
    item = UnifiedMarketTradeV59(
        event_key=namespaced_event_key_v59(asset, native_event_key),
        source_provider=str(source_provider),
        asset=asset,
        side=observation.side,
        chain_time=observation.chain_time,
        observed_at=observation.observed_at,
        wallet_address=observation.wallet_address,
        notional_usd=observation.notional_usd,
        price_usd=observation.price_usd,
        venue=observation.venue,
        transaction_key=observation.transaction_key,
    )
    validate_trade_v59(item)
    return item


def solana_lifecycle_to_v59(
    *,
    native_event_key: str,
    source_provider: str,
    observation: MarketLifecycleObservation,
) -> UnifiedLifecycleEventV59:
    """Wrap existing Solana market-start evidence as a v59 lifecycle event."""

    asset = canonical_asset_v59(
        namespace="solana",
        reference="mainnet",
        address=observation.token_mint,
    )
    item = UnifiedLifecycleEventV59(
        event_key=namespaced_event_key_v59(asset, native_event_key),
        source_provider=str(source_provider),
        asset=asset,
        event_type="market_started",
        chain_time=observation.market_started_at,
        observed_at=observation.observed_at,
        venue=observation.venue,
    )
    validate_lifecycle_v59(item)
    return item
