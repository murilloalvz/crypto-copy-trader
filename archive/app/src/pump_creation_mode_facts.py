"""Causal Pump creation-mode facts.

Mayhem Mode is a creation-time protocol fact. It must come from explicit decoded
Pump creation evidence (currently Carbon's maintained `CreateV2` decoder exposes
`is_mayhem_mode`) and must never be inferred from trade intensity or wallet behavior.

This module is versioned separately from `MarketProtocolFactsV0` so the already-frozen
v0 contract is not silently widened. A later protocol-facts version may compose this
surface once the live adapter emits the observation.

`observed_at` is the local causal-availability clock. `chain_time` is an independent
on-chain ordering clock; they are never ordered against each other to decide whether
evidence existed at a local T0.
"""

from dataclasses import dataclass
from typing import Iterable


PUMP_CREATION_MODE_FACTS_VERSION = "pump_creation_mode_facts_v0_clock_domains"

_ALLOWED_EVIDENCE_KINDS = frozenset({"pump_create_v2_instruction"})


@dataclass(frozen=True)
class PumpCreationModeObservation:
    token_mint: str
    chain_time: int
    observed_at: int
    evidence_key: str
    source: str
    evidence_kind: str
    is_mayhem_mode: bool
    decoder_version: str | None = None

    def __post_init__(self) -> None:
        if not self.token_mint.strip():
            raise ValueError("token_mint cannot be empty")
        if self.chain_time < 0 or self.observed_at < 0:
            raise ValueError("timestamps must be non-negative")
        if not self.evidence_key.strip():
            raise ValueError("evidence_key cannot be empty")
        if not self.source.strip():
            raise ValueError("source cannot be empty")
        if self.evidence_kind not in _ALLOWED_EVIDENCE_KINDS:
            raise ValueError(f"unsupported evidence_kind: {self.evidence_kind}")
        if not isinstance(self.is_mayhem_mode, bool):
            raise ValueError("is_mayhem_mode must be bool")
        if self.decoder_version is not None and not self.decoder_version.strip():
            raise ValueError("decoder_version cannot be blank")

    def is_available_at(self, as_of: int) -> bool:
        return self.observed_at <= as_of


@dataclass(frozen=True)
class PumpCreationModeFactsV0:
    method_version: str
    token_mint: str
    as_of: int
    mayhem_mode: bool | None
    evidence_chain_time: int | None
    evidence_observed_at: int | None
    evidence_kind: str | None
    source: str | None
    decoder_version: str | None
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def build_pump_creation_mode_facts_v0(
    *,
    token_mint: str,
    as_of: int,
    observations: Iterable[PumpCreationModeObservation] = (),
) -> PumpCreationModeFactsV0:
    """Return Mayhem mode only when explicit causal CreateV2 evidence is coherent."""

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")

    rows = [
        row
        for row in observations
        if row.token_mint == token_mint and row.is_available_at(as_of)
    ]
    rows.sort(key=lambda row: (row.chain_time, row.observed_at, row.evidence_key))

    provenance = tuple(sorted({row.evidence_key for row in rows}))
    clock_flags = (
        ("chain_clock_ahead_of_local_snapshot_clock_observed",)
        if any(row.chain_time > as_of for row in rows)
        else ()
    )
    if not rows:
        return PumpCreationModeFactsV0(
            method_version=PUMP_CREATION_MODE_FACTS_VERSION,
            token_mint=token_mint,
            as_of=as_of,
            mayhem_mode=None,
            evidence_chain_time=None,
            evidence_observed_at=None,
            evidence_kind=None,
            source=None,
            decoder_version=None,
            provenance_keys=(),
            data_quality_flags=("pump_create_v2_mode_not_observed",),
        )

    distinct_values = {row.is_mayhem_mode for row in rows}
    if len(distinct_values) != 1:
        return PumpCreationModeFactsV0(
            method_version=PUMP_CREATION_MODE_FACTS_VERSION,
            token_mint=token_mint,
            as_of=as_of,
            mayhem_mode=None,
            evidence_chain_time=None,
            evidence_observed_at=None,
            evidence_kind=None,
            source=None,
            decoder_version=None,
            provenance_keys=provenance,
            data_quality_flags=tuple(
                sorted({"pump_create_v2_mayhem_mode_conflict", *clock_flags})
            ),
        )

    latest = rows[-1]
    return PumpCreationModeFactsV0(
        method_version=PUMP_CREATION_MODE_FACTS_VERSION,
        token_mint=token_mint,
        as_of=as_of,
        mayhem_mode=latest.is_mayhem_mode,
        evidence_chain_time=latest.chain_time,
        evidence_observed_at=latest.observed_at,
        evidence_kind=latest.evidence_kind,
        source=latest.source,
        decoder_version=latest.decoder_version,
        provenance_keys=provenance,
        data_quality_flags=clock_flags,
    )
