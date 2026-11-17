from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from benchmarks.market_first_liquidity_discovery_v0.run import _cohort


VERSION = "market_first_liquidity_dominant_quote_v0"
PASS = "PASS_MARKET_FIRST_LIQUIDITY_DOMINANT_QUOTE_V0"
SOURCE_NAME = "market-first-liquidity-discovery-v0.json"
OUTPUT_NAME = "market-first-liquidity-dominant-quote-v0.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def dominant_quote_mint_v0(rows: list[dict[str, Any]]) -> str:
    counts = Counter(
        str(row.get("quote_mint"))
        for row in rows
        if isinstance(row.get("quote_mint"), str) and str(row.get("quote_mint")).strip()
    )
    if not counts:
        raise ValueError("no quote_mint evidence available in baseline rows")
    # Selection uses support only, never route status, provider impact or future return.
    return min(counts, key=lambda mint: (-counts[mint], mint))


def run_quote_stratification_v0(*, run_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    source_path = run_dir / SOURCE_NAME
    if not source_path.is_file():
        raise ValueError(f"required liquidity discovery artifact missing: {source_path}")

    source = _read_json(source_path)
    if source.get("classification") != "PASS_MARKET_FIRST_LIQUIDITY_DISCOVERY_V0":
        raise ValueError("source liquidity discovery did not PASS")
    if source.get("threshold_search_performed") is not False:
        raise ValueError("source artifact unexpectedly performed threshold search")
    if source.get("selector_changed") is not False:
        raise ValueError("source artifact unexpectedly changed selector")
    if source.get("provider_execution_used_as_feature") is not False:
        raise ValueError("source artifact leaked provider execution into features")

    rows = [row for row in source.get("rows") or [] if isinstance(row, dict)]
    baseline = [row for row in rows if row.get("baseline_admitted") is True]
    sniper = [row for row in baseline if row.get("sniper_selected") is True]
    quote_mint = dominant_quote_mint_v0(baseline)
    baseline_same_quote = [row for row in baseline if row.get("quote_mint") == quote_mint]
    sniper_same_quote = [row for row in sniper if row.get("quote_mint") == quote_mint]

    report = {
        "type": "market_first_liquidity_dominant_quote_report_v0",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "RETROSPECTIVE_DISCOVERY_UNIT_CONTROL_ONLY",
        "selection_basis": "largest_baseline_quote_mint_support_only_no_outcome_use",
        "dominant_quote_mint": quote_mint,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "provider_execution_used_as_feature": False,
        "source_artifact": str(source_path),
        "source_integrity": source.get("source_integrity"),
        "baseline_total_count": len(baseline),
        "sniper_total_count": len(sniper),
        "baseline_dominant_quote_count": len(baseline_same_quote),
        "sniper_dominant_quote_count": len(sniper_same_quote),
        "baseline_dominant_quote_share_pct": (
            100.0 * len(baseline_same_quote) / len(baseline) if baseline else None
        ),
        "sniper_dominant_quote_share_pct": (
            100.0 * len(sniper_same_quote) / len(sniper) if sniper else None
        ),
        "cohorts": {
            "baseline_dominant_quote": _cohort(baseline_same_quote),
            "sniper_dominant_quote": _cohort(sniper_same_quote),
        },
        "interpretation": (
            "Unit-control diagnostic only. The dominant quote mint is selected solely by baseline support, "
            "before reading route outcomes. The same quote mint is then used for baseline and Sniper cohorts, "
            "making raw reserve values unit-comparable. No threshold is searched or promoted."
        ),
    }
    destination = output_path or (run_dir / OUTPUT_NAME)
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Outcome-blind dominant-quote unit control for liquidity discovery")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_quote_stratification_v0(run_dir=args.run_dir, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_LIQUIDITY_DOMINANT_QUOTE_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
