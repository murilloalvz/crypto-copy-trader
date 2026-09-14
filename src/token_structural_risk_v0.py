"""Provider-neutral, score-free structural token risk facts.

This module normalizes structural token/holder risk observations from external or
chain-derived providers without turning them into a trade score or recommendation.
All evidence is gated by local ``observed_at <= as_of`` causality. When multiple
providers are available, numeric values are exposed as ranges and boolean claims
require unanimous agreement before a consensus value is emitted.

Provider labels such as ``insider``, ``sniper``, ``bundler`` and ``honeypot`` are
kept as provider-derived claims, not independently proven ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


TOKEN_STRUCTURAL_RISK_VERSION = "token_structural_risk_v0_provider_neutral"

_PERCENT_FIELDS = (
    "top10_holder_pct",
    "largest_holder_pct",
    "dev_holder_pct",
    "insider_holder_pct",
    "sniper_holder_pct",
    "bundler_holder_pct",
    "liquidity_burned_pct",
    "liquidity_locked_pct",
)


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _pct(value: float | None, name: str) -> None:
    if value is None:
        return
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 100.0:
        raise ValueError(f"{name} must be finite in [0, 100] when present")


def _optional_bool(value: bool | None, name: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{name} must be bool or None")


@dataclass(frozen=True)
class StructuralRiskObservationV0:
    token_mint: str
    observed_at: int
    evidence_key: str
    source: str

    holder_count: int | None = None
    top10_holder_pct: float | None = None
    largest_holder_pct: float | None = None
    dev_holder_pct: float | None = None
    insider_holder_pct: float | None = None
    sniper_holder_pct: float | None = None
    bundler_holder_pct: float | None = None

    mint_authority_active: bool | None = None
    freeze_authority_active: bool | None = None
    provider_honeypot_flag: bool | None = None

    liquidity_burned_pct: float | None = None
    liquidity_locked_pct: float | None = None

    creator_wallet: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.token_mint, "token_mint")
        _nonempty(self.evidence_key, "evidence_key")
        _nonempty(self.source, "source")
        if (
            not isinstance(self.observed_at, int)
            or isinstance(self.observed_at, bool)
            or self.observed_at < 0
        ):
            raise ValueError("observed_at must be a non-negative integer")
        if self.holder_count is not None and (
            not isinstance(self.holder_count, int)
            or isinstance(self.holder_count, bool)
            or self.holder_count < 0
        ):
            raise ValueError("holder_count must be a non-negative integer when present")
        for name in _PERCENT_FIELDS:
            _pct(getattr(self, name), name)
        _optional_bool(self.mint_authority_active, "mint_authority_active")
        _optional_bool(self.freeze_authority_active, "freeze_authority_active")
        _optional_bool(self.provider_honeypot_flag, "provider_honeypot_flag")
        if self.creator_wallet is not None:
            _nonempty(self.creator_wallet, "creator_wallet")


@dataclass(frozen=True)
class NumericEvidenceRangeV0:
    metric: str
    known_source_count: int
    min_value: float | None
    max_value: float | None
    latest_observed_at: int | None
    source_values: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class BooleanEvidenceConsensusV0:
    metric: str
    known_source_count: int
    consensus_value: bool | None
    conflict: bool
    latest_observed_at: int | None
    source_values: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class TokenStructuralRiskFactsV0:
    method_version: str
    token_mint: str
    as_of: int
    source_count: int
    sources: tuple[str, ...]
    latest_observed_at: int | None

    holder_count: NumericEvidenceRangeV0
    top10_holder_pct: NumericEvidenceRangeV0
    largest_holder_pct: NumericEvidenceRangeV0
    dev_holder_pct: NumericEvidenceRangeV0
    insider_holder_pct: NumericEvidenceRangeV0
    sniper_holder_pct: NumericEvidenceRangeV0
    bundler_holder_pct: NumericEvidenceRangeV0
    liquidity_burned_pct: NumericEvidenceRangeV0
    liquidity_locked_pct: NumericEvidenceRangeV0

    mint_authority_active: BooleanEvidenceConsensusV0
    freeze_authority_active: BooleanEvidenceConsensusV0
    provider_honeypot_flag: BooleanEvidenceConsensusV0

    creator_wallets: tuple[str, ...]
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _latest_per_source(
    rows: Iterable[StructuralRiskObservationV0],
    *,
    token_mint: str,
    as_of: int,
) -> list[StructuralRiskObservationV0]:
    latest: dict[str, StructuralRiskObservationV0] = {}
    for row in rows:
        if row.token_mint != token_mint or row.observed_at > as_of:
            continue
        current = latest.get(row.source)
        if current is None or (row.observed_at, row.evidence_key) > (
            current.observed_at,
            current.evidence_key,
        ):
            latest[row.source] = row
    return [latest[key] for key in sorted(latest)]


def _numeric_range(
    metric: str,
    rows: list[StructuralRiskObservationV0],
) -> NumericEvidenceRangeV0:
    pairs: list[tuple[str, float, int]] = []
    for row in rows:
        value = getattr(row, metric)
        if value is not None:
            pairs.append((row.source, float(value), row.observed_at))
    values = [value for _, value, _ in pairs]
    return NumericEvidenceRangeV0(
        metric=metric,
        known_source_count=len(pairs),
        min_value=min(values) if values else None,
        max_value=max(values) if values else None,
        latest_observed_at=max((observed for _, _, observed in pairs), default=None),
        source_values=tuple((source, value) for source, value, _ in pairs),
    )


def _boolean_consensus(
    metric: str,
    rows: list[StructuralRiskObservationV0],
) -> BooleanEvidenceConsensusV0:
    pairs: list[tuple[str, bool, int]] = []
    for row in rows:
        value = getattr(row, metric)
        if value is not None:
            pairs.append((row.source, bool(value), row.observed_at))
    values = {value for _, value, _ in pairs}
    conflict = len(values) > 1
    consensus = next(iter(values)) if len(values) == 1 else None
    return BooleanEvidenceConsensusV0(
        metric=metric,
        known_source_count=len(pairs),
        consensus_value=consensus,
        conflict=conflict,
        latest_observed_at=max((observed for _, _, observed in pairs), default=None),
        source_values=tuple((source, value) for source, value, _ in pairs),
    )


def build_token_structural_risk_facts_v0(
    *,
    token_mint: str,
    as_of: int,
    observations: Iterable[StructuralRiskObservationV0] = (),
) -> TokenStructuralRiskFactsV0:
    """Build causal structural-risk facts without scoring or provider preference."""

    _nonempty(token_mint, "token_mint")
    if not isinstance(as_of, int) or isinstance(as_of, bool) or as_of < 0:
        raise ValueError("as_of must be a non-negative integer")

    normalized = list(observations)
    for row in normalized:
        if not isinstance(row, StructuralRiskObservationV0):
            raise TypeError("observations must contain StructuralRiskObservationV0")

    rows = _latest_per_source(normalized, token_mint=token_mint, as_of=as_of)
    numeric = {
        name: _numeric_range(name, rows)
        for name in ("holder_count", *_PERCENT_FIELDS)
    }
    boolean = {
        name: _boolean_consensus(name, rows)
        for name in (
            "mint_authority_active",
            "freeze_authority_active",
            "provider_honeypot_flag",
        )
    }

    quality: set[str] = set()
    if not rows:
        quality.add("no_structural_risk_observations")
    if numeric["holder_count"].known_source_count == 0:
        quality.add("holder_count_unavailable")
    if (
        numeric["top10_holder_pct"].known_source_count == 0
        and numeric["largest_holder_pct"].known_source_count == 0
    ):
        quality.add("holder_concentration_unavailable")
    if all(
        numeric[name].known_source_count == 0
        for name in (
            "dev_holder_pct",
            "insider_holder_pct",
            "sniper_holder_pct",
            "bundler_holder_pct",
        )
    ):
        quality.add("provider_tagged_holder_profile_unavailable")
    if all(
        boolean[name].known_source_count == 0
        for name in ("mint_authority_active", "freeze_authority_active")
    ):
        quality.add("authority_state_unavailable")
    if boolean["provider_honeypot_flag"].known_source_count == 0:
        quality.add("provider_honeypot_claim_unavailable")
    if all(
        numeric[name].known_source_count == 0
        for name in ("liquidity_burned_pct", "liquidity_locked_pct")
    ):
        quality.add("liquidity_lock_burn_context_unavailable")
    for name, item in boolean.items():
        if item.conflict:
            quality.add(f"source_conflict:{name}")

    creator_wallets = tuple(
        sorted({row.creator_wallet for row in rows if row.creator_wallet is not None})
    )
    provenance = tuple(sorted({row.evidence_key for row in rows}))

    return TokenStructuralRiskFactsV0(
        method_version=TOKEN_STRUCTURAL_RISK_VERSION,
        token_mint=token_mint,
        as_of=as_of,
        source_count=len(rows),
        sources=tuple(row.source for row in rows),
        latest_observed_at=max((row.observed_at for row in rows), default=None),
        holder_count=numeric["holder_count"],
        top10_holder_pct=numeric["top10_holder_pct"],
        largest_holder_pct=numeric["largest_holder_pct"],
        dev_holder_pct=numeric["dev_holder_pct"],
        insider_holder_pct=numeric["insider_holder_pct"],
        sniper_holder_pct=numeric["sniper_holder_pct"],
        bundler_holder_pct=numeric["bundler_holder_pct"],
        liquidity_burned_pct=numeric["liquidity_burned_pct"],
        liquidity_locked_pct=numeric["liquidity_locked_pct"],
        mint_authority_active=boolean["mint_authority_active"],
        freeze_authority_active=boolean["freeze_authority_active"],
        provider_honeypot_flag=boolean["provider_honeypot_flag"],
        creator_wallets=creator_wallets,
        provenance_keys=provenance,
        data_quality_flags=tuple(sorted(quality)),
    )
