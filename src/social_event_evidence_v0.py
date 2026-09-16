from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "social_event_evidence_v0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _entity_keys(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("entity_keys must be a list or tuple")
    return tuple(sorted({_required_text(item, "entity_keys item") for item in value}))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_social_event_evidence_key_v0(
    *,
    source_kind: str,
    source_key: str,
    source_event_id: str,
) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "source_kind": _required_text(source_kind, "source_kind"),
        "source_key": _required_text(source_key, "source_key"),
        "source_event_id": _required_text(source_event_id, "source_event_id"),
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"sev0:{digest}"


@dataclass(frozen=True)
class SocialEventEvidenceV0:
    evidence_key: str
    source_kind: str
    source_key: str
    source_event_id: str
    event_kind: str
    observed_wall_ns: int
    token_mapping_observed_wall_ns: int | None = None
    published_at_ns: int | None = None
    actor_key: str | None = None
    token_mint: str | None = None
    content_fingerprint_sha256: str | None = None
    entity_keys: tuple[str, ...] = ()

    @property
    def causal_available_wall_ns(self) -> int:
        mapped = self.token_mapping_observed_wall_ns
        return max(self.observed_wall_ns, mapped) if mapped is not None else self.observed_wall_ns


def social_event_evidence_from_mapping_v0(row: Mapping[str, Any]) -> SocialEventEvidenceV0:
    if row.get("schema_version") not in (None, SCHEMA_VERSION):
        raise ValueError("unsupported social/event evidence schema_version")

    source_kind = _required_text(row.get("source_kind"), "source_kind")
    source_key = _required_text(row.get("source_key"), "source_key")
    source_event_id = _required_text(row.get("source_event_id"), "source_event_id")
    event_kind = _required_text(row.get("event_kind"), "event_kind")
    observed_wall_ns = _positive_int(row.get("observed_wall_ns"), "observed_wall_ns")
    token_mapping_observed_wall_ns = _optional_positive_int(
        row.get("token_mapping_observed_wall_ns"), "token_mapping_observed_wall_ns"
    )
    published_at_ns = _optional_positive_int(row.get("published_at_ns"), "published_at_ns")
    actor_key = _optional_text(row.get("actor_key"), "actor_key")
    token_mint = _optional_text(row.get("token_mint"), "token_mint")
    entity_keys = _entity_keys(row.get("entity_keys"))

    content_hash = row.get("content_fingerprint_sha256")
    if content_hash is not None:
        content_hash = _required_text(content_hash, "content_fingerprint_sha256").lower()
        if _SHA256_RE.fullmatch(content_hash) is None:
            raise ValueError("content_fingerprint_sha256 must be 64 lowercase hexadecimal characters")

    expected_key = make_social_event_evidence_key_v0(
        source_kind=source_kind,
        source_key=source_key,
        source_event_id=source_event_id,
    )
    supplied_key = row.get("evidence_key")
    if supplied_key is not None and _required_text(supplied_key, "evidence_key") != expected_key:
        raise ValueError("evidence_key does not match deterministic social/event identity")

    if token_mint is not None and token_mapping_observed_wall_ns is None:
        # Direct token-specific sources may know the token at ingestion time. In that case
        # the source observation itself is the causal token-mapping clock.
        token_mapping_observed_wall_ns = observed_wall_ns

    return SocialEventEvidenceV0(
        evidence_key=expected_key,
        source_kind=source_kind,
        source_key=source_key,
        source_event_id=source_event_id,
        event_kind=event_kind,
        observed_wall_ns=observed_wall_ns,
        token_mapping_observed_wall_ns=token_mapping_observed_wall_ns,
        published_at_ns=published_at_ns,
        actor_key=actor_key,
        token_mint=token_mint,
        content_fingerprint_sha256=content_hash,
        entity_keys=entity_keys,
    )


def social_event_evidence_to_dict_v0(item: SocialEventEvidenceV0) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_key": item.evidence_key,
        "source_kind": item.source_kind,
        "source_key": item.source_key,
        "source_event_id": item.source_event_id,
        "event_kind": item.event_kind,
        "observed_wall_ns": item.observed_wall_ns,
        "token_mapping_observed_wall_ns": item.token_mapping_observed_wall_ns,
        "causal_available_wall_ns": item.causal_available_wall_ns,
        "published_at_ns": item.published_at_ns,
        "actor_key": item.actor_key,
        "token_mint": item.token_mint,
        "content_fingerprint_sha256": item.content_fingerprint_sha256,
        "entity_keys": list(item.entity_keys),
    }
