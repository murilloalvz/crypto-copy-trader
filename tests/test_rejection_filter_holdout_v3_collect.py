import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import rejection_filter_holdout_v1_collect as v1
import rejection_filter_holdout_v3_collect as rc

D1, D2, D3, D4 = "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"
NOON = lambda d: time.mktime(time.strptime(d + " 12:00", "%Y-%m-%d %H:%M")) - time.timezone  # noqa: E731


def put(root, label, validity=rc.VALID, date=D1, classification=rc.ACQ_DONE):
    rc._write({"classification": classification, "cohort_validity": validity, "started_utc_date": date,
               "protocol_sha256": "a" * 64}, label, root)


class StudyStateTests(unittest.TestCase):
    def test_ten_valid_required_and_replacements(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(rc.study_state(root)["next"], "T1")
            for i in range(1, 10):
                put(root, f"T{i}")
            self.assertEqual(rc.study_state(root)["status"], "CONTINUE")  # 9 valid is not enough
            put(root, "T10")
            self.assertEqual(rc.study_state(root)["status"], "COMPLETE")

    def test_degraded_uses_reserved_replacements_and_fourth_degraded_ends(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l in ("T1", "T2", "T3"):
                put(root, l, rc.DEGRADED)
            for i in range(4, 14):
                put(root, f"T{i}")
            self.assertEqual(rc.study_state(root)["status"], "COMPLETE")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l in ("T1", "T2", "T3", "T4"):
                put(root, l, rc.DEGRADED)
            self.assertEqual(rc.study_state(root)["status"], "INCONCLUSIVE_ACQUISITION")

    def test_not_fresh_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            put(Path(d), "T1", rc.DEGRADED, classification=rc.NOT_FRESH)
            with self.assertRaises(SystemExit):
                rc.study_state(Path(d))


class DayRuleTests(unittest.TestCase):
    def test_max_three_started_per_utc_day(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(rc.day_problem(NOON(D1), root))
            for l in ("T1", "T2", "T3"):
                put(root, l, date=D1)
            self.assertIn("already started", rc.day_problem(NOON(D1), root))
            self.assertIsNone(rc.day_problem(NOON(D2), root))

    def test_day_diversity(self):
        self.assertTrue(rc.day_diversity_ok([D1] * 3 + [D2] * 3 + [D3] * 3 + [D4]))
        self.assertFalse(rc.day_diversity_ok([D1] * 5 + [D2] * 5))      # only two days
        self.assertFalse(rc.day_diversity_ok([D1] * 4 + [D2] * 3 + [D3] * 3))  # four on one day
        self.assertFalse(rc.day_diversity_ok([D1, D2, None]))


class GuardTests(unittest.TestCase):
    def test_run_keys_and_protocol_gate(self):
        self.assertEqual(rc.run_key_for("T1"), "rejection-filter-v3-20261002-01-T1")
        self.assertEqual(rc.run_key_for("T13"), "rejection-filter-v3-20261002-01-T13")
        with self.assertRaises(ValueError):
            rc.run_key_for("H1")
        orig = rc.PROTOCOL_SHA256
        try:
            rc.PROTOCOL_SHA256 = None
            with self.assertRaises(SystemExit):
                rc.verify_protocol()  # no hash recorded => not frozen
        finally:
            rc.PROTOCOL_SHA256 = orig
        with self.assertRaises(SystemExit):
            rc.main(["--bootstrap-report", "x.json"])  # live flag missing
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.md"
            f.write_text("x", encoding="utf-8")
            rc.verify_protocol(f, expected=rc.protocol_hash(f))
            with self.assertRaises(SystemExit):
                rc.verify_protocol(f, expected="0" * 64)

    def test_frozen_constants_and_reuse(self):
        self.assertEqual((rc.LATENESS_CAP_SECONDS, rc.DEGRADED_THRESHOLD), (60, 0.20))
        self.assertEqual((rc.RESEARCH_NOTIONAL_USD, rc.VALID_COHORTS_REQUIRED, rc.MAX_DEGRADED), (10.0, 10, 3))
        self.assertIs(rc.classify_outcome, v1.classify_outcome)


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

    def run_it(self, label="T1"):
        with tempfile.TemporaryDirectory() as d:
            return rc.run_cohort(label=label, bootstrap_report=Path("b.json"), artifact_root=Path(d))

    def test_valid_cohort_uses_usd10_and_records_start(self):
        r = self.run_it()
        self.assertEqual(r["cohort_validity"], rc.VALID)
        self.assertRegex(r["started_utc_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(r["order_notional_usd"], 10.0)
        kw = self.calls["bridge"]
        self.assertEqual(kw["run_key"], "rejection-filter-v3-20261002-01-T1")
        self.assertEqual((kw["duration_seconds"], kw["max_episodes"], kw["research_notional_usd"],
                          kw["research_slippage_bps"], kw["hazard_start_interval_ms"], kw["entry_start_interval_ms"]),
                         (120.0, 40, 10.0, 100, 650, 1000))
        self.assertTrue(r["no_verdict_computed"])

    def test_not_fresh_and_failures(self):
        rc._strict_run_keys_fresh = lambda keys: (False, "T1:t:3")
        self.assertEqual(self.run_it()["classification"], rc.NOT_FRESH)
        self.assertNotIn("bridge", self.calls)
        rc._strict_run_keys_fresh = lambda keys: (True, "")
        rc._schedule_audit = lambda key: (29, 87, True)
        self.assertEqual(self.run_it()["cohort_validity"], rc.DEGRADED)


if __name__ == "__main__":
    unittest.main()
