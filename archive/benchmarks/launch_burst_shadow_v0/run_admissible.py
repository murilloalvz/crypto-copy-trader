from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_shadow_v0.run import (
    DEFAULT_HORIZONS_SECONDS,
    PASS_CLASSIFICATION,
    _assert_output_isolated,
    _parse_horizons,
    _write_json,
    run_shadow_v0,
)
from benchmarks.launch_burst_shadow_v0.source_admissibility import evaluate_burst_source


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _absolute(path_text: str | None) -> str:
    if not path_text:
        raise ValueError("resolved source path is missing")
    return str(Path(path_text).resolve())


def run_from_admissible_source(
    *,
    live_report_path: Path,
    output_path: Path,
    horizons_seconds: tuple[int, ...] = DEFAULT_HORIZONS_SECONDS,
    candidate_parity_report: Path | None = None,
) -> dict[str, Any]:
    source = evaluate_burst_source(live_report_path)
    if source.get("burst_source_admissible") is not True:
        failed = ",".join(source.get("failed_gates") or [])
        raise ValueError(f"source is not Burst-admissible; failed gates: {failed}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    original = _read_json(live_report_path)
    normalized = copy.deepcopy(original)
    normalized.setdefault("run", {})["status"] = "CLOSED"
    normalized["valid_live_discovery"] = True
    normalized.setdefault("artifacts", {})["processed_chunks"] = _absolute(
        (source.get("resolved") or {}).get("processed_chunks")
    )
    normalized.setdefault("bootstrap", {})["report_path"] = _absolute(
        (source.get("resolved") or {}).get("bootstrap_report")
    )

    compatibility_report = output.with_suffix(output.suffix + ".source-compat.json")
    protected = [
        Path(live_report_path),
        Path(normalized["artifacts"]["processed_chunks"]),
        Path(normalized["bootstrap"]["report_path"]),
    ]
    if candidate_parity_report is not None:
        protected.append(Path(candidate_parity_report))
    _assert_output_isolated(output, protected)
    _assert_output_isolated(compatibility_report, protected)

    try:
        _write_json(compatibility_report, normalized)
        result = run_shadow_v0(
            live_report_path=compatibility_report,
            horizons_seconds=horizons_seconds,
            candidate_parity_report=candidate_parity_report,
        )
    finally:
        compatibility_report.unlink(missing_ok=True)

    result["source_admissibility"] = source
    result["gates"].pop("source_valid_live_discovery", None)
    result["gates"]["source_burst_admissible"] = True
    result["safety"]["requires_source_run_closed"] = False
    result["safety"]["requires_source_finalized_evidence"] = True
    result["safety"]["market_first_official_pass_required"] = False
    result["safety"]["original_source_run_status"] = source.get("original_run_status")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run DB-free/network-free Launch Burst shadow from finalized source evidence "
            "without requiring the Market-First overall PASS verdict"
        )
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--horizons", type=_parse_horizons, default=DEFAULT_HORIZONS_SECONDS)
    parser.add_argument("--candidate-parity-report", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/launch_burst_shadow_v0/admissible-report.json"),
    )
    args = parser.parse_args()

    result = run_from_admissible_source(
        live_report_path=args.live_report,
        output_path=args.output,
        horizons_seconds=args.horizons,
        candidate_parity_report=args.candidate_parity_report,
    )
    _write_json(args.output, result)
    print(
        f"Launch Burst admissible shadow classification={result['classification']} "
        f"source_status={result['source_admissibility']['original_run_status']} "
        f"anchors={sum(item['anchor_count'] for item in result['strata'].values())} "
        f"adapted={result['feature_coverage']['adapted_trade_count']}/"
        f"{result['feature_coverage']['decoded_trade_count']}"
    )
    print(f"output={args.output}")
    return 0 if result["classification"] == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
