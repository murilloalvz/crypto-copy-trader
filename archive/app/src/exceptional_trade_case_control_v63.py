from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


EXCEPTIONAL_TRADE_CASE_CONTROL_VERSION = "exceptional_trade_case_control_v63_outcome_blind"


@dataclass(frozen=True)
class FrozenOutcomeLabelV63:
    """Outcome label kept separate from causal pre-entry features.

    ``outcome_value`` is diagnostic metadata only and is deliberately excluded from matching.
    The caller is responsible for freezing the label definition before joining labels to features.
    """

    reference_key: str
    wallet_address: str
    label: str
    label_frozen_at: int
    outcome_value: float | None = None


@dataclass(frozen=True)
class PreEntryMatchCovariatesV63:
    """Entry-time covariates that are allowed to participate in matching."""

    reference_key: str
    wallet_address: str
    entry_chain_time: int
    strategy_signature: str
    venue_bucket: str
    entry_notional_bucket: str
    market_age_bucket: str


@dataclass(frozen=True)
class MatchedCaseControlV63:
    case_reference_key: str
    control_reference_key: str
    wallet_address: str
    strategy_signature: str
    venue_bucket: str
    entry_notional_bucket: str
    market_age_bucket: str
    entry_time_distance_seconds: int


@dataclass(frozen=True)
class CaseControlMatchResultV63:
    method_version: str
    case_count: int
    control_count: int
    matched_pair_count: int
    unmatched_case_reference_keys: tuple[str, ...]
    unused_control_reference_keys: tuple[str, ...]
    pairs: tuple[MatchedCaseControlV63, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_label(item: FrozenOutcomeLabelV63) -> None:
    _required(item.reference_key, "reference_key")
    _required(item.wallet_address, "wallet_address")
    if item.label not in {"case", "control"}:
        raise ValueError("label must be case or control")
    if int(item.label_frozen_at) < 0:
        raise ValueError("label_frozen_at must be non-negative")


def _validate_covariates(item: PreEntryMatchCovariatesV63) -> None:
    _required(item.reference_key, "reference_key")
    _required(item.wallet_address, "wallet_address")
    _required(item.strategy_signature, "strategy_signature")
    _required(item.venue_bucket, "venue_bucket")
    _required(item.entry_notional_bucket, "entry_notional_bucket")
    _required(item.market_age_bucket, "market_age_bucket")
    if int(item.entry_chain_time) < 0:
        raise ValueError("entry_chain_time must be non-negative")


def _exact_match_key(item: PreEntryMatchCovariatesV63) -> tuple[str, str, str, str, str]:
    return (
        item.wallet_address,
        item.strategy_signature,
        item.venue_bucket,
        item.entry_notional_bucket,
        item.market_age_bucket,
    )


def match_exceptional_trade_cases_v63(
    *,
    outcome_labels: Iterable[FrozenOutcomeLabelV63],
    preentry_covariates: Iterable[PreEntryMatchCovariatesV63],
) -> CaseControlMatchResultV63:
    """Pair cases to controls without consulting outcome magnitude.

    Matching is exact on wallet + frozen strategy signature + venue + entry-notional bucket +
    market-age bucket. Within an exact stratum, nearest entry time is the deterministic tie-breaker.
    Controls are used at most once. No fallback relaxation is performed if a stratum lacks controls.

    This function must be called only after causal pre-entry snapshots have already been built. It
    does not inspect those feature values and therefore cannot select a control because its future
    outcome or feature vector looks convenient.
    """

    labels: dict[str, FrozenOutcomeLabelV63] = {}
    for item in outcome_labels:
        _validate_label(item)
        if item.reference_key in labels:
            raise ValueError("duplicate outcome label reference_key")
        labels[item.reference_key] = item

    covariates: dict[str, PreEntryMatchCovariatesV63] = {}
    for item in preentry_covariates:
        _validate_covariates(item)
        if item.reference_key in covariates:
            raise ValueError("duplicate covariate reference_key")
        covariates[item.reference_key] = item

    missing_covariates = sorted(set(labels) - set(covariates))
    if missing_covariates:
        raise ValueError("every labeled reference must have pre-entry covariates")

    for key, label in labels.items():
        if label.wallet_address != covariates[key].wallet_address:
            raise ValueError("label/covariate wallet mismatch")

    cases = sorted(
        (item for item in labels.values() if item.label == "case"),
        key=lambda item: item.reference_key,
    )
    controls = sorted(
        (item for item in labels.values() if item.label == "control"),
        key=lambda item: item.reference_key,
    )

    controls_by_stratum: dict[tuple[str, str, str, str, str], list[PreEntryMatchCovariatesV63]] = {}
    for label in controls:
        cov = covariates[label.reference_key]
        controls_by_stratum.setdefault(_exact_match_key(cov), []).append(cov)

    for rows in controls_by_stratum.values():
        rows.sort(key=lambda item: (item.entry_chain_time, item.reference_key))

    used_controls: set[str] = set()
    pairs: list[MatchedCaseControlV63] = []
    unmatched: list[str] = []

    for label in cases:
        case = covariates[label.reference_key]
        candidates = [
            item
            for item in controls_by_stratum.get(_exact_match_key(case), [])
            if item.reference_key not in used_controls
        ]
        if not candidates:
            unmatched.append(case.reference_key)
            continue
        candidates.sort(
            key=lambda item: (
                abs(int(item.entry_chain_time) - int(case.entry_chain_time)),
                item.entry_chain_time,
                item.reference_key,
            )
        )
        control = candidates[0]
        used_controls.add(control.reference_key)
        pairs.append(
            MatchedCaseControlV63(
                case_reference_key=case.reference_key,
                control_reference_key=control.reference_key,
                wallet_address=case.wallet_address,
                strategy_signature=case.strategy_signature,
                venue_bucket=case.venue_bucket,
                entry_notional_bucket=case.entry_notional_bucket,
                market_age_bucket=case.market_age_bucket,
                entry_time_distance_seconds=abs(
                    int(control.entry_chain_time) - int(case.entry_chain_time)
                ),
            )
        )

    unused_controls = sorted(
        label.reference_key
        for label in controls
        if label.reference_key not in used_controls
    )
    return CaseControlMatchResultV63(
        method_version=EXCEPTIONAL_TRADE_CASE_CONTROL_VERSION,
        case_count=len(cases),
        control_count=len(controls),
        matched_pair_count=len(pairs),
        unmatched_case_reference_keys=tuple(unmatched),
        unused_control_reference_keys=tuple(unused_controls),
        pairs=tuple(pairs),
    )
