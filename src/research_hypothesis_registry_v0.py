"""Immutable research-hypothesis registry with cross-track convergence guards.

The registry is a scientific bookkeeping primitive, not a strategy engine. A hypothesis
record is immutable; changing a frozen contract requires a new hypothesis id rather than
mutating history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable


REGISTRY_VERSION = "research_hypothesis_registry_v0"

TRACK_MARKET_FIRST = "MARKET_FIRST"
TRACK_SOCIAL_EVENT_FIRST = "SOCIAL_EVENT_FIRST"
TRACK_CONVERGENCE = "CONVERGENCE"
_ALLOWED_TRACKS = {TRACK_MARKET_FIRST, TRACK_SOCIAL_EVENT_FIRST, TRACK_CONVERGENCE}

STAGE_DISCOVERY = "DISCOVERY"
STAGE_PREREGISTERED = "PREREGISTERED"
STAGE_PROSPECTIVE_OPEN = "PROSPECTIVE_OPEN"
STAGE_PROSPECTIVE_CLOSED = "PROSPECTIVE_CLOSED"
_ALLOWED_STAGES = {
    STAGE_DISCOVERY,
    STAGE_PREREGISTERED,
    STAGE_PROSPECTIVE_OPEN,
    STAGE_PROSPECTIVE_CLOSED,
}

VERDICT_NONE = "NONE"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_REJECTED = "REJECTED"
_ALLOWED_VERDICTS = {
    VERDICT_NONE,
    VERDICT_INCONCLUSIVE,
    VERDICT_SUPPORTED,
    VERDICT_REJECTED,
}


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _optional_hash(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    normalized = _required(value, name).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return normalized


@dataclass(frozen=True)
class ResearchHypothesisRecordV0:
    hypothesis_id: str
    track: str
    stage: str
    frozen_at: int
    statement: str
    feature_contract_sha256: str | None = None
    outcome_contract_sha256: str | None = None
    parent_hypothesis_ids: tuple[str, ...] = ()
    supersedes_hypothesis_id: str | None = None
    outcomes_opened: bool = False
    evidence_verdict: str = VERDICT_NONE
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.hypothesis_id, "hypothesis_id")
        _required(self.statement, "statement")
        if self.track not in _ALLOWED_TRACKS:
            raise ValueError(f"unsupported track: {self.track}")
        if self.stage not in _ALLOWED_STAGES:
            raise ValueError(f"unsupported stage: {self.stage}")
        if self.evidence_verdict not in _ALLOWED_VERDICTS:
            raise ValueError(f"unsupported evidence_verdict: {self.evidence_verdict}")
        if not isinstance(self.frozen_at, int) or isinstance(self.frozen_at, bool) or self.frozen_at < 0:
            raise ValueError("frozen_at must be a non-negative integer")
        _optional_hash(self.feature_contract_sha256, "feature_contract_sha256")
        _optional_hash(self.outcome_contract_sha256, "outcome_contract_sha256")
        if len(set(self.parent_hypothesis_ids)) != len(self.parent_hypothesis_ids):
            raise ValueError("parent_hypothesis_ids must be unique")
        for parent in self.parent_hypothesis_ids:
            _required(parent, "parent_hypothesis_id")
        if self.supersedes_hypothesis_id is not None:
            _required(self.supersedes_hypothesis_id, "supersedes_hypothesis_id")
            if self.supersedes_hypothesis_id == self.hypothesis_id:
                raise ValueError("a hypothesis cannot supersede itself")

        if self.stage != STAGE_DISCOVERY and self.feature_contract_sha256 is None:
            raise ValueError("preregistered/prospective hypotheses require feature_contract_sha256")
        if self.stage in {STAGE_PROSPECTIVE_OPEN, STAGE_PROSPECTIVE_CLOSED} and self.outcome_contract_sha256 is None:
            raise ValueError("prospective hypotheses require outcome_contract_sha256")
        if self.stage in {STAGE_DISCOVERY, STAGE_PREREGISTERED} and self.outcomes_opened:
            raise ValueError("discovery/preregistered hypotheses cannot have outcomes_opened=true")
        if self.stage in {STAGE_PROSPECTIVE_OPEN, STAGE_PROSPECTIVE_CLOSED} and not self.outcomes_opened:
            raise ValueError("prospective open/closed hypotheses require outcomes_opened=true")
        if self.stage != STAGE_PROSPECTIVE_CLOSED and self.evidence_verdict != VERDICT_NONE:
            raise ValueError("only closed prospective hypotheses may carry an evidence verdict")
        if self.stage == STAGE_PROSPECTIVE_CLOSED and self.evidence_verdict == VERDICT_NONE:
            raise ValueError("closed prospective hypotheses require an evidence verdict")
        if self.track != TRACK_CONVERGENCE and self.parent_hypothesis_ids:
            raise ValueError("only convergence hypotheses may reference cross-track parents in V0")
        if self.track == TRACK_CONVERGENCE and len(self.parent_hypothesis_ids) < 2:
            raise ValueError("convergence hypotheses require at least two parent hypotheses")


def validate_research_hypothesis_registry_v0(
    records: Iterable[ResearchHypothesisRecordV0],
) -> tuple[ResearchHypothesisRecordV0, ...]:
    """Validate one registry and return its deterministic id-sorted representation."""

    normalized = tuple(records)
    by_id: dict[str, ResearchHypothesisRecordV0] = {}
    for record in normalized:
        if not isinstance(record, ResearchHypothesisRecordV0):
            raise TypeError("registry entries must be ResearchHypothesisRecordV0")
        if record.hypothesis_id in by_id:
            raise ValueError(f"duplicate hypothesis_id: {record.hypothesis_id}")
        by_id[record.hypothesis_id] = record

    for record in normalized:
        if record.supersedes_hypothesis_id is not None:
            parent = by_id.get(record.supersedes_hypothesis_id)
            if parent is None:
                raise ValueError(
                    f"superseded hypothesis not present: {record.supersedes_hypothesis_id}"
                )
            if parent.track != record.track:
                raise ValueError("superseding hypotheses must remain in the same research track")
            if record.frozen_at <= parent.frozen_at:
                raise ValueError("superseding hypothesis must freeze after the superseded record")

        if record.track != TRACK_CONVERGENCE:
            continue

        parents: list[ResearchHypothesisRecordV0] = []
        for parent_id in record.parent_hypothesis_ids:
            parent = by_id.get(parent_id)
            if parent is None:
                raise ValueError(f"convergence parent not present: {parent_id}")
            if parent.frozen_at >= record.frozen_at:
                raise ValueError("convergence must freeze after all parent hypotheses")
            parents.append(parent)

        market_supported = any(
            parent.track == TRACK_MARKET_FIRST
            and parent.stage == STAGE_PROSPECTIVE_CLOSED
            and parent.evidence_verdict == VERDICT_SUPPORTED
            for parent in parents
        )
        social_supported = any(
            parent.track == TRACK_SOCIAL_EVENT_FIRST
            and parent.stage == STAGE_PROSPECTIVE_CLOSED
            and parent.evidence_verdict == VERDICT_SUPPORTED
            for parent in parents
        )
        if not market_supported or not social_supported:
            raise ValueError(
                "convergence requires independent SUPPORTED closed prospective evidence "
                "from both Market-First and Social/Event-First"
            )

    return tuple(sorted(normalized, key=lambda item: item.hypothesis_id))


def research_hypothesis_registry_digest_v0(
    records: Iterable[ResearchHypothesisRecordV0],
) -> str:
    """Return deterministic SHA-256 for a validated registry snapshot."""

    validated = validate_research_hypothesis_registry_v0(records)
    payload = {
        "version": REGISTRY_VERSION,
        "records": [asdict(record) for record in validated],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
