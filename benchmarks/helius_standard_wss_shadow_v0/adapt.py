from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Iterable

from src.carbon_matched_unit_adapter import (
    ADAPTED as MATCHED_ADAPTED,
    CONFLICTING_CONTEXT,
    INVALID_EVENT as MATCHED_INVALID,
    MISSING_CONTEXT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.carbon_protocol_adapter import (
    ADAPTED as PROTOCOL_ADAPTED,
    INVALID_EVENT as PROTOCOL_INVALID,
    adapt_carbon_pumpswap_create_pool_v0,
)


ADAPTER_AUDIT_VERSION = "helius_standard_wss_shadow_adapter_audit_v0"
CARBON_DECODER_VERSION = "2.0.0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _index_unique(
    rows: Iterable[dict[str, Any]], row_type: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        if row.get("type") != row_type:
            continue
        key = row.get("event_key")
        if not isinstance(key, str) or not key:
            continue
        if key in indexed:
            duplicates.append(key)
        indexed[key] = row
    return indexed, duplicates


def audit_adapters(
    *,
    manifest_path: Path,
    carbon_output_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    manifest_rows = _jsonl(manifest_path)
    carbon_rows = _jsonl(carbon_output_path)

    manifests, manifest_duplicates = _index_unique(
        manifest_rows, "wss_target_event_manifest"
    )
    events, carbon_duplicates = _index_unique(carbon_rows, "carbon_canonical_event")
    footers = [row for row in carbon_rows if row.get("type") == "carbon_decoder_footer"]

    footer = footers[0] if len(footers) == 1 else None
    carbon_footer_valid = (
        footer is not None
        and footer.get("carbon_decoder_version") == CARBON_DECODER_VERSION
        and int(footer.get("input_events", -1)) == len(events)
        and int(footer.get("output_events", -1)) == len(events)
        and int(footer.get("decode_failures", -1)) == 0
    )

    missing_manifest_keys: list[str] = []
    rejected_manifest_keys: list[str] = []
    invalid_manifest_clock_keys: list[str] = []
    ordered: list[tuple[int, str, int, str, dict[str, Any], dict[str, Any]]] = []

    for event_key, event in events.items():
        manifest = manifests.get(event_key)
        if manifest is None:
            missing_manifest_keys.append(event_key)
            continue
        if (
            manifest.get("transaction_succeeded") is not True
            or manifest.get("accepted_for_market_research") is not True
        ):
            rejected_manifest_keys.append(event_key)
            continue
        received_ns = manifest.get("first_received_wall_ns")
        log_index = manifest.get("log_index")
        signature = manifest.get("signature")
        if (
            not isinstance(received_ns, int)
            or isinstance(received_ns, bool)
            or received_ns <= 0
            or not isinstance(log_index, int)
            or isinstance(log_index, bool)
            or not isinstance(signature, str)
            or not signature
        ):
            invalid_manifest_clock_keys.append(event_key)
            continue
        ordered.append((received_ns, signature, log_index, event_key, event, manifest))

    ordered.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

    pool_observations = []
    output_rows: list[dict[str, Any]] = []
    protocol_status_counts: Counter[str] = Counter()
    matched_status_counts: Counter[str] = Counter()
    matched_by_event_type: dict[str, Counter[str]] = defaultdict(Counter)
    non_flow_event_counts: Counter[str] = Counter()
    invalid_or_conflicting_keys: list[str] = []

    for received_ns, _signature, _log_index, event_key, event, manifest in ordered:
        observed_at = received_ns // 1_000_000_000
        event_type = str(event.get("event_type", ""))

        base_row = {
            "type": "helius_standard_wss_shadow_adapter_result",
            "version": ADAPTER_AUDIT_VERSION,
            "event_key": event_key,
            "event_type": event_type,
            "observed_at": observed_at,
            "first_received_wall_ns": received_ns,
            "transaction_log_complete": manifest.get("transaction_log_complete"),
        }

        if event_type == "pumpswap_create_pool":
            result = adapt_carbon_pumpswap_create_pool_v0(event, observed_at=observed_at)
            protocol_status_counts[result.status] += 1
            if result.status == PROTOCOL_ADAPTED and result.pool_observation is not None:
                pool_observations.append(result.pool_observation)
            elif result.status == PROTOCOL_INVALID:
                invalid_or_conflicting_keys.append(event_key)
            output_rows.append(
                {
                    **base_row,
                    "stage": "protocol_context",
                    "status": result.status,
                    "pool_observation": (
                        asdict(result.pool_observation)
                        if result.pool_observation is not None
                        else None
                    ),
                    "provenance_keys": list(result.provenance_keys),
                    "data_quality_flags": list(result.data_quality_flags),
                }
            )
            continue

        if event_type == "pump_trade":
            result = adapt_carbon_pump_trade_v0(event, observed_at=observed_at)
        elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
            result = adapt_carbon_pumpswap_trade_v0(
                event,
                observed_at=observed_at,
                pool_observations=tuple(pool_observations),
            )
        else:
            non_flow_event_counts[event_type or "UNKNOWN"] += 1
            output_rows.append(
                {
                    **base_row,
                    "stage": "not_applicable",
                    "status": "NON_FLOW_EVENT",
                    "observation": None,
                    "provenance_keys": [event_key],
                    "data_quality_flags": [],
                }
            )
            continue

        matched_status_counts[result.status] += 1
        matched_by_event_type[event_type][result.status] += 1
        if result.status in {MATCHED_INVALID, CONFLICTING_CONTEXT}:
            invalid_or_conflicting_keys.append(event_key)
        output_rows.append(
            {
                **base_row,
                "stage": "matched_unit_flow",
                "status": result.status,
                "observation": (
                    asdict(result.observation) if result.observation is not None else None
                ),
                "provenance_keys": list(result.provenance_keys),
                "data_quality_flags": list(result.data_quality_flags),
            }
        )

    _write_jsonl(output_path, output_rows)

    matched_by_event_type_json = {
        event_type: dict(sorted(counts.items()))
        for event_type, counts in sorted(matched_by_event_type.items())
    }
    pumpswap_trade_total = sum(
        matched_by_event_type[event_type][status]
        for event_type in ("pumpswap_buy", "pumpswap_sell")
        for status in matched_by_event_type[event_type]
    )
    pumpswap_adapted = sum(
        matched_by_event_type[event_type][MATCHED_ADAPTED]
        for event_type in ("pumpswap_buy", "pumpswap_sell")
    )

    valid_adapter_audit = (
        carbon_footer_valid
        and not manifest_duplicates
        and not carbon_duplicates
        and not missing_manifest_keys
        and not rejected_manifest_keys
        and not invalid_manifest_clock_keys
        and not invalid_or_conflicting_keys
        and len(ordered) == len(events)
    )

    return {
        "type": "helius_standard_wss_shadow_adapter_audit",
        "version": ADAPTER_AUDIT_VERSION,
        "carbon_footer_valid": carbon_footer_valid,
        "carbon_events": len(events),
        "manifest_events": len(manifests),
        "joined_accepted_events": len(ordered),
        "manifest_duplicate_event_keys": len(set(manifest_duplicates)),
        "carbon_duplicate_event_keys": len(set(carbon_duplicates)),
        "missing_manifest_events": len(missing_manifest_keys),
        "rejected_manifest_events": len(rejected_manifest_keys),
        "invalid_manifest_clock_events": len(invalid_manifest_clock_keys),
        "protocol_status_counts": dict(sorted(protocol_status_counts.items())),
        "pool_context_observations": len(pool_observations),
        "matched_unit_status_counts": dict(sorted(matched_status_counts.items())),
        "matched_unit_by_event_type": matched_by_event_type_json,
        "matched_unit_adapted_events": matched_status_counts[MATCHED_ADAPTED],
        "matched_unit_missing_context_events": matched_status_counts[MISSING_CONTEXT],
        "pumpswap_trade_events": pumpswap_trade_total,
        "pumpswap_matched_unit_adapted_events": pumpswap_adapted,
        "pumpswap_context_coverage_pct": (
            0.0 if pumpswap_trade_total == 0 else 100.0 * pumpswap_adapted / pumpswap_trade_total
        ),
        "non_flow_event_counts": dict(sorted(non_flow_event_counts.items())),
        "invalid_or_conflicting_events": len(invalid_or_conflicting_keys),
        "invalid_or_conflicting_event_examples": sorted(set(invalid_or_conflicting_keys))[:10],
        "valid_adapter_audit": valid_adapter_audit,
        "chain_complete_coverage_claimed": False,
        "notes": [
            "MISSING_CONTEXT is preserved as missingness and does not fail the adapter audit.",
            "PumpSwap quote identity is never assumed and future pool context is never backfilled.",
            "This adapter audit does not establish chain-complete coverage or economic edge.",
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit live Carbon events through protocol and matched-unit adapters"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--carbon-output", type=Path, required=True)
    parser.add_argument("--out", dest="output_path", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = audit_adapters(
        manifest_path=args.manifest,
        carbon_output_path=args.carbon_output,
        output_path=args.output_path,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_adapter_audit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
