from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from src.causal_evidence_guardrails_v0 import validate_market_feature_snapshot_v0


VERSION = "market_signal_snapshot_v0"
PASS = "PASS_MARKET_SIGNAL_SNAPSHOT_V0"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def market_signal_snapshot_from_route_episode_v0(episode: Mapping[str, Any]) -> dict[str, Any]:
    episode_key = str(episode.get("episode_key") or "").strip()
    token_mint = str(episode.get("token_mint") or "").strip()
    snapshot = episode.get("feature_snapshot")
    if not episode_key or not token_mint or not isinstance(snapshot, Mapping):
        raise ValueError("route episode must include episode_key, token_mint and feature_snapshot")

    validate_market_feature_snapshot_v0(snapshot, path=f"episode[{episode_key}].feature_snapshot")

    anchor = snapshot.get("observed_t0_wall_ns")
    cutoff = snapshot.get("decision_cutoff_wall_ns")
    if not isinstance(anchor, int) or isinstance(anchor, bool) or anchor <= 0:
        raise ValueError("feature snapshot has no valid observed_t0_wall_ns")
    if not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff < anchor:
        raise ValueError("feature snapshot has no valid decision_cutoff_wall_ns")
    features = snapshot.get("features")
    assert isinstance(features, Mapping)

    return {
        "type": VERSION,
        "classification": PASS,
        "episode_key": episode_key,
        "token_mint": token_mint,
        "market_anchor_wall_ns": anchor,
        "decision_cutoff_wall_ns": cutoff,
        "snapshot": {
            "stratum": "pump_launch",
            "complete": True,
            "evidence_window_seconds": 5,
            "decision_as_of": snapshot.get("decision_as_of"),
            "features": dict(features),
        },
        "guardrails": {
            "source_is_frozen_pre_provider_feature_snapshot": True,
            "provider_route_outcomes_not_read": True,
            "market_outcomes_not_read": True,
            "recursive_feature_leakage_scan_passed": True,
            "no_selector_added": True,
            "no_trade_recommendation": True,
        },
    }


def export_market_signal_snapshot_v0(
    *,
    route_input_path: Path,
    episode_key: str | None = None,
    token_mint: str | None = None,
) -> dict[str, Any]:
    payload = _read_json(route_input_path)
    if payload.get("type") != "launch_burst_prospective_route_input_v2":
        raise ValueError("unsupported route input type")
    if payload.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze features before provider quotes")
    episode_key = episode_key.strip() if isinstance(episode_key, str) and episode_key.strip() else None
    token_mint = token_mint.strip() if isinstance(token_mint, str) and token_mint.strip() else None
    if (episode_key is None) == (token_mint is None):
        raise ValueError("provide exactly one of episode_key or token_mint")

    matches = []
    for episode in payload.get("episodes") or []:
        if not isinstance(episode, Mapping):
            continue
        if episode_key is not None and str(episode.get("episode_key") or "") == episode_key:
            matches.append(episode)
        elif token_mint is not None and str(episode.get("token_mint") or "") == token_mint:
            matches.append(episode)
    if not matches:
        raise ValueError("no matching route episode found")
    if len(matches) != 1:
        raise ValueError("selector matched multiple route episodes; use episode_key")
    return market_signal_snapshot_from_route_episode_v0(matches[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an outcome-blind Market-First snapshot from an existing route-input-v2 artifact")
    parser.add_argument("--route-input", type=Path, required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--episode-key")
    selector.add_argument("--token-mint")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = export_market_signal_snapshot_v0(
            route_input_path=args.route_input,
            episode_key=args.episode_key,
            token_mint=args.token_mint,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_SIGNAL_SNAPSHOT_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
