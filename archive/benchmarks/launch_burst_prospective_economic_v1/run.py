from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from src.causal_quotes import CausalQuoteObservation
from src.launch_burst_economic_v1 import (
    DRAFT_STATUS,
    RUNNER_VERSION,
    decision_to_dict,
    evaluate_episode,
    feature_snapshot_hash_sha256,
    validate_contract,
)
from src.launch_burst_v0 import canonical_launch_venue, launch_stratum_for_venue

PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_PROSPECTIVE_ECONOMIC_V1"
BLOCKED_CLASSIFICATION = "BLOCKED_LAUNCH_BURST_ECONOMIC_CONTRACT_NOT_FROZEN"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_PROSPECTIVE_ECONOMIC_V1"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _quote(raw: dict[str, Any]) -> CausalQuoteObservation:
    allowed = set(CausalQuoteObservation.__dataclass_fields__)
    unexpected = sorted(set(raw) - allowed)
    if unexpected:
        raise ValueError("unexpected quote fields: " + ",".join(unexpected))
    return CausalQuoteObservation(**raw)


def _validated_active_strata(contract: dict[str, Any]) -> tuple[str, ...]:
    all_strata = tuple(str(value) for value in (contract.get("strata") or ()))
    raw = contract.get("active_strata")
    if not isinstance(raw, list) or not raw:
        raise ValueError("frozen contract requires non-empty active_strata")
    active = tuple(str(value) for value in raw)
    if len(set(active)) != len(active):
        raise ValueError("active_strata cannot contain duplicates")
    unknown = [value for value in active if value not in all_strata]
    if unknown:
        raise ValueError("active_strata must be a subset of contract.strata")
    return active


def _hold_row(
    *,
    episode_key: str,
    token_mint: str,
    stratum: str,
    feature_snapshot: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    decision_as_of = feature_snapshot.get("decision_as_of")
    if isinstance(decision_as_of, bool) or not isinstance(decision_as_of, int) or decision_as_of < 0:
        raise ValueError("held feature_snapshot.decision_as_of must be a non-negative integer")
    return {
        "token_mint": token_mint,
        "stratum": stratum,
        "decision_as_of": decision_as_of,
        "feature_snapshot_hash": feature_snapshot_hash_sha256(feature_snapshot),
        "admitted": False,
        "decision_reason": "STRATUM_HOLD",
        "entry_quote": None,
        "exit_quote": None,
        "status": "STRATUM_HOLD",
        "gross_return_pct": None,
        "net_return_pct": None,
        "pnl_usd": None,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "episode_key": episode_key,
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [row for row in rows if row.get("net_return_pct") is not None]
    values = [float(row["net_return_pct"]) for row in realized]
    profits = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    ordered = sorted(values)
    median = None
    if ordered:
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    profit_factor = (sum(profits) / sum(losses)) if losses else (float("inf") if profits else None)
    return {
        "n": len(rows),
        "held": sum(1 for row in rows if row["status"] == "STRATUM_HOLD"),
        "admitted": sum(1 for row in rows if row["admitted"]),
        "closed": sum(1 for row in rows if row["status"] == "CLOSED"),
        "economic_results": len(realized),
        "failed_exits": sum(1 for row in rows if str(row["status"]).startswith("UNEXITABLE")),
        "entry_unavailable": sum(1 for row in rows if str(row["status"]).startswith("ENTRY_")),
        "positive_share_pct": (100.0 * len(profits) / len(values)) if values else None,
        "mean_net_return_pct": (sum(values) / len(values)) if values else None,
        "median_net_return_pct": median,
        "profit_factor": profit_factor,
        "best_net_return_pct": max(values) if values else None,
        "worst_net_return_pct": min(values) if values else None,
    }


def run_economic_v1(*, contract_path: Path, input_path: Path, output_path: Path) -> dict[str, Any]:
    contract = _read_json(contract_path)
    if contract.get("status") == DRAFT_STATUS:
        return {
            "type": "launch_burst_prospective_economic_result",
            "version": RUNNER_VERSION,
            "classification": BLOCKED_CLASSIFICATION,
            "economic_outcomes_opened": False,
            "reason": "contract is DRAFT_UNARMED; freeze selection and economics before opening outcomes",
        }
    validate_contract(contract, require_frozen=True)
    active_strata = _validated_active_strata(contract)

    source = _read_json(input_path)
    if source.get("type") != "launch_burst_prospective_economic_input_v1":
        raise ValueError("unsupported prospective economic input type")
    if source.get("feature_snapshot_frozen_before_outcomes") is not True:
        raise ValueError("input must attest feature_snapshot_frozen_before_outcomes=true")
    episodes = source.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("episodes must be a list")

    rows: list[dict[str, Any]] = []
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            raise ValueError(f"episode {index} must be an object")
        feature_snapshot = episode.get("feature_snapshot")
        if not isinstance(feature_snapshot, dict):
            raise ValueError(f"episode {index} feature_snapshot must be an object")
        quotes_raw = episode.get("quotes") or []
        if not isinstance(quotes_raw, list):
            raise ValueError(f"episode {index} quotes must be a list")

        token_mint = str(episode.get("token_mint") or "")
        venue = str(episode.get("venue") or "")
        episode_key = str(episode.get("episode_key") or f"episode-{index}")
        stratum = launch_stratum_for_venue(canonical_launch_venue(venue))
        if stratum not in contract["strata"]:
            raise ValueError(f"episode {index} launch stratum is not declared by contract")
        if feature_snapshot.get("stratum") != stratum:
            raise ValueError(f"episode {index} feature snapshot stratum does not match episode venue")

        if stratum not in active_strata:
            row = _hold_row(
                episode_key=episode_key,
                token_mint=token_mint,
                stratum=stratum,
                feature_snapshot=feature_snapshot,
                contract=contract,
            )
        else:
            decision = evaluate_episode(
                token_mint=token_mint,
                venue=venue,
                feature_snapshot=feature_snapshot,
                quotes=tuple(_quote(item) for item in quotes_raw),
                contract=contract,
            )
            row = decision_to_dict(decision)
            row["episode_key"] = episode_key

        rows.append(row)
        strata[stratum].append(row)

    result = {
        "type": "launch_burst_prospective_economic_result",
        "version": RUNNER_VERSION,
        "classification": PASS_CLASSIFICATION,
        "economic_outcomes_opened": True,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "active_strata": list(active_strata),
        "episode_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "strata": {name: _metrics(strata.get(name, [])) for name in contract["strata"]},
        "decisions": rows,
        "interpretation": (
            "PASS means frozen causal accounting completed for active_strata only. It does not by itself "
            "establish edge; held strata produce no economic outcome and Pump/PumpSwap remain independent."
        ),
    }
    _write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen, fail-closed Launch Burst prospective economic evaluator v1")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_economic_v1(contract_path=args.contract, input_path=args.input, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": FAIL_CLASSIFICATION, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["classification"] == PASS_CLASSIFICATION else 3


if __name__ == "__main__":
    raise SystemExit(main())
