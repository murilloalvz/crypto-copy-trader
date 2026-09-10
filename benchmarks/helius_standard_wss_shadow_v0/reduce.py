from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

from benchmarks.carbon_decoder_parity_v1.parity import extract_contextual_target_payloads
from benchmarks.helius_standard_wss_shadow_v0 import TRACE_VERSION

REDUCER_VERSION = "helius_standard_wss_shadow_reducer_v1"


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


def reduce_shadow(
    *,
    trace_path: Path,
    carbon_input_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    rows = _jsonl(trace_path)
    headers = [row for row in rows if row.get("type") == "trace_header"]
    footers = [row for row in rows if row.get("type") == "trace_footer"]
    logs_rows = [row for row in rows if row.get("type") == "logs_notification"]

    trace_contract_valid = (
        len(headers) == 1
        and headers[0].get("version") == TRACE_VERSION
        and headers[0].get("chain_complete_coverage_claimed") is False
        and len(footers) == 1
        and footers[0].get("version") == TRACE_VERSION
        and footers[0].get("chain_complete_coverage_claimed") is False
    )

    carbon_by_key: dict[str, dict[str, Any]] = {}
    manifest_by_key: dict[str, dict[str, Any]] = {}
    notification_signatures: set[str] = set()
    duplicate_notifications = 0
    seen_notification_identity: set[tuple[str, int, str]] = set()
    stack_errors = 0
    successful_tx_stack_errors = 0
    failed_tx_stack_errors = 0
    stack_error_examples: list[dict[str, Any]] = []
    target_counts: Counter[str] = Counter()
    accepted_counts: Counter[str] = Counter()
    failed_tx_target_events = 0
    conflicting_event_keys: list[str] = []

    ordered_logs = sorted(
        logs_rows,
        key=lambda row: (
            int(row.get("received_wall_ns", 0)),
            str(row.get("signature", "")),
            str(row.get("subscription_label", "")),
        ),
    )

    for row in ordered_logs:
        signature = row.get("signature")
        slot = row.get("slot")
        logs = row.get("logs")
        received_wall_ns = row.get("received_wall_ns")
        subscription_label = row.get("subscription_label")
        if (
            not isinstance(signature, str)
            or not signature
            or not isinstance(slot, int)
            or isinstance(slot, bool)
            or not isinstance(received_wall_ns, int)
            or isinstance(received_wall_ns, bool)
            or received_wall_ns <= 0
            or not isinstance(logs, list)
            or subscription_label not in {"pump_logs", "pumpswap_logs"}
        ):
            continue

        notification_identity = (signature, slot, subscription_label)
        if notification_identity in seen_notification_identity:
            duplicate_notifications += 1
        else:
            seen_notification_identity.add(notification_identity)
        notification_signatures.add(signature)

        targets, record_stack_errors = extract_contextual_target_payloads(logs)
        stack_errors += record_stack_errors
        tx_succeeded = row.get("err") is None
        if record_stack_errors:
            if tx_succeeded:
                successful_tx_stack_errors += record_stack_errors
            else:
                failed_tx_stack_errors += record_stack_errors
            if len(stack_error_examples) < 10:
                stack_error_examples.append(
                    {
                        "signature": signature,
                        "slot": slot,
                        "subscription_label": subscription_label,
                        "transaction_succeeded": tx_succeeded,
                        "stack_errors": record_stack_errors,
                    }
                )

        for target in targets:
            log_index = int(target["log_index"])
            event_type = str(target["event_type"])
            program_id = str(target["program_id"])
            payload = bytes(target["payload"])
            event_key = f"{signature}:{log_index}:{event_type}"
            target_counts[event_type] += 1

            manifest_candidate = {
                "type": "wss_target_event_manifest",
                "version": REDUCER_VERSION,
                "event_key": event_key,
                "signature": signature,
                "slot": slot,
                "log_index": log_index,
                "program_id": program_id,
                "event_type": event_type,
                "first_received_wall_ns": received_wall_ns,
                "session_key": row.get("session_key"),
                "first_subscription_label": subscription_label,
                "transaction_succeeded": tx_succeeded,
                "accepted_for_market_research": tx_succeeded,
            }
            carbon_candidate = {
                "type": "carbon_decoder_input",
                "event_key": event_key,
                "signature": signature,
                "slot": slot,
                "log_index": log_index,
                "program_id": program_id,
                "event_type": event_type,
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }

            previous_manifest = manifest_by_key.get(event_key)
            if previous_manifest is None:
                manifest_by_key[event_key] = manifest_candidate
            else:
                immutable_fields = (
                    "signature",
                    "slot",
                    "log_index",
                    "program_id",
                    "event_type",
                    "transaction_succeeded",
                )
                if any(
                    previous_manifest.get(field) != manifest_candidate.get(field)
                    for field in immutable_fields
                ):
                    conflicting_event_keys.append(event_key)
                    continue
                if received_wall_ns < int(previous_manifest["first_received_wall_ns"]):
                    previous_manifest["first_received_wall_ns"] = received_wall_ns
                    previous_manifest["session_key"] = row.get("session_key")
                    previous_manifest["first_subscription_label"] = subscription_label

            if tx_succeeded:
                previous_carbon = carbon_by_key.get(event_key)
                if previous_carbon is None:
                    carbon_by_key[event_key] = carbon_candidate
                    accepted_counts[event_type] += 1
                elif previous_carbon != carbon_candidate:
                    conflicting_event_keys.append(event_key)
            elif previous_manifest is None:
                failed_tx_target_events += 1

    carbon_rows = [carbon_by_key[key] for key in sorted(carbon_by_key)]
    manifest_rows = [manifest_by_key[key] for key in sorted(manifest_by_key)]
    _write_jsonl(carbon_input_path, carbon_rows)
    _write_jsonl(manifest_path, manifest_rows)

    conflicts = tuple(sorted(set(conflicting_event_keys)))
    report = {
        "type": "helius_standard_wss_shadow_reduce",
        "version": REDUCER_VERSION,
        "trace_contract_valid": trace_contract_valid,
        "logs_notifications": len(logs_rows),
        "unique_notification_signatures": len(notification_signatures),
        "duplicate_notifications": duplicate_notifications,
        "contextual_target_events_observed": len(manifest_rows),
        "accepted_success_target_events": len(carbon_rows),
        "failed_transaction_target_events": sum(
            1 for item in manifest_rows if not item["transaction_succeeded"]
        ),
        "target_event_counts": dict(sorted(target_counts.items())),
        "accepted_event_counts": dict(sorted(accepted_counts.items())),
        "program_log_stack_errors": stack_errors,
        "successful_tx_stack_errors": successful_tx_stack_errors,
        "failed_tx_stack_errors": failed_tx_stack_errors,
        "stack_error_examples": stack_error_examples,
        "conflicting_event_keys": len(conflicts),
        "conflicting_event_key_examples": list(conflicts[:10]),
        "valid_for_carbon_decode": (
            trace_contract_valid
            and len(carbon_rows) > 0
            and successful_tx_stack_errors == 0
            and not conflicts
        ),
        "chain_complete_coverage_claimed": False,
    }
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reduce Helius Standard WSS shadow logs")
    parser.add_argument("--in", dest="trace_path", type=Path, required=True)
    parser.add_argument("--carbon-input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = reduce_shadow(
        trace_path=args.trace_path,
        carbon_input_path=args.carbon_input,
        manifest_path=args.manifest,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["trace_contract_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
