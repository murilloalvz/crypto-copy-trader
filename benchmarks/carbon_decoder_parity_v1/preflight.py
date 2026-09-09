from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
from pathlib import Path
from typing import Any

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

PUMP_TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
PUMP_CREATE_EVENT_DISCRIMINATOR = bytes([27, 114, 169, 77, 222, 235, 99, 118])
PUMPSWAP_BUY_EVENT_DISCRIMINATOR = bytes([103, 244, 82, 31, 44, 245, 119, 119])
PUMPSWAP_SELL_EVENT_DISCRIMINATOR = bytes([62, 47, 55, 10, 165, 3, 220, 42])
PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR = bytes([177, 49, 12, 210, 160, 118, 167, 116])

EVENT_BY_DISCRIMINATOR = {
    PUMP_TRADE_EVENT_DISCRIMINATOR: "pump_trade",
    PUMP_CREATE_EVENT_DISCRIMINATOR: "pump_create",
    PUMPSWAP_BUY_EVENT_DISCRIMINATOR: "pumpswap_buy",
    PUMPSWAP_SELL_EVENT_DISCRIMINATOR: "pumpswap_sell",
    PUMPSWAP_CREATE_POOL_EVENT_DISCRIMINATOR: "pumpswap_create_pool",
}


def _keys(result: dict[str, Any]) -> list[str]:
    message = result["transaction"]["message"]
    keys: list[str] = []
    for raw in message.get("accountKeys") or []:
        keys.append(str(raw.get("pubkey")) if isinstance(raw, dict) else str(raw))
    loaded = (result.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(str(x) for x in (loaded.get("writable") or []))
    keys.extend(str(x) for x in (loaded.get("readonly") or []))
    return keys


def _program_id(ix: dict[str, Any], keys: list[str]) -> str | None:
    if ix.get("programId") is not None:
        return str(ix["programId"])
    index = ix.get("programIdIndex")
    if isinstance(index, int) and 0 <= index < len(keys):
        return keys[index]
    return None


def _program_data_events(logs: list[Any]) -> list[str]:
    output: list[str] = []
    prefix = "Program data: "
    for item in logs:
        line = str(item)
        if not line.startswith(prefix):
            continue
        try:
            payload = base64.b64decode(line[len(prefix):].strip(), validate=True)
        except Exception:
            continue
        event = EVENT_BY_DISCRIMINATOR.get(payload[:8])
        if event is not None:
            output.append(event)
    return output


def inspect_record(record: dict[str, Any]) -> dict[str, Any]:
    result = record["result"]
    keys = _keys(result)
    top = result["transaction"]["message"].get("instructions") or []
    inner = [
        ix
        for group in ((result.get("meta") or {}).get("innerInstructions") or [])
        for ix in (group.get("instructions") or [])
    ]
    top_programs = [_program_id(ix, keys) for ix in top]
    inner_programs = [_program_id(ix, keys) for ix in inner]
    events = _program_data_events((result.get("meta") or {}).get("logMessages") or [])
    return {
        "signature": record["signature"],
        "venues": list(record.get("venues") or []),
        "slot": result.get("slot"),
        "version": result.get("version"),
        "pump_top_invocations": sum(p == PUMP_PROGRAM_ID for p in top_programs),
        "pump_inner_invocations": sum(p == PUMP_PROGRAM_ID for p in inner_programs),
        "pumpswap_top_invocations": sum(p == PUMPSWAP_PROGRAM_ID for p in top_programs),
        "pumpswap_inner_invocations": sum(p == PUMPSWAP_PROGRAM_ID for p in inner_programs),
        "target_events": events,
    }


def analyze(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = [row for row in rows if row.get("type") == "raw_transaction"]
    signatures = [str(row.get("signature")) for row in records]
    duplicate_signatures = len(signatures) - len(set(signatures))
    slot_mismatches = 0
    block_time_mismatches = 0
    transaction_signature_mismatches = 0
    failed_transactions = 0
    manifest: list[dict[str, Any]] = []
    for row in records:
        result = row["result"]
        if row.get("signature_slot") != result.get("slot"):
            slot_mismatches += 1
        if row.get("signature_block_time") != result.get("blockTime"):
            block_time_mismatches += 1
        tx_sigs = (result.get("transaction") or {}).get("signatures") or []
        if not tx_sigs or tx_sigs[0] != row.get("signature"):
            transaction_signature_mismatches += 1
        if (result.get("meta") or {}).get("err") is not None:
            failed_transactions += 1
        manifest.append(inspect_record(row))

    pump_invoked = sum((x["pump_top_invocations"] + x["pump_inner_invocations"]) > 0 for x in manifest)
    pumpswap_invoked = sum((x["pumpswap_top_invocations"] + x["pumpswap_inner_invocations"]) > 0 for x in manifest)
    event_counts = Counter(event for x in manifest for event in x["target_events"])
    target_transactions = sum(bool(x["target_events"]) for x in manifest)
    summary = {
        "type": "carbon_decoder_parity_preflight",
        "records": len(records),
        "unique_signatures": len(set(signatures)),
        "duplicate_signatures": duplicate_signatures,
        "slot_mismatches": slot_mismatches,
        "block_time_mismatches": block_time_mismatches,
        "transaction_signature_mismatches": transaction_signature_mismatches,
        "failed_transactions": failed_transactions,
        "pump_actual_invocation_transactions": pump_invoked,
        "pumpswap_actual_invocation_transactions": pumpswap_invoked,
        "target_event_transactions": target_transactions,
        "target_events": dict(sorted(event_counts.items())),
        "target_event_count": sum(event_counts.values()),
        "valid_for_event_parity": (
            len(records) > 0
            and duplicate_signatures == 0
            and slot_mismatches == 0
            and block_time_mismatches == 0
            and transaction_signature_mismatches == 0
            and failed_transactions == 0
            and target_transactions > 0
        ),
    }
    return summary, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a raw corpus and build the strict Pump/PumpSwap event-parity manifest.")
    parser.add_argument("--in", dest="input_path", required=True, type=Path)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()
    summary, manifest = analyze(args.input_path)
    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest_out.open("w", encoding="utf-8", newline="\n") as handle:
            for row in manifest:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid_for_event_parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
