"""Causal, score-free Social/Event-First evidence contract.

This module intentionally does not compute sentiment, influencer quality, confidence,
TAKE/SKIP actions or market convergence. Local ``observed_at`` is the only causal
availability clock. Provider/source ``created_at`` is preserved as metadata and is
never used to make evidence available earlier than it was locally observed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


SOCIAL_EVENT_EVIDENCE_VERSION = "social_event_evidence_v0_causal"

ATTRIBUTION_MINT_DIRECT = "MINT_DIRECT"
ATTRIBUTION_LINK_RESOLVED = "LINK_RESOLVED"
ATTRIBUTION_MANUAL_VERIFIED = "MANUAL_VERIFIED"
ATTRIBUTION_SYMBOL_ONLY_AMBIGUOUS = "SYMBOL_ONLY_AMBIGUOUS"

_STRONG_ATTRIBUTION_KINDS = {
    ATTRIBUTION_MINT_DIRECT,
    ATTRIBUTION_LINK_RESOLVED,
    ATTRIBUTION_MANUAL_VERIFIED,
}
_ALLOWED_ATTRIBUTION_KINDS = _STRONG_ATTRIBUTION_KINDS | {
    ATTRIBUTION_SYMBOL_ONLY_AMBIGUOUS
}


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _clock(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class SocialEventObservationV0:
    token_mint: str
    observed_at: int
    evidence_key: str
    source: str
    source_event_id: str
    event_type: str
    attribution_kind: str
    source_created_at: int | None = None
    author_id: str | None = None
    content_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _required(self.token_mint, "token_mint")
        _required(self.evidence_key, "evidence_key")
        _required(self.source, "source")
        _required(self.source_event_id, "source_event_id")
        _required(self.event_type, "event_type")
        _clock(self.observed_at, "observed_at")
        if self.attribution_kind not in _ALLOWED_ATTRIBUTION_KINDS:
            raise ValueError(f"unsupported attribution_kind: {self.attribution_kind}")
        if self.source_created_at is not None:
            _clock(self.source_created_at, "source_created_at")
        if self.author_id is not None:
            _required(self.author_id, "author_id")
        if self.content_fingerprint is not None:
            _required(self.content_fingerprint, "content_fingerprint")


@dataclass(frozen=True)
class SocialEventEvidenceSnapshotV0:
    method_version: str
    token_mint: str
    as_of: int
    window_seconds: int
    deduped_event_count: int
    attributed_event_count: int
    ambiguous_event_count: int
    unique_author_count: int
    first_observed_at: int | None
    latest_observed_at: int | None
    source_counts: tuple[tuple[str, int], ...]
    event_type_counts: tuple[tuple[str, int], ...]
    attribution_counts: tuple[tuple[str, int], ...]
    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _dedupe_first_seen(
    rows: Iterable[SocialEventObservationV0],
) -> list[SocialEventObservationV0]:
    first: dict[tuple[str, str], SocialEventObservationV0] = {}
    for row in rows:
        key = (row.source, row.source_event_id)
        current = first.get(key)
        if current is None or (row.observed_at, row.evidence_key) < (
            current.observed_at,
            current.evidence_key,
        ):
            first[key] = row
    return sorted(
        first.values(),
        key=lambda item: (item.observed_at, item.source, item.source_event_id),
    )


def build_social_event_evidence_snapshot_v0(
    *,
    token_mint: str,
    as_of: int,
    observations: Iterable[SocialEventObservationV0] = (),
    window_seconds: int = 300,
) -> SocialEventEvidenceSnapshotV0:
    """Build one causal social/event snapshot using only local observation time."""

    _required(token_mint, "token_mint")
    cutoff = _clock(as_of, "as_of")
    if not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or window_seconds <= 0:
        raise ValueError("window_seconds must be a positive integer")

    normalized = list(observations)
    for row in normalized:
        if not isinstance(row, SocialEventObservationV0):
            raise TypeError("observations must contain SocialEventObservationV0")

    lower = cutoff - window_seconds
    causal = [
        row
        for row in normalized
        if row.token_mint == token_mint
        and row.observed_at <= cutoff
        and row.observed_at > lower
    ]
    deduped = _dedupe_first_seen(causal)
    attributed = [
        row for row in deduped if row.attribution_kind in _STRONG_ATTRIBUTION_KINDS
    ]
    ambiguous = [
        row
        for row in deduped
        if row.attribution_kind == ATTRIBUTION_SYMBOL_ONLY_AMBIGUOUS
    ]

    source_counts = Counter(row.source for row in attributed)
    event_type_counts = Counter(row.event_type for row in attributed)
    attribution_counts = Counter(row.attribution_kind for row in deduped)
    authors = {row.author_id for row in attributed if row.author_id is not None}

    quality: set[str] = set()
    if not deduped:
        quality.add("no_social_event_evidence_in_window")
    if ambiguous:
        quality.add("ambiguous_symbol_only_attribution_present")
    if attributed and len(authors) < len(attributed):
        quality.add("partial_author_identity_coverage")
    if any(row.source_created_at is None for row in deduped):
        quality.add("source_created_at_partial_or_missing")
    if any(
        row.source_created_at is not None and row.source_created_at > row.observed_at
        for row in deduped
    ):
        quality.add("source_created_at_after_local_observation_clock")

    return SocialEventEvidenceSnapshotV0(
        method_version=SOCIAL_EVENT_EVIDENCE_VERSION,
        token_mint=token_mint,
        as_of=cutoff,
        window_seconds=window_seconds,
        deduped_event_count=len(deduped),
        attributed_event_count=len(attributed),
        ambiguous_event_count=len(ambiguous),
        unique_author_count=len(authors),
        first_observed_at=(deduped[0].observed_at if deduped else None),
        latest_observed_at=(deduped[-1].observed_at if deduped else None),
        source_counts=tuple(sorted(source_counts.items())),
        event_type_counts=tuple(sorted(event_type_counts.items())),
        attribution_counts=tuple(sorted(attribution_counts.items())),
        provenance_keys=tuple(row.evidence_key for row in deduped),
        data_quality_flags=tuple(sorted(quality)),
    )
