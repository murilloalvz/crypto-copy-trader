from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Iterable

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

PUMP_TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
PUMP_CREATE_EVENT_DISCRIMINATOR = bytes([27, 114, 169, 77, 222, 235, 99, 118])
PUMPSWAP_BUY_EVENT_DISCRIMINATOR = bytes([103, 244, 82, 31, 44, 245, 119, 119])
PUMPSWAP_SELL_EVENT_DISCRIMINATOR = bytes([62, 47, 55, 10, 165, 3, 220, 42])
PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR = bytes([177, 49, 12, 210, 160, 118, 167, 116])

EVENTS_BY_PROGRAM = {
    PUMP_PROGRAM_ID: {
        PUMP_TRADE_EVENT_DISCRIMINATOR: "pump_trade",
        PUMP_CREATE_EVENT_DISCRIMINATOR: "pump_create",
    },
    PUMPSWAP_PROGRAM_ID: {
        PUMPSWAP_BUY_EVENT_DISCRIMINATOR: "pumpswap_buy",
        PUMPSWAP_SELL_EVENT_DISCRIMINATOR: "pumpswap_sell",
        PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR: "pumpswap_create_pool",
    },
}

FROZEN_EXPECTED_COUNTS = Counter(
    {
        "pump_trade": 79,
        "pump_create": 2,
        "pumpswap_buy": 29,
        "pumpswap_sell": 40,
    }
)
FROZEN_EXPECTED_TOTAL = 150

_INVOKE_RE = re.compile(r"^Program ([1-9A-HJ-NP-Za-km-z]+) invoke \[\d+\]$")
_EXIT_RE = re.compile(r"^Program ([1-9A-HJ-NP-Za-km-z]+) (?:success|failed:.*)$")
_DATA_PREFIX = "Program data: "

COMMON_COMPARE_FIELDS = (
    "event_key",
    "signature",
    "slot",
    "log_index",
    "program_id",
    "event_type",
)
EVENT_COMPARE_FIELDS = {
    "pump_trade": (
        "mint",
        "side",
        "wallet",
        "timestamp",
        "sol_amount_raw",
        "token_amount_raw",
    ),
    "pump_create": (
        "mint",
        "bonding_curve",
        "user",
        "creator",
        "timestamp",
    ),
    "pumpswap_buy": (
        "side",
        "pool",
        "user",
        "timestamp",
        "base_amount_raw",
        "quote_amount_raw",
    ),
    "pumpswap_sell": (
        "side",
        "pool",
        "user",
        "timestamp",
        "base_amount_raw",
        "quote_amount_raw",
    ),
    "pumpswap_create_pool": (
        "pool",
        "creator",
        "base_mint",
        "quote_mint",
        "base_mint_decimals",
        "quote_mint_decimals",
        "timestamp",
    ),
}


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


def extract_contextual_target_payloads(
    logs: Iterable[Any],
) -> tuple[list[dict[str, Any]], int]:
    """Return target Program-data payloads only while Pump/PumpSwap is the active program.

    Solana runtime logs expose nested invocation context. We track that stack so an event
    discriminator emitted by some other CPI program cannot be misclassified as Pump/PumpSwap.
    """
    stack: list[str] = []
    events: list[dict[str, Any]] = []
    stack_errors = 0

    for log_index, raw_line in enumerate(logs):
        line = str(raw_line)
        invoke = _INVOKE_RE.match(line)
        if invoke is not None:
            stack.append(invoke.group(1))
            continue

        if line.startswith(_DATA_PREFIX):
            if not stack:
                continue
            program_id = stack[-1]
            program_events = EVENTS_BY_PROGRAM.get(program_id)
            if program_events is None:
                continue
            encoded = line[len(_DATA_PREFIX) :].strip()
            try:
                payload = base64.b64decode(encoded, validate=True)
            except Exception:
                continue
            event_type = program_events.get(payload[:8])
            if event_type is None:
                continue
            events.append(
                {
                    "log_index": log_index,
                    "program_id": program_id,
                    "event_type": event_type,
                    "payload": payload,
                }
            )
            continue

        exit_match = _EXIT_RE.match(line)
        if exit_match is not None:
            program_id = exit_match.group(1)
            if stack and stack[-1] == program_id:
                stack.pop()
            else:
                stack_errors += 1
                if program_id in stack:
                    while stack and stack[-1] != program_id:
                        stack.pop()
                    if stack and stack[-1] == program_id:
                        stack.pop()

    if stack:
        stack_errors += len(stack)
    return events, stack_errors


def _decode_ours(program_id: str, event_type: str, payload: bytes) -> dict[str, Any]:
    if program_id == PUMP_PROGRAM_ID:
        from src.pump_bonding_stream import (
            decode_pump_create_event_payload,
            decode_pump_trade_event_payload,
        )

        if event_type == "pump_trade":
            event = decode_pump_trade_event_payload(payload)
            if event is None:
                raise ValueError("our Pump TradeEvent decoder returned None")
            return {
                "mint": event.mint,
                "side": "buy" if event.is_buy else "sell",
                "wallet": event.user,
                "timestamp": event.timestamp,
                "sol_amount_raw": event.sol_amount,
                "token_amount_raw": event.token_amount,
            }
        if event_type == "pump_create":
            event = decode_pump_create_event_payload(payload)
            if event is None:
                raise ValueError("our Pump CreateEvent decoder returned None")
            return {
                "mint": event.mint,
                "bonding_curve": event.bonding_curve,
                "user": event.user,
                "creator": event.creator,
                "timestamp": event.timestamp,
            }

    if program_id == PUMPSWAP_PROGRAM_ID:
        from src.pumpswap_stream import (
            decode_pumpswap_buy_event_payload,
            decode_pumpswap_create_pool_event_payload,
            decode_pumpswap_sell_event_payload,
        )

        if event_type == "pumpswap_buy":
            event = decode_pumpswap_buy_event_payload(payload)
        elif event_type == "pumpswap_sell":
            event = decode_pumpswap_sell_event_payload(payload)
        elif event_type == "pumpswap_create_pool":
            event = decode_pumpswap_create_pool_event_payload(payload)
        else:
            event = None

        if event is None:
            raise ValueError(f"our {event_type} decoder returned None")

        if event_type in {"pumpswap_buy", "pumpswap_sell"}:
            return {
                "side": event.side,
                "pool": event.pool,
                "user": event.user,
                "timestamp": event.timestamp,
                "base_amount_raw": event.base_amount_raw,
                "quote_amount_raw": event.quote_amount_raw,
            }

        return {
            "pool": event.pool,
            "creator": event.creator,
            "base_mint": event.base_mint,
            "quote_mint": event.quote_mint,
            "base_mint_decimals": event.base_mint_decimals,
            "quote_mint_decimals": event.quote_mint_decimals,
            "timestamp": event.timestamp,
        }

    raise ValueError(f"unsupported program/event pair: {program_id} {event_type}")


def prepare(
    corpus_path: Path,
    carbon_input_path: Path,
    ours_output_path: Path,
    *,
    enforce_frozen_counts: bool = True,
) -> dict[str, Any]:
    rows = _jsonl(corpus_path)
    records = [row for row in rows if row.get("type") == "raw_transaction"]

    carbon_rows: list[dict[str, Any]] = []
    ours_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    target_tx_signatures: set[str] = set()
    stack_errors = 0
    decode_errors: list[dict[str, Any]] = []

    for record in records:
        signature = str(record["signature"])
        result = record["result"]
        slot = int(result["slot"])
        logs = (result.get("meta") or {}).get("logMessages") or []
        contextual_events, record_stack_errors = extract_contextual_target_payloads(logs)
        stack_errors += record_stack_errors

        for target in contextual_events:
            log_index = int(target["log_index"])
            program_id = str(target["program_id"])
            event_type = str(target["event_type"])
            payload = bytes(target["payload"])
            event_key = f"{signature}:{log_index}:{event_type}"
            input_row = {
                "type": "carbon_decoder_input",
                "event_key": event_key,
                "signature": signature,
                "slot": slot,
                "log_index": log_index,
                "program_id": program_id,
                "event_type": event_type,
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }
            carbon_rows.append(input_row)
            counts[event_type] += 1
            target_tx_signatures.add(signature)
            try:
                decoded = _decode_ours(program_id, event_type, payload)
            except Exception as exc:
                decode_errors.append(
                    {
                        "event_key": event_key,
                        "event_type": event_type,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            ours_rows.append(
                {
                    "type": "ours_canonical_event",
                    "event_key": event_key,
                    "signature": signature,
                    "slot": slot,
                    "log_index": log_index,
                    "program_id": program_id,
                    "event_type": event_type,
                    **decoded,
                }
            )

    _write_jsonl(carbon_input_path, carbon_rows)
    _write_jsonl(ours_output_path, ours_rows)

    frozen_counts_match = counts == FROZEN_EXPECTED_COUNTS
    valid = (
        len(carbon_rows) > 0
        and len(carbon_rows) == len(ours_rows)
        and not decode_errors
        and stack_errors == 0
        and (
            not enforce_frozen_counts
            or (len(carbon_rows) == FROZEN_EXPECTED_TOTAL and frozen_counts_match)
        )
    )
    return {
        "type": "carbon_decoder_parity_prepare",
        "records": len(records),
        "contextual_target_transactions": len(target_tx_signatures),
        "contextual_target_events": len(carbon_rows),
        "contextual_target_event_counts": dict(sorted(counts.items())),
        "our_decoded_events": len(ours_rows),
        "our_decode_errors": len(decode_errors),
        "our_decode_error_examples": decode_errors[:10],
        "program_log_stack_errors": stack_errors,
        "frozen_expected_total": FROZEN_EXPECTED_TOTAL,
        "frozen_expected_counts": dict(sorted(FROZEN_EXPECTED_COUNTS.items())),
        "frozen_counts_match": frozen_counts_match,
        "valid_for_carbon_decoder_run": valid,
    }


def _index_unique(
    rows: Iterable[dict[str, Any]], row_type: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        if row.get("type") != row_type:
            continue
        key = str(row.get("event_key", ""))
        if not key:
            continue
        if key in indexed:
            duplicates.append(key)
        indexed[key] = row
    return indexed, duplicates


def compare(ours_path: Path, carbon_path: Path) -> dict[str, Any]:
    ours_rows = _jsonl(ours_path)
    carbon_rows = _jsonl(carbon_path)
    ours, ours_duplicates = _index_unique(ours_rows, "ours_canonical_event")
    carbon, carbon_duplicates = _index_unique(carbon_rows, "carbon_canonical_event")
    footers = [row for row in carbon_rows if row.get("type") == "carbon_decoder_footer"]

    exact = 0
    mismatches: list[dict[str, Any]] = []
    per_type_total: Counter[str] = Counter()
    per_type_exact: Counter[str] = Counter()

    for key, expected in ours.items():
        event_type = str(expected["event_type"])
        per_type_total[event_type] += 1
        actual = carbon.get(key)
        if actual is None:
            mismatches.append({"event_key": key, "reason": "missing_carbon_event"})
            continue
        if actual.get("status") != "decoded":
            mismatches.append(
                {
                    "event_key": key,
                    "reason": "carbon_decode_failed",
                    "carbon_error": actual.get("error"),
                }
            )
            continue

        fields = COMMON_COMPARE_FIELDS + EVENT_COMPARE_FIELDS[event_type]
        field_mismatches = {
            field: {"ours": expected.get(field), "carbon": actual.get(field)}
            for field in fields
            if expected.get(field) != actual.get(field)
        }
        if field_mismatches:
            mismatches.append(
                {
                    "event_key": key,
                    "reason": "field_mismatch",
                    "fields": field_mismatches,
                }
            )
            continue
        exact += 1
        per_type_exact[event_type] += 1

    extra_carbon = sorted(set(carbon) - set(ours))
    missing_carbon = sorted(set(ours) - set(carbon))
    parity_pct = 0.0 if not ours else (100.0 * exact / len(ours))
    footer = footers[0] if len(footers) == 1 else None
    footer_valid = (
        footer is not None
        and footer.get("carbon_decoder_version") == "2.0.0"
        and int(footer.get("input_events", -1)) == len(ours)
        and int(footer.get("output_events", -1)) == len(carbon)
    )

    per_type = {}
    for event_type in sorted(per_type_total):
        total = per_type_total[event_type]
        exact_count = per_type_exact[event_type]
        per_type[event_type] = {
            "total": total,
            "exact": exact_count,
            "parity_pct": 100.0 * exact_count / total if total else 0.0,
        }

    passed = (
        len(ours) == FROZEN_EXPECTED_TOTAL
        and exact == len(ours)
        and not mismatches
        and not extra_carbon
        and not missing_carbon
        and not ours_duplicates
        and not carbon_duplicates
        and footer_valid
    )
    return {
        "type": "carbon_decoder_parity_result",
        "frozen_expected_events": FROZEN_EXPECTED_TOTAL,
        "ours_events": len(ours),
        "carbon_events": len(carbon),
        "exact_events": exact,
        "canonical_event_parity_pct": parity_pct,
        "per_event_type": per_type,
        "missing_carbon_events": len(missing_carbon),
        "extra_carbon_events": len(extra_carbon),
        "ours_duplicate_event_keys": len(ours_duplicates),
        "carbon_duplicate_event_keys": len(carbon_duplicates),
        "carbon_footer_count": len(footers),
        "carbon_footer_valid": footer_valid,
        "mismatch_examples": mismatches[:20],
        "classification": (
            "PASS_CARBON_DECODER_PARITY_V1"
            if passed
            else "FAIL_CARBON_DECODER_PARITY_V1"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and compare same-payload Pump/PumpSwap decoder parity against Carbon."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--corpus", required=True, type=Path)
    prepare_parser.add_argument("--carbon-input", required=True, type=Path)
    prepare_parser.add_argument("--ours-out", required=True, type=Path)
    prepare_parser.add_argument(
        "--allow-nonfrozen-counts",
        action="store_true",
        help="Do not require the frozen 150-event corpus counts.",
    )

    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--ours", required=True, type=Path)
    compare_parser.add_argument("--carbon", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        summary = prepare(
            args.corpus,
            args.carbon_input,
            args.ours_out,
            enforce_frozen_counts=not args.allow_nonfrozen_counts,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["valid_for_carbon_decoder_run"] else 2

    summary = compare(args.ours, args.carbon)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["classification"] == "PASS_CARBON_DECODER_PARITY_V1" else 3


if __name__ == "__main__":
    raise SystemExit(main())
