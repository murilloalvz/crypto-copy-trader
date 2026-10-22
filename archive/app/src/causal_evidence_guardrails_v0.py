from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


VERSION = "causal_evidence_guardrails_v0"

# Exact normalized field names that are not admissible as causal evidence.
_FORBIDDEN_NORMALIZED_KEYS = {
    "pnl",
    "pnlusd",
    "realizedpnl",
    "realizedpnlusd",
    "unrealizedpnl",
    "return",
    "returnpct",
    "fixedreturnpct",
    "smartreturnpct",
    "futurereturnpct",
    "outcome",
    "outcomes",
    "label",
    "labels",
    "target",
    "targets",
    "profit",
    "profitusd",
    "loss",
    "lossusd",
    "hindsight",
    "postevent",
    "posteventresult",
    "entryresult",
    "exitresult",
    "fill",
    "fills",
    "fillstatus",
    "landedfill",
    "landedfills",
    "executionresult",
    "executionresults",
    "routepnl",
    "routepaperpnlusd",
    "economicresult",
    "economicresults",
}

# Compound names such as post_event_return_60s must also fail. These fragments
# are intentionally limited to concepts that are unambiguously post-decision or
# economic-result-bearing in this research schema.
_FORBIDDEN_NORMALIZED_FRAGMENTS = (
    "pnl",
    "return",
    "outcome",
    "hindsight",
    "postevent",
    "priceimpact",
    "slippage",
    "landedfill",
    "executionresult",
    "economicresult",
    "realizedprofit",
    "realizedloss",
)

# Provider/execution-side fields are additionally forbidden inside Market-First
# feature snapshots. Values are not inspected; only field names/paths are gated.
_MARKET_PROVIDER_NORMALIZED_KEYS = {
    "provider",
    "providerid",
    "providername",
    "quote",
    "quotes",
    "route",
    "routes",
    "entry",
    "entryprice",
    "entryquote",
    "exit",
    "exitprice",
    "exitquote",
    "fill",
    "fills",
    "fillstatus",
}

_MARKET_PROVIDER_NORMALIZED_FRAGMENTS = (
    "provider",
    "quote",
    "route",
    "priceimpact",
    "slippage",
    "entryprice",
    "exitprice",
    "fillstatus",
)

_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")


def normalize_field_name_v0(name: Any) -> str:
    return "".join(part.lower() for part in _SPLIT_RE.split(str(name)) if part)


def _normalized_extra(extra_forbidden: Iterable[str]) -> tuple[str, ...]:
    return tuple(normalize_field_name_v0(name) for name in extra_forbidden if str(name).strip())


def scan_for_forbidden_evidence_fields_v0(
    value: Any,
    *,
    path: str = "root",
    extra_forbidden: Iterable[str] = (),
    reject_market_provider_fields: bool = False,
) -> None:
    extra = _normalized_extra(extra_forbidden)
    exact = _FORBIDDEN_NORMALIZED_KEYS | set(extra)
    fragments = list(_FORBIDDEN_NORMALIZED_FRAGMENTS) + list(extra)
    if reject_market_provider_fields:
        exact |= _MARKET_PROVIDER_NORMALIZED_KEYS
        fragments.extend(_MARKET_PROVIDER_NORMALIZED_FRAGMENTS)

    def visit(node: Any, node_path: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key)
                normalized = normalize_field_name_v0(key)
                if normalized in exact or any(fragment in normalized for fragment in fragments):
                    raise ValueError(f"future/outcome-bearing field is forbidden in causal evidence: {node_path}.{key}")
                visit(child, f"{node_path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                visit(child, f"{node_path}[{index}]")

    visit(value, path)


def validate_market_feature_snapshot_v0(snapshot: Mapping[str, Any], *, path: str = "feature_snapshot") -> None:
    if not isinstance(snapshot, Mapping):
        raise ValueError(f"{path} must be an object")
    if snapshot.get("complete") is not True:
        raise ValueError(f"{path}.complete must be true")
    if snapshot.get("stratum") != "pump_launch":
        raise ValueError(f"{path}.stratum must be pump_launch")
    if int(snapshot.get("evidence_window_seconds") or 0) != 5:
        raise ValueError(f"{path}.evidence_window_seconds must use the frozen 5-second window (value 5)")
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        raise ValueError(f"{path}.features must be an object")
    scan_for_forbidden_evidence_fields_v0(
        features,
        path=f"{path}.features",
        reject_market_provider_fields=True,
    )
