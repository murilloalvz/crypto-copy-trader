from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    FIX_VERSION,
    JUPITER_SWAP_V2_DOC,
    patched_price_impact_semantics,
)
from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import run_smart_ladder_25
from benchmarks.launch_burst_prospective_route_paper_v2.run import run_route_paper_v2

DEFAULT_CONTRACT = sim.DEFAULT_CONTRACT
DEFAULT_POLICY = Path(__file__).with_name("smart_ladder_25_policy_v0.frozen.json")


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _entry_impact_categories(result: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in result.get("decisions") or []:
        if not row.get("admitted"):
            continue
        quote = row.get("entry_quote") or {}
        impact = quote.get("provider_price_impact_pct_points")
        if impact is None:
            counts["NONE"] += 1
            continue
        try:
            value = float(impact)
        except (TypeError, ValueError):
            counts["INVALID"] += 1
            continue
        if not math.isfinite(value):
            counts["NONFINITE"] += 1
        elif value < 0:
            counts["NEGATIVE"] += 1
        elif value <= 2:
            counts["WITHIN_0_TO_2"] += 1
        else:
            counts["OVER_2"] += 1
    return dict(counts)


def _status_counts(result: dict[str, Any]) -> dict[str, int]:
    return dict(Counter(str(row.get("status")) for row in result.get("decisions") or [] if row.get("admitted")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline replay of Launch Burst artifacts with corrected Jupiter Swap V2 negative price-impact semantics")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    input_path = run_dir / "route-input-v2.json"
    original_route_path = run_dir / "route-result-v2.json"
    market_paths_path = run_dir / "market-paths-smart-ladder-25-v0.json"
    corrected_route_path = run_dir / "route-result-v2-price-impact-semantics-fix-v0.json"
    corrected_smart_path = run_dir / "smart-ladder-25-result-price-impact-semantics-fix-v0.json"
    replay_report_path = run_dir / "price-impact-semantics-fix-replay-v0.json"

    for path in (input_path, original_route_path, market_paths_path):
        if not path.exists():
            raise FileNotFoundError(path)

    original_route = _read(original_route_path)
    contract = _read(args.contract)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    if original_route.get("contract_hash_sha256") != route_hash:
        raise ValueError("original route result contract hash mismatch")

    with patched_price_impact_semantics():
        corrected_route = run_route_paper_v2(
            contract_path=args.contract,
            input_path=input_path,
            output_path=corrected_route_path,
        )
        corrected_smart = run_smart_ladder_25(
            contract_path=args.contract,
            policy_path=args.policy,
            route_result_path=corrected_route_path,
            market_paths_path=market_paths_path,
            output_path=corrected_smart_path,
        )

    report = {
        "type": "launch_burst_price_impact_semantics_fix_replay_v0",
        "version": FIX_VERSION,
        "classification": "PASS_LAUNCH_BURST_PRICE_IMPACT_SEMANTICS_FIX_REPLAY_V0",
        "contract_hash_sha256": route_hash,
        "jupiter_swap_v2_documentation": JUPITER_SWAP_V2_DOC,
        "implementation_fix": {
            "old_behavior": "reject None, non-finite, and negative provider priceImpact as unavailable",
            "corrected_behavior": "reject only None/non-finite as unavailable; accept any finite priceImpact <= frozen upper bound; reject only values above frozen upper bound",
            "frozen_contract_changed": False,
            "market_data_recollected": False,
            "network_calls_performed": False,
            "original_artifacts_overwritten": False,
        },
        "original": {
            "status_counts_admitted": _status_counts(original_route),
            "entry_price_impact_categories": _entry_impact_categories(original_route),
        },
        "corrected": {
            "status_counts_admitted": _status_counts(corrected_route),
            "entry_price_impact_categories": _entry_impact_categories(corrected_route),
            "paired_trade_count": int(corrected_smart.get("paired_trade_count") or 0),
            "fixed_60s": corrected_smart.get("fixed_60s"),
            "smart_ladder_25": corrected_smart.get("smart_ladder_25"),
            "smart_minus_fixed_total_pnl_usd": corrected_smart.get("smart_minus_fixed_total_pnl_usd"),
            "threshold_hit_counts": corrected_smart.get("threshold_hit_counts"),
            "runner_exit_reason_counts": corrected_smart.get("runner_exit_reason_counts"),
        },
        "artifacts": {
            "input_reused": str(input_path),
            "market_paths_reused": str(market_paths_path),
            "original_route_result_preserved": str(original_route_path),
            "corrected_route_result": str(corrected_route_path),
            "corrected_smart_ladder_result": str(corrected_smart_path),
            "replay_report": str(replay_report_path),
        },
        "guardrails": {
            "official_v4_funded_taker_gate_opened": False,
            "official_v4_economic_verdict_changed": False,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
            "same_causal_capture_reused": True,
            "same_selector_and_threshold_reused": True,
            "same_costs_reused": True,
            "same_smart_ladder_policy_reused": True,
        },
    }
    _write(replay_report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
