from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.integrated_market_signal_plane_v1.v5_batch_suite import (
    PASS_CLASSIFICATION as V5_BATCH_PASS,
    run_v5_batch_capacity,
)
from benchmarks.v68_signal_plane_bridge_v0.run import (
    PASS_CLASSIFICATION as EPISODE_BRIDGE_PASS,
    run_bridge_audit,
)
import route_research_prospective_flow60_buy_share_holdout_v68 as legacy_v68
from src.signal_plane_forward_cohort_v0 import (
    SUBCOHORT_CAP,
    SUBCOHORT_MIN_DECISIONS,
)


VERSION = "signal_plane_edge_offline_readiness_v0"
PASS_CLASSIFICATION = "PASS_SIGNAL_PLANE_EDGE_OFFLINE_READINESS_V0"
FAIL_CLASSIFICATION = "FAIL_SIGNAL_PLANE_EDGE_OFFLINE_READINESS_V0"

EXPECTED_V68_CONTRACT = {
    "feature": "flow60_buy_share_pct",
    "low_max": 57.1429,
    "mid_max": 65.7143,
    "favorable": "LOW",
    "opposite": "HIGH",
    "primary_horizon_seconds": 900,
    "minimum_support_per_subcohort": 5,
}


def run_offline_edge_readiness(
    *,
    events: int = 10_000,
    seed: int = 68,
    cargo: str = "cargo",
) -> dict:
    v5 = run_v5_batch_capacity(
        events=events,
        seed=seed,
        cargo=cargo,
    )
    bridge = run_bridge_audit(
        events=events,
        seed=seed,
        cargo=cargo,
    )

    actual_contract = {
        "feature": legacy_v68.V68_FEATURE_NAME,
        "low_max": legacy_v68.V68_LOW_MAX,
        "mid_max": legacy_v68.V68_MID_MAX,
        "favorable": legacy_v68.V68_FAVORABLE_GROUP,
        "opposite": legacy_v68.V68_OPPOSITE_GROUP,
        "primary_horizon_seconds": (
            legacy_v68.V68_PRIMARY_HORIZON_SECONDS
        ),
        "minimum_support_per_subcohort": (
            legacy_v68.V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT
        ),
    }

    checks = {
        "v5_batch_offline_capacity_pass": (
            v5.get("classification") == V5_BATCH_PASS
            and all(v5.get("checks", {}).values())
        ),
        "v68_episode_bridge_offline_pass": (
            bridge.get("classification") == EPISODE_BRIDGE_PASS
            and all(bridge.get("checks", {}).values())
        ),
        "frozen_v68_contract_exact": actual_contract == EXPECTED_V68_CONTRACT,
        "subcohort_cap_frozen_40": SUBCOHORT_CAP == 40,
        "subcohort_minimum_frozen_30": SUBCOHORT_MIN_DECISIONS == 30,
        "scientific_thresholds_unchanged": (
            v5.get("scientific_thresholds_modified") is False
            and bridge.get("scientific_thresholds_modified") is False
        ),
        "economic_hypothesis_unchanged": (
            v5.get("economic_hypothesis_modified") is False
            and bridge.get("economic_hypothesis_modified") is False
        ),
    }

    classification = (
        PASS_CLASSIFICATION if all(checks.values()) else FAIL_CLASSIFICATION
    )
    return {
        "type": "signal_plane_edge_offline_readiness_report",
        "version": VERSION,
        "classification": classification,
        "authorization": "offline_systems_only_no_live_no_v68_fresh",
        "events": events,
        "seed": seed,
        "v5_batch": {
            "classification": v5.get("classification"),
            "throughput": v5.get("throughput"),
            "trigger_parity": v5.get("trigger_parity"),
            "rust_batch_roundtrip": v5.get("rust_batch_roundtrip"),
            "rust_batch_internal_service": (
                v5.get("rust_batch_internal_service")
            ),
            "checks": v5.get("checks"),
        },
        "episode_bridge": {
            "classification": bridge.get("classification"),
            "rust_python_parity": bridge.get("rust_python_parity"),
            "episode_bridge": bridge.get("episode_bridge"),
            "checks": bridge.get("checks"),
        },
        "v68_contract": actual_contract,
        "cohort_contract": {
            "cap": SUBCOHORT_CAP,
            "minimum_decisions": SUBCOHORT_MIN_DECISIONS,
            "horizons_seconds": [300, 900, 3600],
            "research_notional_usd": 25.0,
            "research_slippage_bps": 100,
            "provider_start_pacing_ms": {
                "hazard": 650,
                "entry": 1000,
                "exit": 250,
            },
        },
        "checks": checks,
        "interpretation": (
            "PASS means the V5 batched Rust kernel, frozen episode identity "
            "bridge and V68/cohort contracts are ready for live systems "
            "promotion testing. It does not establish live sustained capacity "
            "or economic edge."
            if classification == PASS_CLASSIFICATION
            else "Live/economic testing remains blocked by an offline readiness failure."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-command offline readiness gate for the Signal Plane -> V68 "
            "edge path. No provider/network/fresh economic acquisition."
        )
    )
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/signal_plane_edge_offline_readiness_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = run_offline_edge_readiness(
        events=args.events,
        seed=args.seed,
        cargo=args.cargo,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
