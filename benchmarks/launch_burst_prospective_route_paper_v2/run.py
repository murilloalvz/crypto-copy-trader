from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from src.causal_quotes import CausalQuoteObservation
from src.launch_burst_route_paper_v2 import (
    RUNNER_VERSION,
    decision_to_dict,
    evaluate_episode,
    validate_contract,
)

PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2"


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


def _quote(raw: dict[str, Any]) -> CausalQuoteObservation:
    allowed = set(CausalQuoteObservation.__dataclass_fields__)
    unexpected = sorted(set(raw) - allowed)
    if unexpected:
        raise ValueError("unexpected quote fields: " + ",".join(unexpected))
    return CausalQuoteObservation(**raw)


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    admitted_rows = [row for row in rows if row["admitted"]]
    entry_quote_observed = [row for row in admitted_rows if row.get("entry_quote") is not None]
    entry_unavailable = [row for row in admitted_rows if row["status"] == "ENTRY_UNAVAILABLE"]
    entry_rejected = [row for row in admitted_rows if str(row["status"]).startswith("ENTRY_REJECTED")]

    # Economic/route-return metrics are conditional on a usable entry. Provider misses and
    # entry-quality rejections are coverage evidence, not zero-return trades. Once an entry is
    # usable, an unroutable exit remains an explicit negative outcome under the frozen contract.
    conditional_rows = [
        row
        for row in admitted_rows
        if row["status"] == "ROUTE_CLOSED"
        or str(row["status"]).startswith("UNROUTABLE_EXIT")
    ]
    values = [
        float(row["net_route_return_pct"])
        for row in conditional_rows
        if row.get("net_route_return_pct") is not None
    ]
    profits = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    ordered = sorted(values)
    median = None
    if ordered:
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0

    entry_usable = len(conditional_rows)
    return {
        "n": len(rows),
        "admitted": len(admitted_rows),
        "entry_quote_observed": len(entry_quote_observed),
        "entry_provider_coverage_pct": _pct(len(entry_quote_observed), len(admitted_rows)),
        "entry_unavailable": len(entry_unavailable),
        "entry_rejected": len(entry_rejected),
        "entry_usable": entry_usable,
        "entry_usable_pct_of_admitted": _pct(entry_usable, len(admitted_rows)),
        "route_closed": sum(1 for row in conditional_rows if row["status"] == "ROUTE_CLOSED"),
        "failed_exits": sum(1 for row in conditional_rows if str(row["status"]).startswith("UNROUTABLE_EXIT")),
        "conditional_route_results": len(values),
        "conditional_positive_share_pct": _pct(len(profits), len(values)),
        "conditional_mean_net_route_return_pct": (sum(values) / len(values)) if values else None,
        "conditional_median_net_route_return_pct": median,
        "conditional_profit_factor": (sum(profits) / sum(losses)) if losses else (float("inf") if profits else None),
        "conditional_best_net_route_return_pct": max(values) if values else None,
        "conditional_worst_net_route_return_pct": min(values) if values else None,
    }


def run_route_paper_v2(*, contract_path: Path, input_path: Path, output_path: Path) -> dict[str, Any]:
    contract = _read_json(contract_path)
    validate_contract(contract)
    source = _read_json(input_path)
    if source.get("type") != "launch_burst_prospective_route_input_v2":
        raise ValueError("unsupported prospective route input type")
    if source.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("input must attest feature snapshots were frozen before provider quotes")
    if source.get("source_capture_started_after_contract_freeze") is not True:
        raise ValueError("input must attest the source capture started after the frozen contract")
    episodes = source.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("episodes must be a list")

    rows: list[dict[str, Any]] = []
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            raise ValueError(f"episode {index} must be an object")
        snapshot = episode.get("feature_snapshot")
        quotes = episode.get("quotes") or []
        if not isinstance(snapshot, dict) or not isinstance(quotes, list):
            raise ValueError(f"episode {index} snapshot/quotes are invalid")
        decision = evaluate_episode(
            token_mint=str(episode.get("token_mint") or ""),
            venue=str(episode.get("venue") or ""),
            feature_snapshot=snapshot,
            quotes=tuple(_quote(item) for item in quotes),
            contract=contract,
        )
        row = decision_to_dict(decision)
        row["episode_key"] = str(episode.get("episode_key") or f"episode-{index}")
        row["collection"] = episode.get("collection") or {}
        rows.append(row)
        strata[decision.stratum].append(row)

    result = {
        "type": "launch_burst_prospective_route_paper_result_v2",
        "version": RUNNER_VERSION,
        "classification": PASS_CLASSIFICATION,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "episode_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "strata": {name: _metrics(strata.get(name, [])) for name in contract["strata"]},
        "decisions": rows,
        "interpretation": (
            "PASS means frozen prospective route-paper accounting completed. Entry-provider misses and "
            "entry-quality rejections are reported as provider/route coverage and are excluded from conditional "
            "return metrics; after a usable entry, failed exits remain explicit negative outcomes. BUY evidence "
            "is an assembled candidate transaction and SELL evidence is a route-only exact-quantity quote. "
            "These are not landed fills or realized PnL, and cannot by themselves establish executable trading edge."
        ),
    }
    _write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen Launch Burst prospective route-paper evaluator v2")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_route_paper_v2(contract_path=args.contract, input_path=args.input, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": FAIL_CLASSIFICATION, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
