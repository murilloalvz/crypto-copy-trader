"""Read-only export of the V55 discovery cohort's persisted route-only returns.

PAPER / RESEARCH / READ-ONLY. Descriptive export only: route-only return != realized P&L.
It does not evaluate, re-open or re-interpret V48/V55/V68/Participant Quality. The V55
discovery sample is burned for V68 validation; this file only lets the persisted returns be
re-read under different hold windows.

Reuses the existing V55 dataset builder (which itself reuses
`src.route_research_evaluation._return_for_available` for the route-only return), so no
price/return math is reimplemented here. No provider/network call is made.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src import database
from src.route_research_early_opportunity_v55 import build_early_opportunity_dataset_v55

# From docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md
# ("Fresh base"); sub-cohorts are `<base>-A` and `<base>-B`.
V55_BASE_RUN_KEY = "route-research-early-opportunity-discovery-20260907-55"
V55_RUN_KEYS = (f"{V55_BASE_RUN_KEY}-A", f"{V55_BASE_RUN_KEY}-B")
V55_DOCUMENTED_ROWS = 79  # A=39, B=40 per the frozen result document
HORIZONS_SECONDS = (300, 900, 3600)
FEATURE = "flow60_buy_share_pct"

COLUMNS = (
    "episode_key",
    "cohort",
    "decision_as_of",
    FEATURE,
    *(f"return_pct_{h}s" for h in HORIZONS_SECONDS),
    *(f"status_{h}s" for h in HORIZONS_SECONDS),
)

DEFAULT_OUT = Path(__file__).with_name("v55_cohort_export.csv")


def rows_to_records(rows) -> list[dict[str, object]]:
    records = []
    for row in sorted(rows, key=lambda r: (r.research_decision_as_of, r.episode_key)):
        record: dict[str, object] = {
            "episode_key": row.episode_key,
            "cohort": row.cohort,
            "decision_as_of": row.research_decision_as_of,
            FEATURE: row.features.get(FEATURE),
        }
        for horizon in HORIZONS_SECONDS:
            record[f"return_pct_{horizon}s"] = row.labels.get(horizon)
            record[f"status_{horizon}s"] = row.outcome_statuses.get(horizon)
        records.append(record)
    return records


def write_csv(records: list[dict[str, object]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for record in records:
            # Missingness stays explicit: None is written as an empty cell, never as 0.
            writer.writerow({k: ("" if v is None else v) for k, v in record.items()})


def export(out: Path) -> int:
    db_path = database.settings.database_path
    if not Path(db_path).is_file():
        # database.connection() would silently create an empty DB; refuse instead.
        raise SystemExit(f"Database not found: {db_path} (set DATABASE_PATH or run from repo root)")

    dataset = build_early_opportunity_dataset_v55(acquisition_run_keys=V55_RUN_KEYS)
    base = dataset.base
    problems = {
        "lineage_violations": base.lineage_violations,
        "missing_decisions": base.missing_decisions,
        "missing_episodes": base.missing_episodes,
        "missing_hazard_attempts": base.missing_hazard_attempts,
        "missing_entry_quotes": base.missing_entry_quotes,
        "official_decision_mutations": base.official_decision_mutations,
        "augmentation_failures": dataset.augmentation_failures,
        "feature_clock_violations": dataset.feature_clock_violations,
    }
    if not dataset.rows:
        raise SystemExit(f"No rows for run keys {V55_RUN_KEYS}; wrong database or run key.")
    if any(problems.values()):
        raise SystemExit(f"Fail-closed, cohort integrity problems: {problems}")

    records = rows_to_records(dataset.rows)
    write_csv(records, out)
    print(f"run_keys={V55_RUN_KEYS}")
    print(f"rows_exported={len(records)} documented_rows={V55_DOCUMENTED_ROWS}")
    for horizon in HORIZONS_SECONDS:
        available = sum(1 for r in records if r[f"return_pct_{horizon}s"] is not None)
        print(f"available_{horizon}s={available}")
    if len(records) != V55_DOCUMENTED_ROWS:
        print("WARNING: row count differs from the documented 79; inspect before using.")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    return export(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
