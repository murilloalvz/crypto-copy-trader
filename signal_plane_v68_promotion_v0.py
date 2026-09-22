from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


VERSION = "v68_signal_plane_promotion_v0"
PASS_CLASSIFICATION = "PASS_V68_SIGNAL_PLANE_PROMOTION_V0"
FAIL_CLASSIFICATION = "FAIL_V68_SIGNAL_PLANE_PROMOTION_V0"

REQUIRED_LIVE_VERSION = "rust_signal_plane_live_shadow_v5_signal_batch"
REQUIRED_OFFLINE_CAPACITY = "PASS_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY_V0"
REQUIRED_OFFLINE_BRIDGE = "PASS_V68_SIGNAL_PLANE_BRIDGE_V0"
REQUIRED_LIVE_CLASSIFICATION = "PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V5_SIGNAL_BATCH"
REQUIRED_ROUTE_BRIDGE = "PASS_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0"

SMOKE_MIN_DURATION_SECONDS = 120.0
SOAK_MIN_DURATION_SECONDS = 1800.0
LIVE_SOURCE_P95_MAX_MS = 5000.0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git rev-parse HEAD failed: "
            + completed.stderr.strip()
        )
    head = completed.stdout.strip()
    if len(head) != 40:
        raise RuntimeError(f"unexpected git HEAD: {head!r}")
    return head


def _all_true(mapping: Any) -> bool:
    return (
        isinstance(mapping, dict)
        and bool(mapping)
        and all(value is True for value in mapping.values())
    )


def _live_checks(
    report: dict[str, Any],
    *,
    min_duration_seconds: float,
) -> dict[str, bool]:
    transport = report.get("transport") or {}
    latency = report.get("latency") or {}
    rust_source = latency.get("rust_source_to_signal") or {}
    trigger = report.get("trigger_parity") or {}
    return {
        "version_v5": report.get("version") == REQUIRED_LIVE_VERSION,
        "classification_pass": (
            report.get("classification") == REQUIRED_LIVE_CLASSIFICATION
        ),
        "duration_minimum": (
            float(report.get("duration_seconds", 0.0))
            >= min_duration_seconds
        ),
        "all_live_gates_true": _all_true(report.get("gates")),
        "errors_empty": report.get("errors") == [],
        "reader_errors_empty": transport.get("reader_errors") == [],
        "zero_pump_drops": int(transport.get("pump_ingress_drops", -1)) == 0,
        "zero_pumpswap_drops": (
            int(transport.get("pumpswap_ingress_drops", -1)) == 0
        ),
        "ingress_accounting_exact": (
            int(transport.get("enqueued_total", -1))
            == int(transport.get("consumed_total", -2))
        ),
        "ingress_drained": int(transport.get("queue_depth_at_report", -1)) == 0,
        "queue_bounded_below_capacity": (
            0 <= int(transport.get("queue_high_water", -1))
            < int(transport.get("queue_capacity", 0))
        ),
        "trigger_parity_100": (
            float(trigger.get("parity_pct", -1.0)) == 100.0
            and int(trigger.get("mismatches", -1)) == 0
            and int(trigger.get("decision_points", 0)) > 0
        ),
        "source_p95_le_5s": (
            0.0
            <= float(rust_source.get("p95_ms", -1.0))
            <= LIVE_SOURCE_P95_MAX_MS
        ),
    }


def build_promotion_report(
    *,
    offline_capacity_path: Path,
    offline_bridge_path: Path,
    live_smoke_path: Path,
    live_soak_path: Path,
    route_bridge_path: Path,
) -> dict[str, Any]:
    paths = {
        "offline_capacity": Path(offline_capacity_path),
        "offline_bridge": Path(offline_bridge_path),
        "live_smoke": Path(live_smoke_path),
        "live_soak": Path(live_soak_path),
        "route_bridge": Path(route_bridge_path),
    }
    reports = {name: _read_json(path) for name, path in paths.items()}

    offline_capacity = reports["offline_capacity"]
    offline_bridge = reports["offline_bridge"]
    live_smoke = reports["live_smoke"]
    live_soak = reports["live_soak"]
    route_bridge = reports["route_bridge"]

    route_checks = route_bridge.get("checks")
    checks: dict[str, bool] = {
        "offline_capacity_pass": (
            offline_capacity.get("classification")
            == REQUIRED_OFFLINE_CAPACITY
            and _all_true(offline_capacity.get("checks"))
        ),
        "offline_bridge_pass": (
            offline_bridge.get("classification")
            == REQUIRED_OFFLINE_BRIDGE
            and _all_true(offline_bridge.get("checks"))
        ),
        **{
            f"smoke_{name}": passed
            for name, passed in _live_checks(
                live_smoke,
                min_duration_seconds=SMOKE_MIN_DURATION_SECONDS,
            ).items()
        },
        **{
            f"soak_{name}": passed
            for name, passed in _live_checks(
                live_soak,
                min_duration_seconds=SOAK_MIN_DURATION_SECONDS,
            ).items()
        },
        "route_bridge_pass": (
            route_bridge.get("classification") == REQUIRED_ROUTE_BRIDGE
        ),
        "route_bridge_checks_all_true": _all_true(route_checks),
        "route_bridge_not_v68_fresh_key": (
            "v68-flow60-fresh"
            not in str(route_bridge.get("run_key", "")).lower()
        ),
        "route_bridge_has_decisions": (
            int(
                (route_bridge.get("downstream") or {}).get(
                    "research_decisions_frozen",
                    0,
                )
            )
            > 0
        ),
    }

    head = _git_head()
    classification = (
        PASS_CLASSIFICATION if all(checks.values()) else FAIL_CLASSIFICATION
    )
    return {
        "type": "v68_signal_plane_promotion_report",
        "version": VERSION,
        "classification": classification,
        "git_head": head,
        "authorization": (
            "authorizes_v68_signal_plane_release_only_when_classification_pass"
        ),
        "evidence": {
            name: {
                "path": str(path),
                "sha256": _sha256(path),
                "type": reports[name].get("type"),
                "version": reports[name].get("version"),
                "classification": reports[name].get("classification"),
            }
            for name, path in paths.items()
        },
        "checks": checks,
        "frozen_thresholds": {
            "smoke_min_duration_seconds": SMOKE_MIN_DURATION_SECONDS,
            "soak_min_duration_seconds": SOAK_MIN_DURATION_SECONDS,
            "live_source_p95_max_ms": LIVE_SOURCE_P95_MAX_MS,
        },
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "interpretation": (
            "PASS authorizes only the V5 Signal Plane acquisition path to enter "
            "the frozen V68 release wrapper on this exact git HEAD. It is not "
            "economic edge evidence."
            if classification == PASS_CLASSIFICATION
            else "V68 Signal Plane promotion remains blocked."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the fail-closed promotion manifest required before a fresh "
            "V68 run may use the V5 Signal Plane acquisition path."
        )
    )
    parser.add_argument("--offline-capacity", required=True, type=Path)
    parser.add_argument("--offline-bridge", required=True, type=Path)
    parser.add_argument("--live-smoke", required=True, type=Path)
    parser.add_argument("--live-soak", required=True, type=Path)
    parser.add_argument("--route-bridge", required=True, type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/v68_signal_plane_promotion_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = build_promotion_report(
        offline_capacity_path=args.offline_capacity,
        offline_bridge_path=args.offline_bridge,
        live_smoke_path=args.live_smoke,
        live_soak_path=args.live_soak,
        route_bridge_path=args.route_bridge,
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
