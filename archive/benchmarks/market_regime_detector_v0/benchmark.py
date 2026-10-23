"""Research-only benchmark for mature online regime/change detectors.

This harness does not select a trading feature or tune detector parameters.  It feeds
frozen synthetic event-intensity streams to River's maintained Page-Hinkley and ADWIN
implementations using their documented defaults (Page-Hinkley is configured mode='both'
while retaining its other defaults).

The purpose is to learn basic behavioral properties before any historical/outcome
experiment: persistent step response, direction symmetry, short-burst behavior and
stable-stream false alarms.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from river import drift


BENCHMARK_VERSION = "market_regime_detector_v0"


@dataclass(frozen=True)
class Scenario:
    name: str
    values: tuple[float, ...]
    change_index: int | None
    persistent_change: bool


@dataclass(frozen=True)
class DetectorResult:
    detector: str
    scenario: str
    detections: tuple[int, ...]
    first_detection_index: int | None
    first_detection_delay: int | None
    pre_change_detection_count: int


def _low_pattern(n: int) -> tuple[float, ...]:
    pattern = (2.0, 2.0, 3.0, 1.0)
    return tuple(pattern[i % len(pattern)] for i in range(n))


def _high_pattern(n: int) -> tuple[float, ...]:
    pattern = (8.0, 8.0, 9.0, 7.0)
    return tuple(pattern[i % len(pattern)] for i in range(n))


def frozen_scenarios() -> tuple[Scenario, ...]:
    stable = Scenario(
        name="stable_low",
        values=_low_pattern(360),
        change_index=None,
        persistent_change=False,
    )
    up_at = 180
    abrupt_up = Scenario(
        name="abrupt_up",
        values=_low_pattern(up_at) + _high_pattern(240),
        change_index=up_at,
        persistent_change=True,
    )
    down_at = 180
    abrupt_down = Scenario(
        name="abrupt_down",
        values=_high_pattern(down_at) + _low_pattern(240),
        change_index=down_at,
        persistent_change=True,
    )
    burst_at = 180
    short_burst = Scenario(
        name="short_up_burst",
        values=_low_pattern(burst_at) + _high_pattern(8) + _low_pattern(180),
        change_index=burst_at,
        persistent_change=False,
    )
    gradual_at = 180
    ramp = tuple(2.0 + 6.0 * i / 119.0 for i in range(120))
    gradual_up = Scenario(
        name="gradual_up",
        values=_low_pattern(gradual_at) + ramp + _high_pattern(120),
        change_index=gradual_at,
        persistent_change=True,
    )
    return stable, abrupt_up, abrupt_down, short_burst, gradual_up


def _new_detectors():
    return {
        "river_page_hinkley_default_both": drift.PageHinkley(mode="both"),
        "river_adwin_default": drift.ADWIN(),
    }


def run_detector(detector_name: str, detector, scenario: Scenario) -> DetectorResult:
    detections: list[int] = []
    for index, value in enumerate(scenario.values):
        detector.update(value)
        if detector.drift_detected:
            detections.append(index)

    change_index = scenario.change_index
    pre_change = (
        sum(index < change_index for index in detections)
        if change_index is not None
        else len(detections)
    )
    first_post_change = None
    if change_index is not None:
        first_post_change = next(
            (index for index in detections if index >= change_index), None
        )
    return DetectorResult(
        detector=detector_name,
        scenario=scenario.name,
        detections=tuple(detections),
        first_detection_index=(detections[0] if detections else None),
        first_detection_delay=(
            first_post_change - change_index
            if first_post_change is not None and change_index is not None
            else None
        ),
        pre_change_detection_count=pre_change,
    )


def run_benchmark() -> dict:
    results: list[DetectorResult] = []
    for scenario in frozen_scenarios():
        for name, detector in _new_detectors().items():
            results.append(run_detector(name, detector, scenario))

    stable_false_alarms = sum(
        len(item.detections) for item in results if item.scenario == "stable_low"
    )
    persistent = [
        item
        for item in results
        if item.scenario in {"abrupt_up", "abrupt_down", "gradual_up"}
    ]
    persistent_detected = sum(item.first_detection_delay is not None for item in persistent)

    return {
        "type": "market_regime_detector_benchmark",
        "version": BENCHMARK_VERSION,
        "configuration": {
            "page_hinkley": "River defaults; mode=both",
            "adwin": "River defaults",
            "parameter_tuning": False,
            "economic_outcomes_used": False,
        },
        "summary": {
            "stable_false_alarm_count": stable_false_alarms,
            "persistent_scenario_detector_pairs": len(persistent),
            "persistent_scenario_detector_pairs_detected": persistent_detected,
        },
        "results": [asdict(item) for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run_benchmark()
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
