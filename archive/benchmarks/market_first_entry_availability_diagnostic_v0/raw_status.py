from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


VERSION = "market_first_entry_availability_raw_status_v0"
PASS = "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_RAW_STATUS_V0"


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


def _status_text(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "<MISSING>"


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_counts = Counter(_status_text(row.get("collection_entry_status")) for row in rows)
    family_counts = Counter(str(row.get("collection_status_family") or "<MISSING>") for row in rows)
    key_presence: Counter[str] = Counter()
    for row in rows:
        for key in row.get("original_collection_keys") or []:
            key_presence[str(key)] += 1
    provider_started = [row for row in rows if row.get("provider_calls_started") is True]
    return {
        "count": len(rows),
        "raw_collection_entry_status_counts": dict(sorted(raw_counts.items())),
        "collection_status_family_counts": dict(sorted(family_counts.items())),
        "original_collection_key_presence_counts": dict(sorted(key_presence.items())),
        "provider_calls_started_true": len(provider_started),
        "provider_calls_started_false": sum(row.get("provider_calls_started") is False for row in rows),
        "provider_started_but_cutoff_delay_missing": sum(
            row.get("provider_calls_started") is True and row.get("provider_start_delay_after_cutoff_ms") is None
            for row in rows
        ),
        "provider_started_but_ready_delay_missing": sum(
            row.get("provider_calls_started") is True and row.get("provider_start_delay_after_ready_ms") is None
            for row in rows
        ),
    }


def run_raw_status_v0(*, run_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    source_path = run_dir / "market-first-entry-availability-diagnostic-v0.json"
    route_input_path = run_dir / "route-input-v2.json"
    for path in (source_path, route_input_path):
        if not path.is_file():
            raise ValueError(f"required availability raw-status source missing: {path}")

    source = _read_json(source_path)
    route_input = _read_json(route_input_path)
    if source.get("classification") != "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_DIAGNOSTIC_V0":
        raise ValueError("availability diagnostic source is not PASS")
    rows = [row for row in source.get("rows") or [] if isinstance(row, dict)]
    if not rows:
        raise ValueError("availability diagnostic contains no rows")

    episodes = {
        str(row.get("episode_key") or ""): row
        for row in route_input.get("episodes") or []
        if isinstance(row, dict)
    }
    enriched: list[dict[str, Any]] = []
    missing_episode_keys: list[str] = []
    for row in rows:
        episode_key = str(row.get("episode_key") or "")
        episode = episodes.get(episode_key)
        if episode is None:
            missing_episode_keys.append(episode_key)
            continue
        collection = episode.get("collection")
        if not isinstance(collection, dict):
            collection = {}
        raw_status = collection.get("entry_status")
        if _status_text(raw_status) != _status_text(row.get("collection_entry_status")):
            raise ValueError(f"collection entry_status parity failed for {episode_key}")
        enriched.append(
            {
                **row,
                "original_collection_keys": sorted(str(key) for key in collection.keys()),
            }
        )
    if missing_episode_keys:
        raise ValueError("availability raw-status episode join failed: " + ";".join(missing_episode_keys[:10]))

    baseline = [row for row in enriched if row.get("baseline_admitted") is True]
    sniper = [row for row in baseline if row.get("sniper_selected") is True]
    baseline_unavailable = [row for row in baseline if row.get("entry_group") == "ENTRY_UNAVAILABLE"]
    sniper_unavailable = [row for row in sniper if row.get("entry_group") == "ENTRY_UNAVAILABLE"]

    report = {
        "type": "market_first_entry_availability_raw_status_report_v0",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "SYSTEMS_EXECUTION_ROOT_CAUSE_DIAGNOSTIC_ONLY",
        "source_artifact": str(source_path),
        "route_input_source": str(route_input_path),
        "source_integrity": {
            **dict(source.get("source_integrity") or {}),
            "raw_status_route_input_join_exact": len(enriched) == len(rows),
            "collection_entry_status_parity": True,
        },
        "selector_changed": False,
        "provider_collection_metadata_used_as_selector_feature": False,
        "cohorts": {
            "baseline": _cohort(baseline),
            "sniper_selected": _cohort(sniper),
            "baseline_entry_unavailable": _cohort(baseline_unavailable),
            "sniper_entry_unavailable": _cohort(sniper_unavailable),
        },
        "interpretation": (
            "Raw collection entry_status values and original collection key presence are surfaced only to open the prior "
            "OTHER_COLLECTION_STATUS bucket and audit whether historical timing metadata actually exists. These post-decision "
            "execution diagnostics are forbidden as Market-First selector evidence."
        ),
    }
    destination = output_path or (run_dir / "market-first-entry-availability-raw-status-v0.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "source_integrity": report.get("source_integrity"),
        "baseline_entry_unavailable": (report.get("cohorts") or {}).get("baseline_entry_unavailable"),
        "sniper_entry_unavailable": (report.get("cohorts") or {}).get("sniper_entry_unavailable"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Surface raw ENTRY_UNAVAILABLE collection statuses")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_raw_status_v0(run_dir=args.run_dir, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_ENTRY_AVAILABILITY_RAW_STATUS_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
