import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import rejection_filter_holdout_v1_collect as v1
import rejection_filter_holdout_v2_collect as rc

D1, D2, D3 = "2026-10-05", "2026-10-06", "2026-10-07"
NOON = lambda d: time.mktime(time.strptime(d + " 12:00", "%Y-%m-%d %H:%M")) - time.timezone  # noqa: E731


def put(root, label, validity=rc.VALID, date=D1, classification=rc.ACQ_DONE):
    rc._write({"classification": classification, "cohort_validity": validity, "started_utc_date": date,
               "protocol_sha256": "a" * 64}, label, root)


class StudyStateTests(unittest.TestCase):
    def test_five_valid_required_and_replacements(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(rc.study_state(root)["next"], "H1")
            for l in ("H1", "H2", "H3", "H4"):
                put(root, l)
            self.assertEqual(rc.study_state(root)["status"], "CONTINUE")  # 4 valid is not enough
            put(root, "H5")
            self.assertEqual(rc.study_state(root)["status"], "COMPLETE")

    def test_degraded_uses_reserved_replacements_and_third_degraded_ends(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            put(root, "H1", rc.DEGRADED)
            put(root, "H2", rc.DEGRADED)
            for l in ("H3", "H4", "H5", "H6"):
                put(root, l)
            s = rc.study_state(root)
            self.assertEqual((s["status"], s["next"]), ("CONTINUE", "H7"))
            put(root, "H7")
            self.assertEqual(rc.study_state(root)["status"], "COMPLETE")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l in ("H1", "H2", "H3"):
                put(root, l, rc.DEGRADED)
            self.assertEqual(rc.study_state(root)["status"], "INCONCLUSIVE_ACQUISITION")

    def test_not_fresh_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            put(Path(d), "H1", rc.DEGRADED, classification=rc.NOT_FRESH)
            with self.assertRaises(SystemExit):
                rc.study_state(Path(d))


class DayRuleTests(unittest.TestCase):
    def test_forbidden_v1_days_are_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("V1 collection day", rc.day_problem(NOON("2026-09-29"), Path(d)))
            self.assertIn("V1 collection day", rc.day_problem(NOON("2026-09-30"), Path(d)))
            self.assertIsNone(rc.day_problem(NOON(D1), Path(d)))

    def test_max_three_started_per_utc_day(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l in ("H1", "H2", "H3"):
                put(root, l, date=D1)
            self.assertIn("already started", rc.day_problem(NOON(D1), root))
            self.assertIsNone(rc.day_problem(NOON(D2), root))

    def test_distinct_days_check_for_analysis(self):
        reports = {"H1": {"started_utc_date": D1}, "H2": {"started_utc_date": D1}, "H3": {"started_utc_date": D1},
                   "H4": {"started_utc_date": D2}, "H5": {"started_utc_date": D2}}
        labels = ["H1", "H2", "H3", "H4", "H5"]
        self.assertIsNone(rc.distinct_days_problem(reports, labels))
        one_day = {l: {"started_utc_date": D1} for l in labels}
        self.assertIn("at least 2", rc.distinct_days_problem(one_day, labels))
        four = {**reports, "H4": {"started_utc_date": D1}}
        self.assertIn("more than 3", rc.distinct_days_problem(four, labels))
        forbidden = {**reports, "H5": {"started_utc_date": "2026-09-30"}}
        self.assertIn("V1 collection day", rc.distinct_days_problem(forbidden, labels))
        self.assertIn("no recorded", rc.distinct_days_problem({**reports, "H5": {}}, labels))


class GuardTests(unittest.TestCase):
    def test_run_keys_and_protocol_gate(self):
        self.assertEqual(rc.run_key_for("H1"), "rejection-filter-v2-20260930-01-H1")
        self.assertEqual(rc.run_key_for("H7"), "rejection-filter-v2-20260930-01-H7")
        with self.assertRaises(ValueError):
            rc.run_key_for("G1")
        with self.assertRaises(SystemExit):
            rc.verify_protocol()  # not frozen: hash is None
        with self.assertRaises(SystemExit):
            rc.main(["--bootstrap-report", "x.json"])  # live flag missing
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.md"
            f.write_text("x", encoding="utf-8")
            rc.verify_protocol(f, expected=rc.protocol_hash(f))
            with self.assertRaises(SystemExit):
                rc.verify_protocol(f, expected="0" * 64)

    def test_reuses_frozen_v1_values(self):
        self.assertEqual((rc.LATENESS_CAP_SECONDS, rc.DEGRADED_THRESHOLD), (60, 0.20))
        self.assertIs(rc.classify_outcome, v1.classify_outcome)

    def test_utc_date(self):
        self.assertEqual(rc.utc_date(0), "1970-01-01")


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.orig = (rc.bridge.run_bridge, rc._strict_run_keys_fresh, rc._schedule_audit,
                     rc.collect_route_research_forward_through_900_v0, rc.load_route_research_outcomes)
        self.calls = {}

        async def fake_bridge(**kw):
            self.calls["bridge"] = kw
            return {"classification": rc.bridge.PASS_CLASSIFICATION}

        rc.bridge.run_bridge = fake_bridge
        rc._strict_run_keys_fresh = lambda keys: (True, "")
        rc._schedule_audit = lambda key: (40, 120, True)
        rc.collect_route_research_forward_through_900_v0 = lambda **kw: SimpleNamespace(
            classification=rc.FORWARD_PASS, statuses_target={}, target_lateness_p95_seconds=1)
        rc.load_route_research_outcomes = lambda **kw: [
            SimpleNamespace(horizon_seconds=900, status="AVAILABLE", error_type=None, error_message=None,
                            target_at=1000, observed_at=1001) for _ in range(40)]

    def tearDown(self):
        (rc.bridge.run_bridge, rc._strict_run_keys_fresh, rc._schedule_audit,
         rc.collect_route_research_forward_through_900_v0, rc.load_route_research_outcomes) = self.orig

    def run_it(self, label="H1"):
        with tempfile.TemporaryDirectory() as d:
            return rc.run_cohort(label=label, bootstrap_report=Path("b.json"), artifact_root=Path(d))

    def test_valid_cohort_records_start_date_and_uses_frozen_parameters(self):
        r = self.run_it()
        self.assertEqual(r["cohort_validity"], rc.VALID)
        self.assertRegex(r["started_utc_date"], r"^\d{4}-\d{2}-\d{2}$")
        kw = self.calls["bridge"]
        self.assertEqual(kw["run_key"], "rejection-filter-v2-20260930-01-H1")
        self.assertEqual((kw["duration_seconds"], kw["max_episodes"], kw["research_notional_usd"],
                          kw["research_slippage_bps"], kw["hazard_start_interval_ms"], kw["entry_start_interval_ms"]),
                         (120.0, 40, 25.0, 100, 650, 1000))
        self.assertTrue(r["no_verdict_computed"])

    def test_not_fresh_and_failures(self):
        rc._strict_run_keys_fresh = lambda keys: (False, "H1:t:3")
        self.assertEqual(self.run_it()["classification"], rc.NOT_FRESH)
        self.assertNotIn("bridge", self.calls)
        rc._strict_run_keys_fresh = lambda keys: (True, "")
        rc._schedule_audit = lambda key: (29, 87, True)
        self.assertEqual(self.run_it()["cohort_validity"], rc.DEGRADED)


if __name__ == "__main__":
    unittest.main()
