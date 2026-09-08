from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable

from src.pons_curve_state_progress_v64 import PonsCurveProgressSnapshotV64
from src.protocol_deployment_attestation_v66 import (
    ProtocolDeploymentAttestationV66,
    capability_authoritative_for_read_v66,
)


PONS_LAUNCH_QUALITY_EVIDENCE_VERSION = "pons_launch_quality_evidence_v67_raw"


@dataclass(frozen=True)
class PonsLaunchStaticEvidenceV67:
    token_address: str
    curve_address: str
    deployer_address: str
    launch_chain_time: int
    launch_observed_at: int
    dev_quote_spent_raw: int | None
    dev_tokens_received_raw: int | None
    launch_supply_raw: int | None
    creator_tax_bps: int | None
    creator_fee_recipient: str | None
    declared_exemption_count: int | None
    social_x_present: bool | None
    social_website_present: bool | None
    social_telegram_present: bool | None
    description_length: int | None
    evidence_reference: str


@dataclass(frozen=True)
class PonsDeployerHistoryEvidenceV67:
    deployer_address: str
    before_block_number: int
    history_observed_at: int
    prior_launch_count: int | None
    prior_graduated_count: int | None
    history_complete: bool
    evidence_reference: str


@dataclass(frozen=True)
class PonsPriorFingerprintEvidenceV67:
    fingerprint_key: str
    before_chain_time: int
    window_seconds: int
    prior_matching_launch_count: int | None
    distinct_prior_deployer_count: int | None
    evidence_complete: bool
    evidence_reference: str


@dataclass(frozen=True)
class PonsEarlyActivityEvidenceV67:
    token_address: str
    as_of: int
    window_seconds: int
    event_count: int
    buy_count: int
    sell_count: int
    wallet_identity_coverage_pct: float | None
    unique_buyer_count: int | None
    unique_seller_count: int | None
    repeated_wallet_event_share_pct: float | None
    data_quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PonsOpeningTaxEvidenceV67:
    token_address: str
    recipient_address: str
    opening_tax_bps: int
    chain_time: int
    observed_at: int
    capability_name: str
    evidence_reference: str


@dataclass(frozen=True)
class PonsLaunchQualityEvidenceV67:
    method_version: str
    token_address: str
    as_of: int
    deployment_attestation_sha256: str
    launch_age_seconds: int | None
    dev_buy_token_share_pct: float | None
    creator_tax_bps: int | None
    creator_fee_recipient_is_deployer: bool | None
    declared_exemption_count: int | None
    social_x_present: bool | None
    social_website_present: bool | None
    social_telegram_present: bool | None
    social_channel_count: int | None
    description_length: int | None
    deployer_prior_launch_count: int | None
    deployer_prior_graduated_count: int | None
    deployer_prior_graduation_share_pct: float | None
    fingerprint_prior_matching_launch_count: int | None
    fingerprint_distinct_prior_deployer_count: int | None
    early_event_count: int | None
    early_buy_count: int | None
    early_sell_count: int | None
    early_unique_buyer_count: int | None
    early_unique_seller_count: int | None
    early_repeated_wallet_event_share_pct: float | None
    reserve_progress_pct: float | None
    current_opening_tax_bps: int | None
    data_quality_flags: tuple[str, ...]
    evidence_sha256: str


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _address(value: str, name: str) -> str:
    raw = _required(value, name)
    if not raw.startswith("0x") or len(raw) != 42:
        raise ValueError(f"{name} must be a 20-byte EVM address")
    try:
        int(raw[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a 20-byte EVM address") from exc
    return raw.lower()


def _pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    value = 100.0 * num / den
    return value if math.isfinite(value) else None


def _validate_static(item: PonsLaunchStaticEvidenceV67) -> None:
    _address(item.token_address, "token_address")
    _address(item.curve_address, "curve_address")
    _address(item.deployer_address, "deployer_address")
    _required(item.evidence_reference, "evidence_reference")
    if item.launch_chain_time < 0 or item.launch_observed_at < 0:
        raise ValueError("launch timestamps must be non-negative")
    if item.launch_observed_at < item.launch_chain_time:
        raise ValueError("launch_observed_at cannot precede launch_chain_time")
    for name in ("dev_quote_spent_raw", "dev_tokens_received_raw", "launch_supply_raw"):
        value = getattr(item, name)
        if value is not None and int(value) < 0:
            raise ValueError(f"{name} must be non-negative")
    if item.creator_tax_bps is not None and not 0 <= int(item.creator_tax_bps) <= 10_000:
        raise ValueError("creator_tax_bps must be between 0 and 10000")
    if item.creator_fee_recipient is not None:
        _address(item.creator_fee_recipient, "creator_fee_recipient")
    if item.declared_exemption_count is not None and int(item.declared_exemption_count) < 0:
        raise ValueError("declared_exemption_count must be non-negative")
    if item.description_length is not None and int(item.description_length) < 0:
        raise ValueError("description_length must be non-negative")


def _validate_deployer(item: PonsDeployerHistoryEvidenceV67) -> None:
    _address(item.deployer_address, "deployer_address")
    _required(item.evidence_reference, "evidence_reference")
    if item.before_block_number < 0 or item.history_observed_at < 0:
        raise ValueError("deployer history clocks must be non-negative")
    for name in ("prior_launch_count", "prior_graduated_count"):
        value = getattr(item, name)
        if value is not None and int(value) < 0:
            raise ValueError(f"{name} must be non-negative")
    if (
        item.prior_launch_count is not None
        and item.prior_graduated_count is not None
        and item.prior_graduated_count > item.prior_launch_count
    ):
        raise ValueError("prior_graduated_count cannot exceed prior_launch_count")


def _validate_fingerprint(item: PonsPriorFingerprintEvidenceV67) -> None:
    _required(item.fingerprint_key, "fingerprint_key")
    _required(item.evidence_reference, "evidence_reference")
    if item.before_chain_time < 0 or item.window_seconds <= 0:
        raise ValueError("fingerprint clocks must be positive/non-negative")
    for name in ("prior_matching_launch_count", "distinct_prior_deployer_count"):
        value = getattr(item, name)
        if value is not None and int(value) < 0:
            raise ValueError(f"{name} must be non-negative")


def _validate_activity(item: PonsEarlyActivityEvidenceV67) -> None:
    _address(item.token_address, "token_address")
    if item.as_of < 0 or item.window_seconds <= 0:
        raise ValueError("activity clocks must be positive/non-negative")
    if min(item.event_count, item.buy_count, item.sell_count) < 0:
        raise ValueError("activity counts must be non-negative")
    if item.buy_count + item.sell_count != item.event_count:
        raise ValueError("buy_count + sell_count must equal event_count")
    if item.wallet_identity_coverage_pct is not None and not 0 <= item.wallet_identity_coverage_pct <= 100:
        raise ValueError("wallet identity coverage must be between 0 and 100")
    for name in ("unique_buyer_count", "unique_seller_count"):
        value = getattr(item, name)
        if value is not None and int(value) < 0:
            raise ValueError(f"{name} must be non-negative")
    if item.repeated_wallet_event_share_pct is not None and not 0 <= item.repeated_wallet_event_share_pct <= 100:
        raise ValueError("repeated wallet share must be between 0 and 100")


def _validate_opening_tax(item: PonsOpeningTaxEvidenceV67) -> None:
    _address(item.token_address, "token_address")
    _address(item.recipient_address, "recipient_address")
    _required(item.capability_name, "capability_name")
    _required(item.evidence_reference, "evidence_reference")
    if not 0 <= int(item.opening_tax_bps) <= 10_000:
        raise ValueError("opening_tax_bps must be between 0 and 10000")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("opening-tax timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("opening-tax observed_at cannot precede chain_time")


def build_pons_launch_quality_evidence_v67(
    *,
    as_of: int,
    deployment: ProtocolDeploymentAttestationV66,
    static: PonsLaunchStaticEvidenceV67,
    deployer_history: PonsDeployerHistoryEvidenceV67 | None = None,
    fingerprint_history: PonsPriorFingerprintEvidenceV67 | None = None,
    early_activity: PonsEarlyActivityEvidenceV67 | None = None,
    curve_progress: PonsCurveProgressSnapshotV64 | None = None,
    opening_tax: PonsOpeningTaxEvidenceV67 | None = None,
) -> PonsLaunchQualityEvidenceV67:
    """Join causal raw evidence without turning it into a weighted launch score.

    Every optional family fails to missing if its provenance is incomplete or postdates ``as_of``.
    Opening-tax evidence has an additional hard gate: the exact read capability must be authoritative
    in the v66 deployment attestation. Source-only or third-party descriptions cannot populate it.
    """

    cutoff = int(as_of)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")
    _validate_static(static)
    token = _address(static.token_address, "token_address")
    deployer = _address(static.deployer_address, "deployer_address")

    if static.launch_observed_at > cutoff:
        raise ValueError("launch evidence was not known by as_of")
    if deployment.observed_at > cutoff:
        raise ValueError("deployment attestation was not known by as_of")

    flags: list[str] = []
    launch_age = max(0, cutoff - static.launch_chain_time) if static.launch_chain_time <= cutoff else None
    if launch_age is None:
        flags.append("launch_chain_time_after_as_of")

    dev_share = None
    if static.dev_tokens_received_raw is not None and static.launch_supply_raw is not None:
        dev_share = _pct(int(static.dev_tokens_received_raw), int(static.launch_supply_raw))
        if dev_share is not None and dev_share > 100:
            flags.append("dev_buy_token_share_above_100pct")
            dev_share = None
    elif static.dev_tokens_received_raw is not None or static.launch_supply_raw is not None:
        flags.append("partial_dev_buy_share_inputs")

    fee_recipient_same = None
    if static.creator_fee_recipient is not None:
        fee_recipient_same = _address(static.creator_fee_recipient, "creator_fee_recipient") == deployer

    social_values = (
        static.social_x_present,
        static.social_website_present,
        static.social_telegram_present,
    )
    social_count = None
    if all(value is not None for value in social_values):
        social_count = sum(bool(value) for value in social_values)
    elif any(value is not None for value in social_values):
        flags.append("partial_social_presence_fields")

    prior_launches = None
    prior_graduated = None
    prior_grad_share = None
    if deployer_history is not None:
        _validate_deployer(deployer_history)
        if _address(deployer_history.deployer_address, "deployer_address") != deployer:
            raise ValueError("deployer history address mismatch")
        if deployer_history.history_observed_at <= cutoff and deployer_history.history_complete:
            prior_launches = deployer_history.prior_launch_count
            prior_graduated = deployer_history.prior_graduated_count
            if prior_launches is not None and prior_graduated is not None and prior_launches > 0:
                prior_grad_share = _pct(int(prior_graduated), int(prior_launches))
        else:
            flags.append("deployer_history_incomplete_or_not_known_by_as_of")

    fp_count = None
    fp_deployers = None
    if fingerprint_history is not None:
        _validate_fingerprint(fingerprint_history)
        if fingerprint_history.before_chain_time > static.launch_chain_time:
            raise ValueError("fingerprint history cutoff cannot follow launch chain time")
        if fingerprint_history.evidence_complete:
            fp_count = fingerprint_history.prior_matching_launch_count
            fp_deployers = fingerprint_history.distinct_prior_deployer_count
        else:
            flags.append("fingerprint_history_incomplete")

    early_event_count = None
    early_buy_count = None
    early_sell_count = None
    early_unique_buyers = None
    early_unique_sellers = None
    early_repeat = None
    if early_activity is not None:
        _validate_activity(early_activity)
        if _address(early_activity.token_address, "token_address") != token:
            raise ValueError("early activity token mismatch")
        if early_activity.as_of > cutoff:
            raise ValueError("early activity postdates as_of")
        early_event_count = early_activity.event_count
        early_buy_count = early_activity.buy_count
        early_sell_count = early_activity.sell_count
        if early_activity.wallet_identity_coverage_pct == 100.0:
            early_unique_buyers = early_activity.unique_buyer_count
            early_unique_sellers = early_activity.unique_seller_count
            early_repeat = early_activity.repeated_wallet_event_share_pct
        else:
            flags.append("early_wallet_identity_coverage_incomplete")

    progress = None
    if curve_progress is not None:
        if _address(curve_progress.token_address, "token_address") != token:
            raise ValueError("curve progress token mismatch")
        if curve_progress.as_of > cutoff:
            raise ValueError("curve progress postdates as_of")
        progress = curve_progress.reserve_progress_pct
        if progress is None:
            flags.append("curve_progress_unavailable")

    current_tax = None
    if opening_tax is not None:
        _validate_opening_tax(opening_tax)
        if _address(opening_tax.token_address, "token_address") != token:
            raise ValueError("opening-tax token mismatch")
        if opening_tax.observed_at > cutoff or opening_tax.chain_time > cutoff:
            raise ValueError("opening-tax evidence postdates as_of")
        if capability_authoritative_for_read_v66(deployment, opening_tax.capability_name):
            current_tax = int(opening_tax.opening_tax_bps)
        else:
            flags.append("opening_tax_capability_not_authoritative")

    payload = {
        "method_version": PONS_LAUNCH_QUALITY_EVIDENCE_VERSION,
        "token_address": token,
        "as_of": cutoff,
        "deployment_attestation_sha256": deployment.attestation_sha256,
        "launch_age_seconds": launch_age,
        "dev_buy_token_share_pct": dev_share,
        "creator_tax_bps": static.creator_tax_bps,
        "creator_fee_recipient_is_deployer": fee_recipient_same,
        "declared_exemption_count": static.declared_exemption_count,
        "social_x_present": static.social_x_present,
        "social_website_present": static.social_website_present,
        "social_telegram_present": static.social_telegram_present,
        "social_channel_count": social_count,
        "description_length": static.description_length,
        "deployer_prior_launch_count": prior_launches,
        "deployer_prior_graduated_count": prior_graduated,
        "deployer_prior_graduation_share_pct": prior_grad_share,
        "fingerprint_prior_matching_launch_count": fp_count,
        "fingerprint_distinct_prior_deployer_count": fp_deployers,
        "early_event_count": early_event_count,
        "early_buy_count": early_buy_count,
        "early_sell_count": early_sell_count,
        "early_unique_buyer_count": early_unique_buyers,
        "early_unique_seller_count": early_unique_sellers,
        "early_repeated_wallet_event_share_pct": early_repeat,
        "reserve_progress_pct": progress,
        "current_opening_tax_bps": current_tax,
        "data_quality_flags": sorted(set(flags)),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()

    return PonsLaunchQualityEvidenceV67(
        method_version=PONS_LAUNCH_QUALITY_EVIDENCE_VERSION,
        token_address=token,
        as_of=cutoff,
        deployment_attestation_sha256=deployment.attestation_sha256,
        launch_age_seconds=launch_age,
        dev_buy_token_share_pct=dev_share,
        creator_tax_bps=static.creator_tax_bps,
        creator_fee_recipient_is_deployer=fee_recipient_same,
        declared_exemption_count=static.declared_exemption_count,
        social_x_present=static.social_x_present,
        social_website_present=static.social_website_present,
        social_telegram_present=static.social_telegram_present,
        social_channel_count=social_count,
        description_length=static.description_length,
        deployer_prior_launch_count=prior_launches,
        deployer_prior_graduated_count=prior_graduated,
        deployer_prior_graduation_share_pct=prior_grad_share,
        fingerprint_prior_matching_launch_count=fp_count,
        fingerprint_distinct_prior_deployer_count=fp_deployers,
        early_event_count=early_event_count,
        early_buy_count=early_buy_count,
        early_sell_count=early_sell_count,
        early_unique_buyer_count=early_unique_buyers,
        early_unique_seller_count=early_unique_sellers,
        early_repeated_wallet_event_share_pct=early_repeat,
        reserve_progress_pct=progress,
        current_opening_tax_bps=current_tax,
        data_quality_flags=tuple(sorted(set(flags))),
        evidence_sha256=digest,
    )
