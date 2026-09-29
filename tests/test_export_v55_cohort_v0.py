import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from research import export_v55_cohort_v0 as exp


def _row(key, as_of, share, labels, statuses):
    return SimpleNamespace(
        episode_key=key,
        cohort="A",
        research_decision_as_of=as_of,
        features={exp.FEATURE: share},
        labels=labels,
        outcome_statuses=statuses,
    )


class ExportV55CohortTests(unittest.TestCase):
    def test_records_sorted_and_missingness_explicit(self):
        rows = [
            _row("e2", 20, None, {300: None, 900: 5.0, 3600: None},
                 {300: "UNAVAILABLE", 900: "AVAILABLE", 3600: "PENDING"}),
            _row("e1", 10, 50.0, {300: 1.5, 900: -2.0, 3600: 0.0},
                 {300: "AVAILABLE", 900: "AVAILABLE", 3600: "AVAILABLE"}),
        ]
        records = exp.rows_to_records(rows)
        self.assertEqual([r["episode_key"] for r in records], ["e1", "e2"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.csv"
            exp.write_csv(records, out)
            data = list(csv.DictReader(out.open(encoding="utf-8")))
        self.assertEqual(tuple(data[0].keys()), exp.COLUMNS)
        self.assertEqual(data[0]["return_pct_3600s"], "0.0")  # real zero stays 0
        self.assertEqual(data[1]["return_pct_300s"], "")  # missing stays empty
        self.assertEqual(data[1][exp.FEATURE], "")

    def test_missing_database_fails_closed(self):
        original = exp.database.settings
        try:
            exp.database.settings = SimpleNamespace(database_path=Path("/nonexistent/x.db"))
            with self.assertRaises(SystemExit):
                exp.export(Path("/tmp/unused.csv"))
        finally:
            exp.database.settings = original

    def test_returns_only_groups_by_episode_and_fails_closed(self):
        def outcome(ep, h, status="AVAILABLE", as_of=10):
            return SimpleNamespace(
                episode_key=ep, horizon_seconds=h, status=status, research_decision_as_of=as_of
            )

        good = [outcome("e1", h) for h in (300, 900, 3600)]
        good[1] = outcome("e1", 900, status="UNAVAILABLE")
        orig_load, orig_ret = exp.load_route_research_outcomes, exp._return_for_available
        try:
            exp.load_route_research_outcomes = lambda acquisition_run_key: (
                good if acquisition_run_key.endswith("-A") else []
            )
            exp._return_for_available = lambda o: float(o.horizon_seconds) / 100
            records = exp.returns_only_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["return_pct_300s"], 3.0)
            self.assertIsNone(records[0]["return_pct_900s"])  # explicit missingness
            self.assertEqual(records[0]["cohort"], "A")
            exp.load_route_research_outcomes = lambda acquisition_run_key: good[:2]
            with self.assertRaises(SystemExit):  # missing horizon -> fail closed
                exp.returns_only_records()
        finally:
            exp.load_route_research_outcomes, exp._return_for_available = orig_load, orig_ret


if __name__ == "__main__":
    unittest.main()
