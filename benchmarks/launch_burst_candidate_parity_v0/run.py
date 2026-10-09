from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_matched_unit_coverage_v0.run import (
    _evidence_file,
    _nonnegative_int,
    _paired_rows,
    _read_json,
    _resolve_declared,
    _text,
)
from benchmarks.market_first_live_discovery_v0.contracts import (
    event_is_inside_discovery_window_v0,
)
from src.database import connection
from src.market_observation_store import ensure_market_observation_schema


CANDIDATE_PARITY_VERSION = "launch_burst_candidate_parity_v0_exact_anchor_identity"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_CANDIDATE_PARITY_V0"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_CANDIDATE_PARITY_V0"


def _db_anchor_ledger(acquisition_run_key: str) -> dict[tuple[str, str], dict[str, Any]]:
    ensure_market_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT event_key, token_mint, market_started_at, observed_at, venue, id
               FROM market_lifecycle_observations
               WHERE acquisition_run_key=? AND venue IN ('pump', 'pumpswap')
               ORDER BY observed_at, market_started_at, id""",
            (acquisition_run_key,),
        ).fetchall()
    anchors: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["token_mint"]), str(row["venue"]))
        if key in anchors:
            continue
        anchors[key] = {
            "token_mint": key[0],
            "venue": key[1],
            "event_key": str(row["event_key"]),
            "chain_t0": int(row["market_started_at"]),
            "observed_t0": int(row["observed_at"]),
            "sqlite_row_id": int(row["id"]),
        }
    return anchors


def _processed_anchor_ledger(
    live_report_path: Path,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    report_path = Path(live_report_path)
    live = _read_json(report_path)
    run = live.get("run") or {}
    if run.get("status") != "CLOSED":
        raise ValueError("candidate parity requires run.status=CLOSED")
    if live.get("valid_live_discovery") is not True:
        raise ValueError("candidate parity requires valid_live_discovery=True")
    discovery_start = int(live.get("discovery_start_wall_ns") or 0)
    discovery_close = int(live.get("discovery_close_wall_ns") or 0)
    if discovery_start <= 0 or discovery_close <= discovery_start:
        raise ValueError("candidate parity live report has invalid discovery bounds")

    artifacts = live.get("artifacts") or {}
    processed_root = _resolve_declared(report_path, artifacts.get("processed_chunks"))
    if not processed_root.is_dir():
        raise ValueError("processed chunks artifact is not a directory")

    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    pairing_errors: list[str] = []
    chunk_count = 0
    no_target_event_chunk_count = 0

    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        carbon_path = _evidence_file(chunk_dir, "carbon-canonical", required=False)
        if carbon_path is None:
            chunk_report_path = chunk_dir / "chunk-report.json"
            if not chunk_report_path.exists():
                raise ValueError(
                    f"missing carbon evidence without chunk report: {chunk_dir}"
                )
            chunk_report = _read_json(chunk_report_path)
            if chunk_report.get("status") != "NO_TARGET_EVENTS":
                raise ValueError(
                    f"missing carbon evidence not justified by NO_TARGET_EVENTS: {chunk_dir}"
                )
            no_target_event_chunk_count += 1
            chunk_count += 1
            continue

        manifest_path = _evidence_file(chunk_dir, "target-manifest", required=True)
        assert manifest_path is not None
        ordered, errors = _paired_rows(carbon_path, manifest_path)
        pairing_errors.extend(f"{chunk_dir.name}:{item}" for item in errors)

        for row, manifest in ordered:
            if row.get("status") != "decoded":
                continue
            event_type = _text(row, "event_type")
            if event_type not in {"pump_create", "pumpswap_create_pool"}:
                continue
            wall_ns = int(manifest["first_received_wall_ns"])
            if not event_is_inside_discovery_window_v0(
                wall_ns,
                discovery_start_wall_ns=discovery_start,
                discovery_close_wall_ns=discovery_close,
            ):
                continue
            event_key = _text(row, "event_key")
            chain_t0 = _nonnegative_int(row, "timestamp")
            if event_type == "pump_create":
                token_mint = _text(row, "mint")
                venue = "pump"
            else:
                token_mint = _text(row, "base_mint")
                venue = "pumpswap"
            if event_key is None or token_mint is None or chain_t0 is None:
                continue
            key = (token_mint, venue)
            candidates.setdefault(key, []).append(
                {
                    "token_mint": token_mint,
                    "venue": venue,
                    "event_key": event_key,
                    "chain_t0": int(chain_t0),
                    "observed_t0": wall_ns // 1_000_000_000,
                    "observed_wall_ns": wall_ns,
                }
            )
        chunk_count += 1

    if pairing_errors:
        raise RuntimeError(
            "processed evidence pairing errors: " + ";".join(pairing_errors[:10])
        )

    anchors: dict[tuple[str, str], dict[str, Any]] = {}
    same_second_multi_candidate_count = 0
    same_second_keys: list[str] = []
    for key, rows in candidates.items():
        rows.sort(key=lambda item: (item["observed_wall_ns"], item["event_key"]))
        anchors[key] = rows[0]
        first_second = int(rows[0]["observed_t0"])
        same_second = [item for item in rows if int(item["observed_t0"]) == first_second]
        if len(same_second) > 1:
            same_second_multi_candidate_count += 1
            same_second_keys.append(f"{key[0]}:{key[1]}")

    diagnostics = {
        "processed_chunk_count": chunk_count,
        "no_target_event_chunk_count": no_target_event_chunk_count,
        "pairing_error_count": 0,
        "same_second_multi_candidate_count": same_second_multi_candidate_count,
        "same_second_candidate_keys": sorted(same_second_keys),
    }
    return anchors, diagnostics


def run_candidate_parity_v0(
    *,
    acquisition_run_key: str,
    live_report_path: Path,
) -> dict[str, Any]:
    key = str(acquisition_run_key).strip()
    if not key:
        raise ValueError("acquisition_run_key cannot be empty")
    live = _read_json(Path(live_report_path))
    live_run_key = str((live.get("run") or {}).get("acquisition_run_key") or "")
    if live_run_key != key:
        raise ValueError("live report acquisition_run_key does not match requested run")

    db = _db_anchor_ledger(key)
    processed, diagnostics = _processed_anchor_ledger(Path(live_report_path))
    db_keys = set(db)
    processed_keys = set(processed)
    missing_in_db = sorted(processed_keys - db_keys)
    missing_in_processed = sorted(db_keys - processed_keys)

    mismatches: list[dict[str, Any]] = []
    exact_match_count = 0
    for candidate_key in sorted(db_keys & processed_keys):
        db_item = db[candidate_key]
        raw_item = processed[candidate_key]
        fields = {
            "event_key": db_item["event_key"] == raw_item["event_key"],
            "chain_t0": db_item["chain_t0"] == raw_item["chain_t0"],
            "observed_t0": db_item["observed_t0"] == raw_item["observed_t0"],
        }
        if all(fields.values()):
            exact_match_count += 1
            continue
        mismatches.append(
            {
                "token_mint": candidate_key[0],
                "venue": candidate_key[1],
                "field_match": fields,
                "db_anchor": {
                    "event_key": db_item["event_key"],
                    "chain_t0": db_item["chain_t0"],
                    "observed_t0": db_item["observed_t0"],
                },
                "processed_anchor": {
                    "event_key": raw_item["event_key"],
                    "chain_t0": raw_item["chain_t0"],
                    "observed_t0": raw_item["observed_t0"],
                },
            }
        )

    exact = not missing_in_db and not missing_in_processed and not mismatches
    return {
        "type": "launch_burst_candidate_parity",
        "version": CANDIDATE_PARITY_VERSION,
        "classification": PASS_CLASSIFICATION if exact else FAIL_CLASSIFICATION,
        "acquisition_run_key": key,
        "exact_match": exact,
        "db_anchor_count": len(db),
        "processed_anchor_count": len(processed),
        "exact_match_count": exact_match_count,
        "missing_in_db_count": len(missing_in_db),
        "missing_in_processed_count": len(missing_in_processed),
        "mismatch_count": len(mismatches),
        "missing_in_db": [
            {"token_mint": item[0], "venue": item[1]} for item in missing_in_db
        ],
        "missing_in_processed": [
            {"token_mint": item[0], "venue": item[1]} for item in missing_in_processed
        ],
        "mismatches": mismatches,
        "diagnostics": diagnostics,
        "scientific_lock": {
            "candidate_identity_only": True,
            "economic_outcomes_loaded": False,
            "return_values_reported": False,
            "candidate_thresholds_defined": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exact Launch Burst candidate-anchor parity between SQLite and processed evidence"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--live-report", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/launch_burst_candidate_parity_v0/report.json"),
    )
    args = parser.parse_args()
    result = run_candidate_parity_v0(
        acquisition_run_key=args.run_key,
        live_report_path=args.live_report,
    )
    _write_json(args.output, result)
    print(
        f"Launch Burst Candidate Parity V0 classification={result['classification']} "
        f"exact={result['exact_match']} mismatches={result['mismatch_count']}"
    )
    print(f"output={args.output}")
    return 0 if result["exact_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
