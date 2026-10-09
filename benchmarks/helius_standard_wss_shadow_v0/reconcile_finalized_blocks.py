from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib import error, parse, request

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
)

VERSION = "helius_standard_wss_finalized_block_reconciler_v1"
PROGRAMS = {
    "pump": PUMP_PROGRAM_ID,
    "pumpswap": PUMPSWAP_PROGRAM_ID,
}
DEFAULT_RPS = 5.0
DEFAULT_MAX_SUPPORTED_TRANSACTION_VERSION = 1


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


def _rpc_url(api_key: str) -> str:
    return "https://mainnet.helius-rpc.com/?api-key=" + parse.quote(api_key, safe="")


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Helius RPC returned non-object JSON")
    return parsed


def derive_shadow_slot_window(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    log_rows = [
        row
        for row in rows
        if row.get("type") == "logs_notification"
        and row.get("subscription_label") in {"pump_logs", "pumpswap_logs"}
        and isinstance(row.get("slot"), int)
        and not isinstance(row.get("slot"), bool)
        and isinstance(row.get("signature"), str)
        and bool(row.get("signature"))
    ]
    if not log_rows:
        raise ValueError("shadow contains no valid Pump/PumpSwap log notifications")

    slots = [int(row["slot"]) for row in log_rows]
    return {
        "min_slot": min(slots),
        "max_slot": max(slots),
        "log_notifications": len(log_rows),
        "unique_wss_signatures": len({str(row["signature"]) for row in log_rows}),
    }


def wss_signature_sets(
    rows: Iterable[dict[str, Any]], *, min_slot: int, max_slot: int
) -> dict[str, set[str]]:
    result = {name: set() for name in PROGRAMS}
    label_to_name = {"pump_logs": "pump", "pumpswap_logs": "pumpswap"}
    for row in rows:
        if row.get("type") != "logs_notification":
            continue
        name = label_to_name.get(str(row.get("subscription_label", "")))
        slot = row.get("slot")
        signature = row.get("signature")
        if (
            name is None
            or not isinstance(slot, int)
            or isinstance(slot, bool)
            or not min_slot <= slot <= max_slot
            or not isinstance(signature, str)
            or not signature
        ):
            continue
        result[name].add(signature)
    return result


def _account_pubkeys(transaction: dict[str, Any]) -> set[str]:
    keys = transaction.get("accountKeys")
    if not isinstance(keys, list):
        return set()
    out: set[str] = set()
    for item in keys:
        if isinstance(item, str) and item:
            out.add(item)
        elif isinstance(item, dict):
            pubkey = item.get("pubkey")
            if isinstance(pubkey, str) and pubkey:
                out.add(pubkey)
    return out


def extract_block_candidates(*, slot: int, block: dict[str, Any]) -> list[dict[str, Any]]:
    transactions = block.get("transactions")
    if not isinstance(transactions, list):
        return []
    block_time = block.get("blockTime")
    rows: list[dict[str, Any]] = []

    for index, entry in enumerate(transactions):
        if not isinstance(entry, dict):
            continue
        tx = entry.get("transaction")
        if not isinstance(tx, dict):
            continue
        signatures = tx.get("signatures")
        account_keys = _account_pubkeys(tx)
        if not isinstance(signatures, list) or not signatures or not account_keys:
            continue
        signature = signatures[0]
        if not isinstance(signature, str) or not signature:
            continue
        mentioned = tuple(
            name for name, program_id in PROGRAMS.items() if program_id in account_keys
        )
        if not mentioned:
            continue
        meta = entry.get("meta")
        err = meta.get("err") if isinstance(meta, dict) else None
        rows.append(
            {
                "type": "finalized_block_program_candidate",
                "version": VERSION,
                "slot": slot,
                "transaction_index": index,
                "signature": signature,
                "programs_mentioned": list(mentioned),
                "err": err,
                "transaction_succeeded": err is None,
                "block_time": block_time,
                "commitment": "finalized",
            }
        )
    return rows


def reconcile_signature_sets(
    *,
    wss_sets: dict[str, set[str]],
    truth_rows: Iterable[dict[str, Any]],
    complete_truth_enumeration: bool,
) -> dict[str, Any]:
    truth_sets: dict[str, set[str]] = {name: set() for name in PROGRAMS}
    success_truth_sets: dict[str, set[str]] = {name: set() for name in PROGRAMS}
    for row in truth_rows:
        signature = row.get("signature")
        mentioned = row.get("programs_mentioned")
        if not isinstance(signature, str) or not isinstance(mentioned, list):
            continue
        for name in PROGRAMS:
            if name in mentioned:
                truth_sets[name].add(signature)
                if row.get("transaction_succeeded") is True:
                    success_truth_sets[name].add(signature)

    per_program: dict[str, Any] = {}
    for name in PROGRAMS:
        wss = set(wss_sets.get(name, set()))
        truth = truth_sets[name]
        success_truth = success_truth_sets[name]

        if not complete_truth_enumeration:
            per_program[name] = {
                "wss_processed_signatures": len(wss),
                "finalized_truth_signatures": None,
                "finalized_success_truth_signatures": None,
                "wss_and_finalized_intersection": None,
                "finalized_truth_missed_by_wss": None,
                "wss_processed_absent_from_finalized_truth": None,
                "finalized_success_seen_by_wss": None,
                "finalized_signature_recall_pct": None,
                "finalized_success_signature_recall_pct": None,
                "missed_finalized_examples": [],
                "processed_absent_finalized_examples": [],
            }
            continue

        intersection = wss & truth
        missed = truth - wss
        not_finalized = wss - truth
        success_seen = wss & success_truth
        per_program[name] = {
            "wss_processed_signatures": len(wss),
            "finalized_truth_signatures": len(truth),
            "finalized_success_truth_signatures": len(success_truth),
            "wss_and_finalized_intersection": len(intersection),
            "finalized_truth_missed_by_wss": len(missed),
            "wss_processed_absent_from_finalized_truth": len(not_finalized),
            "finalized_success_seen_by_wss": len(success_seen),
            "finalized_signature_recall_pct": (
                None if not truth else 100.0 * len(intersection) / len(truth)
            ),
            "finalized_success_signature_recall_pct": (
                None if not success_truth else 100.0 * len(success_seen) / len(success_truth)
            ),
            "missed_finalized_examples": sorted(missed)[:20],
            "processed_absent_finalized_examples": sorted(not_finalized)[:20],
        }
    return per_program


class _Pacer:
    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be positive")
        self.interval = 1.0 / rps
        self.last_started: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self.last_started is not None:
            remaining = self.interval - (now - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()


def _rpc_with_retry(
    *,
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    max_attempts: int,
    pacer: _Pacer,
    post_json: Callable[..., dict[str, Any]] = _post_json,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        pacer.wait()
        try:
            response = post_json(url, payload, timeout_seconds=timeout_seconds)
        except (error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append(f"attempt={attempt} {type(exc).__name__}: {exc}")
        else:
            if response.get("error") is None:
                return response, errors
            errors.append(f"attempt={attempt} rpc_error={response.get('error')!r}")
        if attempt < max_attempts:
            time.sleep(min(4.0, 0.5 * (2 ** (attempt - 1))))
    return None, errors


def reconcile_finalized_blocks(
    *,
    shadow_path: Path,
    candidates_out: Path,
    api_key: str,
    rps: float = DEFAULT_RPS,
    timeout_seconds: float = 30.0,
    max_attempts: int = 3,
    max_supported_transaction_version: int = DEFAULT_MAX_SUPPORTED_TRANSACTION_VERSION,
) -> dict[str, Any]:
    shadow_rows = _jsonl(shadow_path)
    window = derive_shadow_slot_window(shadow_rows)
    min_slot = int(window["min_slot"])
    max_slot = int(window["max_slot"])
    wss_sets = wss_signature_sets(shadow_rows, min_slot=min_slot, max_slot=max_slot)

    url = _rpc_url(api_key)
    pacer = _Pacer(rps)
    request_errors: list[dict[str, Any]] = []

    blocks_payload = {
        "jsonrpc": "2.0",
        "id": "wss-truth-blocks",
        "method": "getBlocks",
        "params": [min_slot, max_slot, {"commitment": "finalized"}],
    }
    blocks_response, errors = _rpc_with_retry(
        url=url,
        payload=blocks_payload,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        pacer=pacer,
    )
    if blocks_response is None:
        request_errors.append({"method": "getBlocks", "errors": errors})
        finalized_slots: list[int] = []
    else:
        raw_slots = blocks_response.get("result")
        finalized_slots = (
            [int(slot) for slot in raw_slots if isinstance(slot, int) and not isinstance(slot, bool)]
            if isinstance(raw_slots, list)
            else []
        )
        if not isinstance(raw_slots, list):
            request_errors.append({"method": "getBlocks", "errors": ["invalid_result"]})

    candidates: list[dict[str, Any]] = []
    fetched_slots: list[int] = []
    null_slots: list[int] = []
    for slot in finalized_slots:
        payload = {
            "jsonrpc": "2.0",
            "id": f"wss-truth-block-{slot}",
            "method": "getBlock",
            "params": [
                slot,
                {
                    "commitment": "finalized",
                    "encoding": "jsonParsed",
                    "transactionDetails": "accounts",
                    "maxSupportedTransactionVersion": max_supported_transaction_version,
                    "rewards": False,
                },
            ],
        }
        response, errors = _rpc_with_retry(
            url=url,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            pacer=pacer,
        )
        if response is None:
            request_errors.append({"method": "getBlock", "slot": slot, "errors": errors})
            continue
        block = response.get("result")
        if block is None:
            null_slots.append(slot)
            continue
        if not isinstance(block, dict):
            request_errors.append({"method": "getBlock", "slot": slot, "errors": ["invalid_result"]})
            continue
        fetched_slots.append(slot)
        candidates.extend(extract_block_candidates(slot=slot, block=block))

    _write_jsonl(candidates_out, candidates)

    complete_truth = (
        blocks_response is not None
        and len(finalized_slots) > 0
        and not request_errors
        and not null_slots
        and len(fetched_slots) == len(finalized_slots)
    )
    per_program = reconcile_signature_sets(
        wss_sets=wss_sets,
        truth_rows=candidates,
        complete_truth_enumeration=complete_truth,
    )
    any_missed = complete_truth and any(
        int(item["finalized_truth_missed_by_wss"]) > 0
        for item in per_program.values()
        if item["finalized_truth_missed_by_wss"] is not None
    )

    return {
        "type": "helius_standard_wss_finalized_block_reconciliation",
        "version": VERSION,
        "source_shadow": str(shadow_path),
        "reference_provider": "helius_free_rpc",
        "reference_commitment": "finalized",
        "reference_method": "getBlocks + getBlock(transactionDetails=accounts)",
        "min_slot": min_slot,
        "max_slot": max_slot,
        "slot_span_inclusive": max_slot - min_slot + 1,
        "wss_log_notifications": window["log_notifications"],
        "wss_unique_signatures": window["unique_wss_signatures"],
        "finalized_slots": len(finalized_slots),
        "fetched_finalized_slots": len(fetched_slots),
        "null_finalized_slots": len(null_slots),
        "candidate_transactions": len(candidates),
        "request_errors": len(request_errors),
        "request_error_examples": request_errors[:10],
        "complete_truth_enumeration": complete_truth,
        "chain_complete_coverage_claimed_for_wss": False,
        "economic_edge_evaluated": False,
        "per_program": per_program,
        "classification": (
            "PASS_FINALIZED_SIGNATURE_RECALL_REFERENCE"
            if complete_truth and not any_missed
            else (
                "MEASURED_WSS_FINALIZED_SIGNATURE_GAPS"
                if complete_truth
                else "INCOMPLETE_FINALIZED_REFERENCE"
            )
        ),
        "notes": [
            "The finalized block scan is an independent slot-bounded signature reference, not an economic test.",
            "WSS uses processed commitment; signatures absent from finalized blocks are not automatically labeled rollbacks without further transaction-level audit.",
            "Program-account mention is compared to the WSS logsSubscribe mentions boundary; target instruction/event recall requires a later semantic audit.",
            "Any getBlock/getBlocks gap makes all truth-comparison counts and recall percentages unavailable rather than treating missing reference data as zero.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile Standard WSS program-mention signatures against finalized blocks"
    )
    parser.add_argument("--shadow", type=Path, required=True)
    parser.add_argument("--candidates-out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--max-supported-transaction-version",
        type=int,
        default=DEFAULT_MAX_SUPPORTED_TRANSACTION_VERSION,
    )
    args = parser.parse_args()

    api_key = os.environ.get("HELIUS_API_KEY")
    if not api_key:
        raise SystemExit("HELIUS_API_KEY is required")
    if args.max_attempts <= 0:
        raise SystemExit("--max-attempts must be positive")

    report = reconcile_finalized_blocks(
        shadow_path=args.shadow,
        candidates_out=args.candidates_out,
        api_key=api_key,
        rps=args.rps,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        max_supported_transaction_version=args.max_supported_transaction_version,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["complete_truth_enumeration"] else 1


if __name__ == "__main__":
    raise SystemExit(main())