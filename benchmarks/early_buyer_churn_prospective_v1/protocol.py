from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_PROTOCOL = (
    Path("benchmarks")
    / "early_buyer_churn_prospective_v1"
    / "protocol.frozen.json"
)
EXPECTED_PROTOCOL_HASH = "0aaf83c2644a6d5eab63034cb09bd403edf87791a0de47a597361a698eba9827"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {
        key: value
        for key, value in dict(protocol).items()
        if key != "protocol_hash_sha256"
    }
    actual = hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != EXPECTED_PROTOCOL_HASH or actual != EXPECTED_PROTOCOL_HASH:
        raise ValueError("early buyer churn prospective v1 protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_PROSPECTIVE_CONFIRMATION":
        raise ValueError("early buyer churn prospective v1 status changed")
    feature = protocol.get("feature_contract") or {}
    if (
        feature.get("primary_feature_id")
        != "mf_early_buyer_roundtrip_sellback_fraction_t0_5s"
    ):
        raise ValueError("early buyer churn prospective feature changed")
    if feature.get("expected_direction") != "negative":
        raise ValueError("early buyer churn prospective direction changed")
    if feature.get("feature_redefinition_allowed") is not False:
        raise ValueError("early buyer churn prospective feature redefinition guard changed")
