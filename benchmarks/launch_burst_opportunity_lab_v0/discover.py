from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_opportunity_lab_v0.analyze import (
    DEFAULT_CONTRACT,
    DEFAULT_SNIPER_POLICY,
    analyze_run,
    run_lab,
)


def discover_compatible_runs(
    *,
    artifacts_root: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    sniper_policy_path: Path = DEFAULT_SNIPER_POLICY,
) -> dict[str, Any]:
    root = Path(artifacts_root)
    if not root.is_dir():
        raise ValueError(f"artifacts root not found: {root}")
    candidates = sorted({path.parent for path in root.rglob("route-input-v2.json")})
    compatible: list[Path] = []
    rejected: list[dict[str, str]] = []
    for run_dir in candidates:
        try:
            analyze_run(
                run_dir=run_dir,
                contract_path=contract_path,
                sniper_policy_path=sniper_policy_path,
            )
            compatible.append(run_dir)
        except Exception as exc:
            rejected.append({"run_dir": str(run_dir.resolve()), "reason": f"{type(exc).__name__}:{exc}"})
    compatible.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return {
        "artifacts_root": str(root.resolve()),
        "candidate_count": len(candidates),
        "compatible_count": len(compatible),
        "compatible_run_dirs": [str(path.resolve()) for path in compatible],
        "rejected": rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover compatible local Launch Burst runs and analyze them offline")
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--sniper-policy", type=Path, default=DEFAULT_SNIPER_POLICY)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("artifacts/opportunity-selection-lab-v0.json"))
    args = parser.parse_args()
    try:
        discovery = discover_compatible_runs(
            artifacts_root=args.artifacts_root,
            contract_path=args.contract,
            sniper_policy_path=args.sniper_policy,
        )
        if args.discover_only:
            print(json.dumps(discovery, indent=2, sort_keys=True))
            return 0
        limit = max(1, int(args.limit))
        selected = [Path(path) for path in discovery["compatible_run_dirs"][:limit]]
        if not selected:
            raise ValueError("no compatible run directories discovered")
        report = run_lab(
            run_dirs=selected,
            contract_path=args.contract,
            sniper_policy_path=args.sniper_policy,
            output_path=args.output,
        )
        compact = {
            "discovery": discovery,
            "analysis": {
                "classification": report["classification"],
                "run_count": report["run_count"],
                "replicated_direction_priority_features": report["replicated_direction_priority_features"][:15],
                "output_path": report["output_path"],
            },
        }
        print(json.dumps(compact, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_LAUNCH_BURST_OPPORTUNITY_DISCOVERY_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
