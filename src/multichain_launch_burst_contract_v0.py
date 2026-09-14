"""Lossless scientific envelope for independent multichain launch-burst research."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

CONTRACT_VERSION = "multichain_launch_burst_contract_v0"
RAW_QUOTE_UNIT = "raw_quote_asset_units"
UNKNOWN_QUOTE_UNIT = "unknown_quote_units"
ROBINHOOD_NATIVE_ETH = "0x0000000000000000000000000000000000000000"


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value.strip()


def _nonnegative(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _copy_json(encoded: str) -> Any:
    return json.loads(encoded)


@dataclass(frozen=True)
class QuoteUnitV0:
    unit_kind: str
    asset_id: str | None = None
    semantic_asset_id: str | None = None
    decimals: int | None = None

    def __post_init__(self) -> None:
        _nonempty(self.unit_kind, "unit_kind")
        if self.asset_id is not None:
            _nonempty(self.asset_id, "asset_id")
        if self.semantic_asset_id is not None:
            _nonempty(self.semantic_asset_id, "semantic_asset_id")
        if self.decimals is not None and (
            not isinstance(self.decimals, int)
            or isinstance(self.decimals, bool)
            or not 0 <= self.decimals <= 36
        ):
            raise ValueError("decimals must be an integer in [0, 36] when present")

    @property
    def is_raw_comparison_ready(self) -> bool:
        return (
            self.unit_kind == RAW_QUOTE_UNIT
            and self.semantic_asset_id is not None
            and self.decimals is not None
        )


@dataclass(frozen=True)
class LaunchBurstEnvelopeV0:
    contract_version: str
    chain_namespace: str
    chain_id: str | None
    protocol_namespace: str
    stratum: str
    launch_id: str
    token_id: str
    anchor_observed_at_ns: int
    cutoff_observed_at_ns: int
    snapshot_observed_at_ns: int
    horizon_seconds: int
    quote_unit: QuoteUnitV0
    feature_namespace: str
    features_json: str
    protocol_extension_json: str
    provenance: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    feature_only: bool
    economic_outcomes_opened: bool
    selector_frozen: bool

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("unexpected multichain contract version")
        for name in (
            "chain_namespace", "protocol_namespace", "stratum",
            "launch_id", "token_id", "feature_namespace",
        ):
            _nonempty(getattr(self, name), name)
        if self.chain_id is not None:
            _nonempty(self.chain_id, "chain_id")
        for name in (
            "anchor_observed_at_ns", "cutoff_observed_at_ns",
            "snapshot_observed_at_ns", "horizon_seconds",
        ):
            _nonnegative(getattr(self, name), name)
        if self.horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be positive")
        if self.cutoff_observed_at_ns != (
            self.anchor_observed_at_ns + self.horizon_seconds * 1_000_000_000
        ):
            raise ValueError("cutoff must equal anchor + horizon on the local causal clock")
        if self.snapshot_observed_at_ns < self.cutoff_observed_at_ns:
            raise ValueError("snapshot cannot freeze before its causal cutoff")
        if self.economic_outcomes_opened and self.feature_only:
            raise ValueError("feature_only cannot be true after economic outcomes are opened")
        if not isinstance(_copy_json(self.features_json), dict):
            raise ValueError("features_json must encode an object")
        if not isinstance(_copy_json(self.protocol_extension_json), dict):
            raise ValueError("protocol_extension_json must encode an object")
        for item in self.provenance:
            _nonempty(item, "provenance item")
        for item in self.data_quality_flags:
            _nonempty(item, "data_quality_flag")

    @property
    def features(self) -> dict[str, Any]:
        return _copy_json(self.features_json)

    @property
    def protocol_extension(self) -> dict[str, Any]:
        return _copy_json(self.protocol_extension_json)

    def source_snapshot(self) -> dict[str, Any]:
        value = self.protocol_extension.get("source_snapshot")
        if not isinstance(value, dict):
            raise ValueError("lossless source snapshot is missing")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "chain_namespace": self.chain_namespace,
            "chain_id": self.chain_id,
            "protocol_namespace": self.protocol_namespace,
            "stratum": self.stratum,
            "launch_id": self.launch_id,
            "token_id": self.token_id,
            "anchor_observed_at_ns": self.anchor_observed_at_ns,
            "cutoff_observed_at_ns": self.cutoff_observed_at_ns,
            "snapshot_observed_at_ns": self.snapshot_observed_at_ns,
            "horizon_seconds": self.horizon_seconds,
            "quote_unit": {
                "unit_kind": self.quote_unit.unit_kind,
                "asset_id": self.quote_unit.asset_id,
                "semantic_asset_id": self.quote_unit.semantic_asset_id,
                "decimals": self.quote_unit.decimals,
            },
            "feature_namespace": self.feature_namespace,
            "features": self.features,
            "protocol_extension": self.protocol_extension,
            "provenance": list(self.provenance),
            "data_quality_flags": list(self.data_quality_flags),
            "feature_only": self.feature_only,
            "economic_outcomes_opened": self.economic_outcomes_opened,
            "selector_frozen": self.selector_frozen,
        }


def _envelope(
    *, chain_namespace: str, chain_id: str | None, protocol_namespace: str,
    stratum: str, launch_id: str, token_id: str, anchor_ns: int,
    cutoff_ns: int, snapshot_ns: int, horizon_seconds: int,
    quote_unit: QuoteUnitV0, feature_namespace: str,
    features: Mapping[str, Any], source_snapshot: Mapping[str, Any],
    adapter_inputs: Mapping[str, Any], provenance: tuple[str, ...],
    data_quality_flags: tuple[str, ...], feature_only: bool,
    economic_outcomes_opened: bool, selector_frozen: bool,
) -> LaunchBurstEnvelopeV0:
    return LaunchBurstEnvelopeV0(
        contract_version=CONTRACT_VERSION,
        chain_namespace=chain_namespace,
        chain_id=chain_id,
        protocol_namespace=protocol_namespace,
        stratum=stratum,
        launch_id=launch_id,
        token_id=token_id,
        anchor_observed_at_ns=anchor_ns,
        cutoff_observed_at_ns=cutoff_ns,
        snapshot_observed_at_ns=snapshot_ns,
        horizon_seconds=horizon_seconds,
        quote_unit=quote_unit,
        feature_namespace=feature_namespace,
        features_json=_canonical_json(dict(features)),
        protocol_extension_json=_canonical_json({
            "source_snapshot": dict(source_snapshot),
            "adapter_inputs": dict(adapter_inputs),
        }),
        provenance=tuple(provenance),
        data_quality_flags=tuple(data_quality_flags),
        feature_only=bool(feature_only),
        economic_outcomes_opened=bool(economic_outcomes_opened),
        selector_frozen=bool(selector_frozen),
    )


def adapt_solana_pump_snapshot_v0(
    *, token_mint: str, snapshot: Mapping[str, Any],
    snapshot_observed_at_ns: int | None = None,
    quote_asset_id: str | None = None,
    quote_asset_decimals: int | None = None,
    quote_semantic_asset_id: str | None = None,
    provenance: tuple[str, ...] = (),
    feature_only: bool = True,
    economic_outcomes_opened: bool = False,
    selector_frozen: bool = False,
) -> LaunchBurstEnvelopeV0:
    """Wrap a frozen Solana/Pump snapshot without inventing missing quote metadata."""
    source = dict(snapshot)
    features = source.get("features")
    if not isinstance(features, Mapping):
        raise ValueError("Solana snapshot must contain a features object")
    anchor_ns = int(source["observed_t0_wall_ns"])
    cutoff_ns = int(source["decision_cutoff_wall_ns"])
    horizon = int(source["evidence_window_seconds"])
    frozen_ns = cutoff_ns if snapshot_observed_at_ns is None else int(snapshot_observed_at_ns)
    quote_unit = QuoteUnitV0(
        unit_kind=(
            RAW_QUOTE_UNIT
            if features.get("raw_quote_amount_aggregation_valid") is True
            else UNKNOWN_QUOTE_UNIT
        ),
        asset_id=quote_asset_id,
        semantic_asset_id=quote_semantic_asset_id,
        decimals=quote_asset_decimals,
    )
    flags: set[str] = set()
    if source.get("complete") is not True:
        flags.add("source_snapshot_incomplete")
    if features.get("raw_quote_amount_aggregation_valid") is not True:
        flags.add("raw_quote_aggregation_invalid")
    if quote_asset_id is None:
        flags.add("quote_asset_identity_missing")
    if quote_asset_decimals is None:
        flags.add("quote_decimals_missing")
    return _envelope(
        chain_namespace="solana-mainnet-beta",
        chain_id=None,
        protocol_namespace="pump",
        stratum=str(source.get("stratum") or "pump_launch"),
        launch_id=token_mint,
        token_id=token_mint,
        anchor_ns=anchor_ns,
        cutoff_ns=cutoff_ns,
        snapshot_ns=frozen_ns,
        horizon_seconds=horizon,
        quote_unit=quote_unit,
        feature_namespace="solana.pump.launch_burst_shadow_v0",
        features=features,
        source_snapshot=source,
        adapter_inputs={
            "token_mint": token_mint,
            "quote_asset_id": quote_asset_id,
            "quote_asset_decimals": quote_asset_decimals,
            "quote_semantic_asset_id": quote_semantic_asset_id,
            "snapshot_observed_at_ns": frozen_ns,
        },
        provenance=provenance,
        data_quality_flags=tuple(sorted(flags)),
        feature_only=feature_only,
        economic_outcomes_opened=economic_outcomes_opened,
        selector_frozen=selector_frozen,
    )


def adapt_robinhood_pons_snapshot_v0(
    *, snapshot: Mapping[str, Any],
    quote_asset_decimals: int | None = None,
    quote_semantic_asset_id: str | None = None,
    provenance: tuple[str, ...] = (),
    feature_only: bool = True,
    economic_outcomes_opened: bool = False,
    selector_frozen: bool = False,
) -> LaunchBurstEnvelopeV0:
    """Wrap one Pons V2 burst snapshot losslessly."""
    source = dict(snapshot)
    required = (
        "token", "curve", "pair_token", "launch_observed_at_ns",
        "cutoff_observed_at_ns", "snapshot_observed_at_ns", "horizon_seconds",
    )
    missing = [name for name in required if name not in source]
    if missing:
        raise ValueError(f"Robinhood snapshot missing fields: {missing}")
    metadata = {
        "method_version", "token", "curve", "deployer", "pair_token",
        "native_eth_cohort", "graduation_threshold_raw", "horizon_seconds",
        "launch_observed_at_ns", "cutoff_observed_at_ns",
        "snapshot_observed_at_ns", "snapshot_dispatch_lag_ms",
        "first_chain_order", "last_chain_order", "data_quality_flags",
    }
    features = {key: value for key, value in source.items() if key not in metadata}
    pair_token = str(source["pair_token"]).lower()
    native = pair_token == ROBINHOOD_NATIVE_ETH
    decimals = 18 if native and quote_asset_decimals is None else quote_asset_decimals
    semantic = "ETH" if native and quote_semantic_asset_id is None else quote_semantic_asset_id
    quote_unit = QuoteUnitV0(
        unit_kind=RAW_QUOTE_UNIT,
        asset_id="robinhood:native-eth" if native else pair_token,
        semantic_asset_id=semantic,
        decimals=decimals,
    )
    flags = {str(item) for item in (source.get("data_quality_flags") or ())}
    if not native:
        flags.add("custom_pair_nonheadline")
    if semantic is None:
        flags.add("quote_semantic_identity_missing")
    if decimals is None:
        flags.add("quote_decimals_missing")
    return _envelope(
        chain_namespace="robinhood-mainnet",
        chain_id="4663",
        protocol_namespace="pons_v2",
        stratum="pons_v2_curve_launch",
        launch_id=str(source["curve"]),
        token_id=str(source["token"]),
        anchor_ns=int(source["launch_observed_at_ns"]),
        cutoff_ns=int(source["cutoff_observed_at_ns"]),
        snapshot_ns=int(source["snapshot_observed_at_ns"]),
        horizon_seconds=int(source["horizon_seconds"]),
        quote_unit=quote_unit,
        feature_namespace="robinhood.pons_v2.launch_burst_v0",
        features=features,
        source_snapshot=source,
        adapter_inputs={
            "quote_asset_decimals": quote_asset_decimals,
            "quote_semantic_asset_id": quote_semantic_asset_id,
        },
        provenance=provenance,
        data_quality_flags=tuple(sorted(flags)),
        feature_only=feature_only,
        economic_outcomes_opened=economic_outcomes_opened,
        selector_frozen=selector_frozen,
    )


def assert_raw_quote_comparable_v0(
    left: LaunchBurstEnvelopeV0, right: LaunchBurstEnvelopeV0
) -> None:
    if not left.quote_unit.is_raw_comparison_ready or not right.quote_unit.is_raw_comparison_ready:
        raise ValueError(
            "raw quote comparison requires explicit semantic asset identity and decimals on both snapshots"
        )
    if left.quote_unit.semantic_asset_id != right.quote_unit.semantic_asset_id:
        raise ValueError("raw quote assets are semantically different")
    if left.quote_unit.decimals != right.quote_unit.decimals:
        raise ValueError("raw quote decimals differ")


@dataclass(frozen=True)
class NormalizedFeatureV0:
    source_chain_namespace: str
    source_protocol_namespace: str
    source_feature_namespace: str
    source_feature_name: str
    semantic_feature_name: str
    common_unit: str
    value: float
    normalization_observed_at_ns: int
    normalization_provenance: tuple[str, ...]


def normalize_feature_v0(
    snapshot: LaunchBurstEnvelopeV0, *, source_feature_name: str,
    semantic_feature_name: str, factor: float, common_unit: str,
    normalization_observed_at_ns: int,
    normalization_provenance: tuple[str, ...],
) -> NormalizedFeatureV0:
    """Normalize only through an explicit causal mapping and provenance."""
    source = snapshot.features.get(source_feature_name)
    if not isinstance(source, (int, float)) or isinstance(source, bool):
        raise ValueError("source feature must be a numeric observed feature")
    if not isinstance(factor, (int, float)) or isinstance(factor, bool) or factor <= 0:
        raise ValueError("normalization factor must be positive")
    _nonempty(semantic_feature_name, "semantic_feature_name")
    _nonempty(common_unit, "common_unit")
    _nonnegative(normalization_observed_at_ns, "normalization_observed_at_ns")
    if normalization_observed_at_ns > snapshot.cutoff_observed_at_ns:
        raise ValueError("normalization evidence arrived after the feature cutoff")
    if not normalization_provenance:
        raise ValueError("normalization provenance is required")
    for item in normalization_provenance:
        _nonempty(item, "normalization_provenance item")
    return NormalizedFeatureV0(
        source_chain_namespace=snapshot.chain_namespace,
        source_protocol_namespace=snapshot.protocol_namespace,
        source_feature_namespace=snapshot.feature_namespace,
        source_feature_name=source_feature_name,
        semantic_feature_name=semantic_feature_name,
        common_unit=common_unit,
        value=float(source) * float(factor),
        normalization_observed_at_ns=normalization_observed_at_ns,
        normalization_provenance=tuple(normalization_provenance),
    )


def assert_normalized_comparable_v0(
    left: NormalizedFeatureV0, right: NormalizedFeatureV0
) -> None:
    if left.common_unit != right.common_unit:
        raise ValueError("normalized common units differ")
    if left.semantic_feature_name != right.semantic_feature_name:
        raise ValueError("normalized semantic feature names differ")
