from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


VERSION = "causal_evidence_guardrails_v0"

# Keys carrying economic outcomes, execution results, or post-decision information
# are not admissible as causal selection evidence. Matching is done on normalized
# key/path components, not values, so legitimate source labels are not censored.
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

# These fields are provider/execution-side rather than frozen market-state
# quantities and are additionally forbidden inside Market-First feature snapshots.
_MARKET_PROVIDER_NORMALIZED_KEYS = {
    "provider",
    "providerid",
    "providername",
    "quote",
    "quotes",
    "route",
    "routes",
    "priceimpact",
    "priceimpactpct",
    "priceimpactpctpoints",
    "providerpriceimpactpctpoints",
    "slippage",
    "slippagebps",
    "entry",
    "entryprice",
    "entryquote",
    "exit",
    "exitprice",
    "exitquote",
}

_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")


def normalize_field_name_v0(name: Any) -> str:
    return "".join(part.lower() for part in _SPLIT_RE.split(str(name)) if part)


def _forbidden_names(extra_forbidden: Iterable[str] = ()) -> set[str]:
    return _FORBIDDEN_NORMALIZED_KEYS | {normalize_field_name_v0(name) for name in extra_forbidden}


def scan_for_forbidden_evidence_fields_v0(
    value: Any,
    *,
    path: str = "root",
    extra_forbidden: Iterable[str] = (),
) -> None:
    forbidden = _forbidden_names(extra_forbidden)

    def visit(node: Any, node_path: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key)
                normalized = normalize_field_name_v0(key)
                if normalized in forbidden:
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
        raise ValueError(f"{path}.evidence_window_seconds must be 5")
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        raise ValueError(f"{path}.features must be an object")
    scan_for_forbidden_evidence_fields_v0(
        features,
        path=f"{path}.features",
        extra_forbidden=_MARKET_PROVIDER_NORMALIZED_KEYS,
    )
