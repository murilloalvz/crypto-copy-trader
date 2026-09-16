from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


VERSION = "convergence_evidence_join_v0"
PASS = "PASS_CONVERGENCE_EVIDENCE_JOIN_V0"
DISALLOWED_OUTCOME_KEYS = {
    "pnl",
    "pnl_usd",
    "realized_pnl",
    "route_paper_pnl_usd",
    "fixed_return_pct",
    "smart_return_pct",
    "future_return_pct",
    "outcome",
    "label",
    "target",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _scan_for_outcome_keys(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in DISALLOWED_OUTCOME_KEYS:
                raise ValueError(f"outcome-bearing key is forbidden in convergence evidence: {path}.{key}")
            _scan_for_outcome_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_outcome_keys(child, path=f"{path}[{index}]")


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _required_positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_market_signal_snapshot_v0(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") != "market_signal_snapshot_v0":
        raise ValueError("market input must have type=market_signal_snapshot_v0")
    _scan_for_outcome_keys(payload, path="market")
    token_mint = _required_text(payload.get("token_mint"), "market.token_mint")
    anchor = _required_positive_int(payload.get("market_anchor_wall_ns"), "market.market_anchor_wall_ns")
    cutoff = _required_positive_int(payload.get("decision_cutoff_wall_ns"), "market.decision_cutoff_wall_ns")
    if cutoff < anchor:
        raise ValueError("market decision cutoff must be >= market anchor")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("market.snapshot must be an object")
    return {
        "type": "market_signal_snapshot_v0",
        "token_mint": token_mint,
        "market_anchor_wall_ns": anchor,
        "decision_cutoff_wall_ns": cutoff,
        "snapshot": dict(snapshot),
    }


def validate_social_event_snapshot_v0(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("type") != "social_event_snapshot" or payload.get("version") != "social_event_snapshot_v0":
        raise ValueError("unsupported Social/Event snapshot")
    _scan_for_outcome_keys(payload, path="social")
    token_mint = _required_text(payload.get("token_mint"), "social.token_mint")
    anchor = _required_positive_int(payload.get("market_anchor_wall_ns"), "social.market_anchor_wall_ns")
    cutoff = _required_positive_int(payload.get("decision_cutoff_wall_ns"), "social.decision_cutoff_wall_ns")
    if payload.get("causal_time_field") != "causal_available_wall_ns":
        raise ValueError("Social/Event snapshot does not declare the expected causal clock")
    features = payload.get("features")
    if not isinstance(features, Mapping):
        raise ValueError("social.features must be an object")
    return {
        "type": "social_event_snapshot",
        "version": "social_event_snapshot_v0",
        "token_mint": token_mint,
        "market_anchor_wall_ns": anchor,
        "decision_cutoff_wall_ns": cutoff,
        "features": dict(features),
        "evidence_keys": list(payload.get("evidence_keys") or []),
    }


def join_market_social_evidence_v0(
    *,
    market_snapshot: Mapping[str, Any],
    social_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    market = validate_market_signal_snapshot_v0(market_snapshot)
    social = validate_social_event_snapshot_v0(social_snapshot)
    if market["token_mint"] != social["token_mint"]:
        raise ValueError("market/social token_mint mismatch")
    if market["market_anchor_wall_ns"] != social["market_anchor_wall_ns"]:
        raise ValueError("market/social market_anchor_wall_ns mismatch")
    if market["decision_cutoff_wall_ns"] != social["decision_cutoff_wall_ns"]:
        raise ValueError("market/social decision_cutoff_wall_ns mismatch")

    return {
        "type": "convergence_evidence_join",
        "version": VERSION,
        "classification": PASS,
        "status": "EVIDENCE_JOIN_ONLY_NO_SELECTOR",
        "token_mint": market["token_mint"],
        "market_anchor_wall_ns": market["market_anchor_wall_ns"],
        "decision_cutoff_wall_ns": market["decision_cutoff_wall_ns"],
        "market_first": market,
        "social_event_first": social,
        "guardrails": {
            "outcome_blind": True,
            "market_and_social_tracks_remain_independently_testable": True,
            "convergence_edge_not_inferred": True,
            "no_selector": True,
            "no_ranking": True,
            "no_trade_recommendation": True,
            "no_threshold_search": True,
            "fresh_preregistration_required_before_any_convergence_selection_rule": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Join independent Market-First and Social/Event-First evidence without outcomes")
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--social", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = join_market_social_evidence_v0(
            market_snapshot=_read_json(args.market),
            social_snapshot=_read_json(args.social),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_CONVERGENCE_EVIDENCE_JOIN_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
