from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_shadow_v0.source_admissibility import evaluate_burst_source


def _ended_wall_ns(report_path: Path) -> int:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    acquisition = payload.get("acquisition") or {}
    value = acquisition.get("ended_wall_ns")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def find_burst_sources(artifacts_root: Path) -> list[dict[str, Any]]:
    root = Path(artifacts_root)
    if not root.is_dir():
        raise ValueError(f"artifacts root is not a directory: {root}")

    rows: list[dict[str, Any]] = []
    for report_path in sorted(root.rglob("report.json")):
        try:
            result = evaluate_burst_source(report_path)
        except Exception as exc:
            rows.append(
                {
                    "report_path": str(report_path.resolve()),
                    "burst_source_admissible": False,
                    "original_run_status": None,
                    "acquisition_run_key": None,
                    "ended_wall_ns": _ended_wall_ns(report_path),
                    "failed_gates": [f"evaluator_error:{type(exc).__name__}:{exc}"],
                }
            )
            continue
        rows.append(
            {
                "report_path": str(report_path.resolve()),
                "burst_source_admissible": result.get("burst_source_admissible") is True,
                "original_run_status": result.get("original_run_status"),
                "acquisition_run_key": result.get("acquisition_run_key"),
                "ended_wall_ns": _ended_wall_ns(report_path),
                "failed_gates": list(result.get("failed_gates") or []),
                "resolution_errors": list(result.get("resolution_errors") or []),
            }
        )

    rows.sort(
        key=lambda row: (
            row.get("burst_source_admissible") is True,
            str(row.get("original_run_status") or "") == "CLOSED",
            int(row.get("ended_wall_ns") or 0),
            str(row.get("report_path") or ""),
        ),
        reverse=True,
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate finalized Burst-admissible Market-First evidence")
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.limit <= 0:
        raise ValueError("--limit must be positive")

    rows = find_burst_sources(args.artifacts_root)
    admissible = [row for row in rows if row["burst_source_admissible"]]
    payload = {
        "type": "launch_burst_source_inventory",
        "artifacts_root": str(args.artifacts_root.resolve()),
        "scanned_report_count": len(rows),
        "admissible_count": len(admissible),
        "selected": admissible[0] if admissible else None,
        "rows": rows[: args.limit],
    }

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if admissible else 2


if __name__ == "__main__":
    raise SystemExit(main())
