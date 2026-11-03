from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_sniper_v1.compare import run_sniper_comparison_v1


STRICT_COMPARE_VERSION = "launch_burst_sniper_strict_compare_v1"
EXPECTED_INPUT_TYPE = "launch_burst_prospective_route_input_v2"
EXPECTED_RESULT_TYPE = "launch_burst_prospective_route_paper_result_v2"
EXPECTED_RESULT_CLASSIFICATION = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _indexed_rows(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        key = str(row.get("episode_key") or "").strip()
        if not key:
            raise ValueError(f"{label}[{index}] has no episode_key")
        if key in indexed:
            raise ValueError(f"duplicate episode_key in {label}: {key}")
        indexed[key] = row
    return indexed


def validate_sniper_source_integrity_v1(
    *,
    route_input_path: Path,
    route_result_path: Path,
    smart_result_path: Path | None,
) -> dict[str, Any]:
    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)

    if route_input.get("type") != EXPECTED_INPUT_TYPE:
        raise ValueError("unsupported route input type for Sniper strict comparison")
    if route_result.get("type") != EXPECTED_RESULT_TYPE:
        raise ValueError("unsupported route result type for Sniper strict comparison")
    if route_result.get("classification") != EXPECTED_RESULT_CLASSIFICATION:
        raise ValueError("route result must be a PASS before Sniper comparison")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze features before provider quotes")

    inputs = _indexed_rows(route_input.get("episodes"), label="route_input.episodes")
    results = _indexed_rows(route_result.get("decisions"), label="route_result.decisions")
    input_keys = set(inputs)
    result_keys = set(results)
    if input_keys != result_keys:
        missing_in_result = sorted(input_keys - result_keys)
        extra_in_result = sorted(result_keys - input_keys)
        raise ValueError(
            "route input/result episode keys differ: "
            f"missing_in_result={missing_in_result[:5]} extra_in_result={extra_in_result[:5]}"
        )

    token_mismatches: list[str] = []
    for key in sorted(input_keys):
        input_mint = str(inputs[key].get("token_mint") or "").strip()
        result_mint = str(results[key].get("token_mint") or "").strip()
        if not input_mint or input_mint != result_mint:
            token_mismatches.append(key)
    if token_mismatches:
        raise ValueError(
            "route input/result token mint mismatch for episode keys: "
            + ",".join(token_mismatches[:5])
        )

    smart_trade_count = 0
    if smart_result_path is not None:
        smart = _read_json(smart_result_path)
        trades = smart.get("trades") or []
        smart_rows = _indexed_rows(trades, label="smart_result.trades") if trades else {}
        orphan_smart = sorted(set(smart_rows) - input_keys)
        if orphan_smart:
            raise ValueError(
                "SMART-LADDER contains episode keys outside the route universe: "
                + ",".join(orphan_smart[:5])
            )
        smart_trade_count = len(smart_rows)

    return {
        "version": STRICT_COMPARE_VERSION,
        "route_episode_count": len(inputs),
        "exact_episode_key_parity": True,
        "exact_token_mint_parity": True,
        "unique_episode_keys": True,
        "route_result_pass_required": True,
        "smart_trade_count": smart_trade_count,
        "smart_orphan_episode_count": 0,
    }


def run_strict_sniper_comparison_v1(
    *,
    contract_path: Path,
    policy_path: Path,
    route_input_path: Path,
    route_result_path: Path,
    smart_result_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    integrity = validate_sniper_source_integrity_v1(
        route_input_path=route_input_path,
        route_result_path=route_result_path,
        smart_result_path=smart_result_path,
    )
    result = run_sniper_comparison_v1(
        contract_path=contract_path,
        policy_path=policy_path,
        route_input_path=route_input_path,
        route_result_path=route_result_path,
        smart_result_path=smart_result_path,
        output_path=output_path,
    )
    result["source_integrity"] = integrity
    _write_json(output_path, result)
    return result
