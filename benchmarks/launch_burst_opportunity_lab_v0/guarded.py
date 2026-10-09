from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_opportunity_lab_v0 import analyze as legacy
from src.causal_evidence_guardrails_v0 import validate_market_feature_snapshot_v0


VERSION = "launch_burst_opportunity_selection_lab_guarded_v0"


def _read_route_input(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "route-input-v2.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"route input must be a JSON object: {path}")
    return payload


def validate_run_causal_features_v0(run_dir: Path) -> dict[str, Any]:
    payload = _read_route_input(run_dir)
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("route-input-v2 episodes must be a list")
    validated = 0
    for index, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            raise ValueError(f"route-input-v2 episode[{index}] must be an object")
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError(f"route-input-v2 episode[{index}] missing feature_snapshot")
        validate_market_feature_snapshot_v0(snapshot, path=f"episodes[{index}].feature_snapshot")
        validated += 1
    return {
        "version": VERSION,
        "route_input": str((Path(run_dir) / "route-input-v2.json").resolve()),
        "episode_count": validated,
        "provider_or_outcome_feature_leakage_rejected": True,
        "frozen_market_snapshot_required": True,
    }


def analyze_run(*, run_dir: Path, contract_path: Path, sniper_policy_path: Path) -> dict[str, Any]:
    guard = validate_run_causal_features_v0(run_dir)
    report = legacy.analyze_run(
        run_dir=run_dir,
        contract_path=contract_path,
        sniper_policy_path=sniper_policy_path,
    )
    report = dict(report)
    report["causal_feature_guardrails"] = guard
    return report


def run_lab(*, run_dirs: list[Path], contract_path: Path, sniper_policy_path: Path, output_path: Path) -> dict[str, Any]:
    guards = [validate_run_causal_features_v0(run_dir) for run_dir in run_dirs]
    report = legacy.run_lab(
        run_dirs=run_dirs,
        contract_path=contract_path,
        sniper_policy_path=sniper_policy_path,
        output_path=output_path,
    )
    report = dict(report)
    report["causal_feature_guardrails"] = {
        "version": VERSION,
        "validated_run_count": len(guards),
        "validated_episode_count": sum(int(item["episode_count"]) for item in guards),
        "provider_or_outcome_feature_leakage_rejected": True,
    }
    return report
