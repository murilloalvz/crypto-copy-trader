from __future__ import annotations

from dataclasses import asdict, dataclass

from src.carbon_market_trade_adapter import CARBON_MARKET_TRADE_ADAPTER_VERSION
from src.carbon_matched_unit_adapter import CARBON_MATCHED_UNIT_ADAPTER_VERSION
from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.matched_unit_flow import MATCHED_UNIT_FLOW_VERSION


LAUNCH_BURST_SOURCE_CAPABILITIES_VERSION = "launch_burst_source_capabilities_v0"


@dataclass(frozen=True)
class SourceCapabilityV0:
    field_family: str
    causal_source: str
    current_status: str
    durable_in_market_observation_store: bool
    usable_for_launch_burst_v0: bool
    notes: str


@dataclass(frozen=True)
class LaunchBurstSourceCapabilitiesV0:
    method_version: str
    market_trade_adapter_version: str
    matched_unit_adapter_version: str
    matched_unit_flow_version: str
    capabilities: tuple[SourceCapabilityV0, ...]
    feature_only_ready: bool
    economic_outcome_ready: bool
    executable_quote_selection_contract_present: bool
    executable_quote_collector_proven: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def build_launch_burst_source_capabilities_v0() -> LaunchBurstSourceCapabilitiesV0:
    """Declare what the current live ingestion contract can and cannot support.

    This is intentionally conservative and machine-readable. It describes the current
    canonical adapters/store, not theoretical information that could be reconstructed by
    a future enrichment job. In particular, the presence of a quote selection primitive
    does not prove an executable quote collector exists.
    """

    capabilities = (
        SourceCapabilityV0(
            field_family="lifecycle_anchor",
            causal_source="pump_create / pumpswap_create_pool canonical events",
            current_status="AVAILABLE",
            durable_in_market_observation_store=True,
            usable_for_launch_burst_v0=True,
            notes="market_started_at, observed_at, token and canonical venue are persisted",
        ),
        SourceCapabilityV0(
            field_family="trade_event_count_and_side",
            causal_source="Carbon matched-unit -> market-trade adapter",
            current_status="AVAILABLE",
            durable_in_market_observation_store=True,
            usable_for_launch_burst_v0=True,
            notes="buy/sell and independent chain/local clocks are persisted",
        ),
        SourceCapabilityV0(
            field_family="wallet_identity",
            causal_source="Pump wallet / PumpSwap user event fields",
            current_status="CONDITIONAL_EVENT_FIELD",
            durable_in_market_observation_store=True,
            usable_for_launch_burst_v0=True,
            notes="missing identity remains explicit and is measured as coverage",
        ),
        SourceCapabilityV0(
            field_family="transaction_identity",
            causal_source="canonical transaction signature",
            current_status="CONDITIONAL_EVENT_FIELD",
            durable_in_market_observation_store=True,
            usable_for_launch_burst_v0=True,
            notes="missing signature remains explicit and is measured as coverage",
        ),
        SourceCapabilityV0(
            field_family="usd_notional",
            causal_source="none in current Carbon market-trade adapter",
            current_status="NOT_INFERRED",
            durable_in_market_observation_store=False,
            usable_for_launch_burst_v0=False,
            notes="market adapter deliberately writes notional_usd=None",
        ),
        SourceCapabilityV0(
            field_family="usd_price",
            causal_source="none in current Carbon market-trade adapter",
            current_status="NOT_INFERRED",
            durable_in_market_observation_store=False,
            usable_for_launch_burst_v0=False,
            notes="market adapter deliberately writes price_usd=None",
        ),
        SourceCapabilityV0(
            field_family="native_quote_amount_and_reserve",
            causal_source="matched-unit Carbon adapter",
            current_status="AVAILABLE_IN_MEMORY_AND_RAW_REPLAY",
            durable_in_market_observation_store=False,
            usable_for_launch_burst_v0=False,
            notes=(
                "quote_amount_raw, quote_reserve_raw, quote_asset_key and market surface are "
                "causally produced before market-trade adaptation but are not persisted by "
                "the live Market-First pipeline"
            ),
        ),
        SourceCapabilityV0(
            field_family="dimensionless_flow_over_reserve",
            causal_source="matched_unit_flow_v1_clock_domains",
            current_status="COMPUTABLE_FROM_MATCHED_UNIT_EVIDENCE",
            durable_in_market_observation_store=False,
            usable_for_launch_burst_v0=False,
            notes=(
                "same-unit flow/reserve features exist without USD conversion, but Launch Burst "
                "must replay or persist matched-unit evidence before using them"
            ),
        ),
        SourceCapabilityV0(
            field_family="executable_quote_outcome",
            causal_source="causal_quotes selection contract",
            current_status="SELECTION_CONTRACT_ONLY",
            durable_in_market_observation_store=False,
            usable_for_launch_burst_v0=False,
            notes=(
                "direction/freshness/executability validation exists, but this capability report "
                "does not recognize any proven official collector"
            ),
        ),
    )

    # Import references above deliberately pin this report to the live contracts. The quote
    # symbols are also referenced so static tooling cannot mistake the selection primitive
    # for an unused/unverified concept.
    selection_contract_present = (
        CausalQuoteObservation is not None and select_first_causal_quote is not None
    )
    blockers = (
        "usd_price_and_notional_not_inferred_by_current_market_trade_adapter",
        "matched_unit_quote_amount_and_reserve_not_persisted_to_market_observation_store",
        "official_executable_launch_burst_outcome_collector_not_proven",
        "launch_burst_outcome_protocol_remains_unfrozen",
    )
    return LaunchBurstSourceCapabilitiesV0(
        method_version=LAUNCH_BURST_SOURCE_CAPABILITIES_VERSION,
        market_trade_adapter_version=CARBON_MARKET_TRADE_ADAPTER_VERSION,
        matched_unit_adapter_version=CARBON_MATCHED_UNIT_ADAPTER_VERSION,
        matched_unit_flow_version=MATCHED_UNIT_FLOW_VERSION,
        capabilities=capabilities,
        feature_only_ready=True,
        economic_outcome_ready=False,
        executable_quote_selection_contract_present=selection_contract_present,
        executable_quote_collector_proven=False,
        blockers=blockers,
    )
