from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

VERSION = "carbon_runtime_replay_suite_v1"
EXPECTED_CARBON_VERSION = "2.0.0"
DEFAULT_EVENTS = 10_000


def _metric(report: dict[str, Any], family: str, key: str) -> float:
    value = report["timing"][family][key]
    if value is None:
        return 0.0
    return float(value)


def _run(
    binary: Path,
    *,
    mode: str,
    events: int,
    source_gap_us: int,
    slow_every: int,
    slow_ms: int,
    carbon_channel: int,
    handoff_buffer: int,
) -> dict[str, Any]:
    command = [
        str(binary),
        "--mode",
        mode,
        "--events",
        str(events),
        "--source-gap-us",
        str(source_gap_us),
        "--slow-every",
        str(slow_every),
        "--slow-ms",
        str(slow_ms),
        "--carbon-channel",
        str(carbon_channel),
        "--handoff-buffer",
        str(handoff_buffer),
    ]
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"runner produced no JSON output: {command!r}")
    report = json.loads(lines[-1])
    if report.get("type") != "carbon_runtime_replay_result":
        raise RuntimeError("runner output has unexpected type")
    if report.get("carbon_version") != EXPECTED_CARBON_VERSION:
        raise RuntimeError("runner Carbon version drift")
    return report


def _pipeline_correct(report: dict[str, Any], events: int) -> bool:
    counts = report["counts"]
    correctness = report["correctness"]
    return (
        int(counts["source_sent"]) == events
        and int(counts["pipeline_processed"]) == events
        and int(correctness["pipeline_order_violations"]) == 0
        and int(correctness["pipeline_current_at_end"]) == 0
    )


def _handoff_accounting(report: dict[str, Any]) -> bool:
    counts = report["counts"]
    correctness = report["correctness"]
    processed = int(counts["pipeline_processed"])
    enqueued = int(counts["handoff_enqueued"])
    dropped = int(counts["handoff_dropped"])
    completed = int(counts["worker_completed"])
    return (
        enqueued + dropped == processed
        and completed == enqueued
        and int(correctness["worker_order_violations"]) == 0
        and int(correctness["downstream_current_at_end"]) == 0
    )


def classify(reports: dict[str, dict[str, Any]], events: int) -> dict[str, Any]:
    fast = reports["inline_fast"]
    inline_slow = reports["inline_slow"]
    handoff = reports["handoff_slow"]
    burst = reports["handoff_burst"]

    fast_p95 = _metric(fast, "pipeline_e2e", "p95_ms")
    inline_slow_p95 = _metric(inline_slow, "pipeline_e2e", "p95_ms")
    inline_bystander_p50 = _metric(inline_slow, "bystander_after_slow", "p50_ms")
    handoff_p95 = _metric(handoff, "pipeline_e2e", "p95_ms")

    correctness_pass = all(
        _pipeline_correct(report, events)
        for report in (fast, inline_slow, handoff, burst)
    )
    handoff_accounting_pass = _handoff_accounting(handoff) and _handoff_accounting(burst)
    representative_zero_drop = int(handoff["counts"]["handoff_dropped"]) == 0

    # Frozen before observing benchmark output. A 5 ms synchronous stall every 100
    # events must create at least 1 ms of measurable p95/bystander inflation to count
    # as reproduced global HOL.
    inline_hol_reproduced = (
        inline_slow_p95 >= fast_p95 + 1.0
        and inline_bystander_p50 >= fast_p95 + 1.0
    )

    # The async boundary is considered isolated when Carbon's acceptance latency under
    # the same downstream stalls stays close to the fast baseline. Relative + absolute
    # guard avoids machine-speed dependence.
    isolation_limit_ms = max(fast_p95 * 3.0, fast_p95 + 1.0)
    representative_isolated = handoff_p95 <= isolation_limit_ms

    burst_drops = int(burst["counts"]["handoff_dropped"])
    burst_drop_accounting_explicit = (
        int(burst["counts"]["handoff_enqueued"]) + burst_drops
        == int(burst["counts"]["pipeline_processed"])
    )

    if (
        correctness_pass
        and handoff_accounting_pass
        and representative_zero_drop
        and inline_hol_reproduced
        and representative_isolated
        and burst_drop_accounting_explicit
    ):
        classification = "ADAPT_CARBON_RUNTIME_BOUNDARY"
    elif correctness_pass and handoff_accounting_pass and not inline_hol_reproduced:
        classification = "INCONCLUSIVE_CARBON_INLINE_HOL_NOT_REPRODUCED"
    else:
        classification = "REJECT_OR_INVESTIGATE_CARBON_RUNTIME_V1"

    return {
        "classification": classification,
        "checks": {
            "pipeline_correctness_pass": correctness_pass,
            "handoff_accounting_pass": handoff_accounting_pass,
            "representative_zero_drop": representative_zero_drop,
            "inline_hol_reproduced": inline_hol_reproduced,
            "representative_isolated": representative_isolated,
            "burst_drop_accounting_explicit": burst_drop_accounting_explicit,
        },
        "evidence": {
            "inline_fast_pipeline_p95_ms": fast_p95,
            "inline_slow_pipeline_p95_ms": inline_slow_p95,
            "inline_slow_bystander_after_slow_p50_ms": inline_bystander_p50,
            "handoff_slow_pipeline_p95_ms": handoff_p95,
            "handoff_isolation_limit_ms": isolation_limit_ms,
            "handoff_slow_drops": int(handoff["counts"]["handoff_dropped"]),
            "handoff_burst_drops": burst_drops,
            "inline_slow_pipeline_outstanding_high_water": int(
                inline_slow["pressure"]["pipeline_outstanding_high_water"]
            ),
            "handoff_slow_pipeline_outstanding_high_water": int(
                handoff["pressure"]["pipeline_outstanding_high_water"]
            ),
            "handoff_slow_downstream_outstanding_high_water": int(
                handoff["pressure"]["downstream_outstanding_high_water"]
            ),
            "handoff_burst_downstream_outstanding_high_water": int(
                burst["pressure"]["downstream_outstanding_high_water"]
            ),
        },
        "interpretation": {
            "ADAPT_CARBON_RUNTIME_BOUNDARY": (
                "Stock Carbon awaits processors in its central pipeline loop, so slow inline "
                "work creates global HOL. Keep Carbon as datasource/decoder/runtime shell only "
                "with a bounded, observable, constant-time handoff at the hot-path boundary; "
                "slow persistence/research/enrichment must remain downstream."
            ),
            "INCONCLUSIVE_CARBON_INLINE_HOL_NOT_REPRODUCED": (
                "The configured stall did not reproduce the expected inline HOL strongly enough. "
                "Do not adopt or reject the runtime yet; inspect instrumentation and rerun the "
                "same frozen scenario before changing thresholds."
            ),
            "REJECT_OR_INVESTIGATE_CARBON_RUNTIME_V1": (
                "Correctness, accounting, or representative-load isolation failed. Do not promote "
                "the Carbon runtime boundary until the exact failure is explained."
            ),
        }[classification],
    }


def _binary_path(manifest: Path) -> Path:
    target = manifest.parent / "target" / "release"
    name = "carbon-runtime-replay-v1"
    if sys.platform.startswith("win"):
        name += ".exe"
    return target / name


def run_suite(
    *,
    manifest: Path,
    out_dir: Path,
    events: int,
    source_gap_us: int,
    slow_every: int,
    slow_ms: int,
    carbon_channel: int,
    handoff_buffer: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    lockfile = manifest.parent / "Cargo.lock"
    if not lockfile.exists():
        subprocess.run(
            ["cargo", "generate-lockfile", "--manifest-path", str(manifest)],
            check=True,
        )

    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(manifest),
        ],
        check=True,
    )
    binary = _binary_path(manifest)
    if not binary.exists():
        raise FileNotFoundError(f"compiled runner not found: {binary}")

    scenarios = {
        "inline_fast": dict(
            mode="inline",
            source_gap_us=source_gap_us,
            slow_every=0,
            slow_ms=0,
        ),
        "inline_slow": dict(
            mode="inline",
            source_gap_us=source_gap_us,
            slow_every=slow_every,
            slow_ms=slow_ms,
        ),
        "handoff_slow": dict(
            mode="handoff",
            source_gap_us=source_gap_us,
            slow_every=slow_every,
            slow_ms=slow_ms,
        ),
        "handoff_burst": dict(
            mode="handoff",
            source_gap_us=0,
            slow_every=slow_every,
            slow_ms=slow_ms,
        ),
    }

    reports: dict[str, dict[str, Any]] = {}
    for name, scenario in scenarios.items():
        report = _run(
            binary,
            events=events,
            carbon_channel=carbon_channel,
            handoff_buffer=handoff_buffer,
            **scenario,
        )
        reports[name] = report
        (out_dir / f"{name}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    verdict = classify(reports, events)
    suite = {
        "type": "carbon_runtime_replay_suite_result",
        "version": VERSION,
        "frozen_protocol": {
            "events": events,
            "source_gap_us": source_gap_us,
            "target_source_rate_eps": (
                math.inf if source_gap_us == 0 else 1_000_000.0 / source_gap_us
            ),
            "slow_every": slow_every,
            "slow_ms": slow_ms,
            "carbon_channel": carbon_channel,
            "handoff_buffer": handoff_buffer,
            "scenarios": list(scenarios),
        },
        "verdict": verdict,
        "reports": reports,
    }
    (out_dir / "suite-report.json").write_text(
        json.dumps(suite, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return suite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/carbon_runtime_replay_v1/rust_runner/Cargo.toml"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/carbon_runtime_replay_v1"),
    )
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--source-gap-us", type=int, default=200)
    parser.add_argument("--slow-every", type=int, default=100)
    parser.add_argument("--slow-ms", type=int, default=5)
    parser.add_argument("--carbon-channel", type=int, default=256)
    parser.add_argument("--handoff-buffer", type=int, default=1024)
    args = parser.parse_args()

    suite = run_suite(
        manifest=args.manifest,
        out_dir=args.out_dir,
        events=args.events,
        source_gap_us=args.source_gap_us,
        slow_every=args.slow_every,
        slow_ms=args.slow_ms,
        carbon_channel=args.carbon_channel,
        handoff_buffer=args.handoff_buffer,
    )
    print(json.dumps(suite["verdict"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
