from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping


VERSION = "opportunity_edge_registry_v0"
DEFAULT_REGISTRY_PATH = (
    Path("benchmarks") / "launch_burst_opportunity_lab_v0" / "edge_registry_v0.json"
)

_ALLOWED_PLANES = {"MARKET_FIRST", "SOCIAL_EVENT_FIRST", "EXECUTION", "OUTCOME_ONLY"}
_ALLOWED_STATUSES = {"AVAILABLE", "DERIVABLE", "NEEDS_COLLECTION", "FORBIDDEN_AS_SELECTOR"}
_ALLOWED_ROLES = {
    "PRE_ENTRY_SELECTOR_CANDIDATE",
    "SAFETY_GATE_CANDIDATE",
    "EXECUTION_ADMISSION",
    "RESEARCH_ONLY",
    "OUTCOME_ONLY",
}
_ALLOWED_EVIDENCE_LEVELS = {
    "L0_EXTERNAL_HEURISTIC",
    "L1_CAUSALLY_MEASURABLE",
    "L2_RETROSPECTIVE_ASSOCIATION",
    "L3_PREREGISTERED_PROSPECTIVE_SCREENING",
    "L4_INDEPENDENT_PROSPECTIVE_REPLICATION",
    "L5_LANDED_EXECUTION_ECONOMICS",
}
_REQUIRED_SIGNAL_FIELDS = {
    "signal_id",
    "family",
    "definition",
    "plane",
    "causal_source_time",
    "eligible_pre_entry",
    "current_status",
    "selector_role",
    "coverage_requirement",
    "adversarial_risk",
    "evidence_level",
    "research_stage",
    "promotion_gate",
    "notes",
}

# These tokens are deliberately conservative. They prevent an outcome-derived
# quantity from being accidentally marked as a causal pre-entry selector merely
# because it was added to the research registry under a new name.
_OUTCOME_NAME_RE = re.compile(
    r"(?:^|[._-])(future|pnl|profit|loss|outcome|realized|postevent|maxfuture|return(?:pct)?)(?:$|[._-])",
    re.IGNORECASE,
)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("edge registry must be a JSON object")
    return payload


def validate_edge_registry_v0(registry: Mapping[str, Any]) -> None:
    if not isinstance(registry, Mapping):
        raise ValueError("edge registry must be an object")
    if registry.get("schema") != VERSION:
        raise ValueError(f"edge registry schema must be {VERSION}")
    if registry.get("status") != "RESEARCH_REGISTRY_ONLY":
        raise ValueError("edge registry must remain RESEARCH_REGISTRY_ONLY")
    if registry.get("selector_policy_effect") != "NO_POLICY_CHANGE":
        raise ValueError("edge registry cannot change selector policy")
    if registry.get("weighted_score_policy") != "NONE_V0":
        raise ValueError("weighted composite scoring is forbidden in registry v0")

    planes = registry.get("research_planes")
    if not isinstance(planes, Mapping):
        raise ValueError("research_planes must be an object")
    if planes.get("market_first") != "INDEPENDENT":
        raise ValueError("Market-First must remain independent")
    if planes.get("social_event_first") != "INDEPENDENT":
        raise ValueError("Social/Event-First must remain independent")
    if planes.get("convergence") != "SEPARATE_PREREGISTRATION_REQUIRED":
        raise ValueError("convergence requires separate preregistration")

    signals = registry.get("signals")
    if not isinstance(signals, list) or not signals:
        raise ValueError("signals must be a non-empty list")

    seen: set[str] = set()
    for index, signal in enumerate(signals):
        path = f"signals[{index}]"
        if not isinstance(signal, Mapping):
            raise ValueError(f"{path} must be an object")
        missing = sorted(_REQUIRED_SIGNAL_FIELDS - set(signal))
        if missing:
            raise ValueError(f"{path} missing fields: {', '.join(missing)}")

        signal_id = _required_text(signal.get("signal_id"), f"{path}.signal_id")
        if signal_id in seen:
            raise ValueError(f"duplicate signal_id: {signal_id}")
        seen.add(signal_id)

        plane = _required_text(signal.get("plane"), f"{path}.plane")
        status = _required_text(signal.get("current_status"), f"{path}.current_status")
        role = _required_text(signal.get("selector_role"), f"{path}.selector_role")
        evidence_level = _required_text(signal.get("evidence_level"), f"{path}.evidence_level")
        eligible = signal.get("eligible_pre_entry")
        if plane not in _ALLOWED_PLANES:
            raise ValueError(f"{path}.plane unsupported: {plane}")
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"{path}.current_status unsupported: {status}")
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"{path}.selector_role unsupported: {role}")
        if evidence_level not in _ALLOWED_EVIDENCE_LEVELS:
            raise ValueError(f"{path}.evidence_level unsupported: {evidence_level}")
        if not isinstance(eligible, bool):
            raise ValueError(f"{path}.eligible_pre_entry must be boolean")

        for field in _REQUIRED_SIGNAL_FIELDS - {
            "eligible_pre_entry", "plane", "current_status", "selector_role", "evidence_level"
        }:
            _required_text(signal.get(field), f"{path}.{field}")

        if plane == "OUTCOME_ONLY":
            if eligible:
                raise ValueError(f"{path}: outcome-only signal cannot be pre-entry eligible")
            if status != "FORBIDDEN_AS_SELECTOR" or role != "OUTCOME_ONLY":
                raise ValueError(f"{path}: outcome-only signal must be forbidden and OUTCOME_ONLY")

        if plane == "EXECUTION":
            if eligible:
                raise ValueError(f"{path}: execution signal cannot enter opportunity selector")
            if status != "FORBIDDEN_AS_SELECTOR" or role != "EXECUTION_ADMISSION":
                raise ValueError(f"{path}: execution signal must be isolated as EXECUTION_ADMISSION")

        if plane in {"MARKET_FIRST", "SOCIAL_EVENT_FIRST"} and role == "EXECUTION_ADMISSION":
            raise ValueError(f"{path}: research-plane signal cannot be an execution admission field")

        if eligible and status == "FORBIDDEN_AS_SELECTOR":
            raise ValueError(f"{path}: forbidden selector signal cannot be pre-entry eligible")

        if eligible and _OUTCOME_NAME_RE.search(signal_id):
            raise ValueError(f"{path}: outcome-bearing signal name cannot be pre-entry eligible")

        causal_source = _required_text(signal.get("causal_source_time"), f"{path}.causal_source_time").lower()
        if eligible and "published" in causal_source:
            raise ValueError(f"{path}: published_at metadata cannot define causal availability")


def load_edge_registry_v0(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    registry = _load_json(Path(path))
    validate_edge_registry_v0(registry)
    return registry


def selector_candidates_v0(
    registry: Mapping[str, Any], *, plane: str | None = None
) -> list[dict[str, Any]]:
    validate_edge_registry_v0(registry)
    if plane is not None and plane not in {"MARKET_FIRST", "SOCIAL_EVENT_FIRST"}:
        raise ValueError("selector candidate plane must be MARKET_FIRST or SOCIAL_EVENT_FIRST")
    roles = {"PRE_ENTRY_SELECTOR_CANDIDATE", "SAFETY_GATE_CANDIDATE"}
    rows: list[dict[str, Any]] = []
    for raw in registry["signals"]:
        signal = dict(raw)
        if signal["eligible_pre_entry"] is not True:
            continue
        if signal["selector_role"] not in roles:
            continue
        if plane is not None and signal["plane"] != plane:
            continue
        rows.append(signal)
    return rows
