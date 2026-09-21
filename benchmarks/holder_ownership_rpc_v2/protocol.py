from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from benchmarks.holder_ownership_rpc_v2.runtime_enrichment import FEATURE_ID


DEFAULT_PROTOCOL = Path("benchmarks") / "holder_ownership_rpc_v2" / "protocol.frozen.json"
EXPECTED_PROTOCOL_HASH = "9e54b4033ef218f958c2c6386efbcb375077b5e78755c1cd40419c73bc7616b4"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {key: value for key, value in dict(protocol).items() if key != "protocol_hash_sha256"}
    actual = hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != EXPECTED_PROTOCOL_HASH or actual != EXPECTED_PROTOCOL_HASH:
        raise ValueError("holder ownership RPC v2 protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_PROSPECTIVE_DISCOVERY":
        raise ValueError("holder ownership RPC v2 protocol is not preregistered")
    feature = protocol.get("feature_contract") or {}
    if feature.get("primary_feature_id") != FEATURE_ID:
        raise ValueError("holder ownership RPC v2 feature changed")
    if feature.get("expected_direction") != "negative":
        raise ValueError("holder ownership RPC v2 direction changed")
    if feature.get("coverage_scope") != (
        "top 20 token accounts returned by getTokenLargestAccounts only; this is not full-holder HHI"
    ):
        raise ValueError("holder ownership RPC v2 coverage scope changed")
