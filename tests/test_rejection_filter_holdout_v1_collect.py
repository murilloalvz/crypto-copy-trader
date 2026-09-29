import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import rejection_filter_holdout_v1_collect as rc


def out(status, et=None, em=None, target=1000, observed=1000):
    return {"status": status, "error_type": et, "error_message": em, "target_at": target, "observed_at": observed}


E429 = ("JupiterOrderError", 'Jupiter /order HTTP 429: {"code":429,"message":"[API Gateway] Too many requests"}')
E400 = ("JupiterOrderError", 'Jupiter /order HTTP 400: {"error":"Failed to get quotes"}')


class TaxonomyTests(unittest.TestCase):
    def test_classify(self):
        c = rc.classify_outcome
        self.assertEqual(c("AVAILABLE", None, None, 1000, 1000), "AVAILABLE_ON_TIME")
        self.assertEqual(c("AVAILABLE", None, None, 1000, 1060), "AVAILABLE_ON_TIME")  # boundary inclusive
        self.assertEqual(c("AVAILABLE", None, None, 1000, 1061), "LATE")
        self.assertEqual(c("AVAILABLE", None, None, 1000, None), "TECHNICAL")
        self.assertEqual(c("PROVIDER_ERROR", *E429, 1000, 1010), "TECHNICAL")
        self.assertEqual(c("PROVIDER_ERROR", *E400, 1000, 1010), "STRUCTURAL")
        self.assertEqual(c("PROVIDER_ERROR", "TimeoutError", "timed out", 1000, 1010), "TECHNICAL")
        self.assertEqual(c("PROVIDER_ERROR", None, None, 1000, 1010), "TECHNICAL")  # unknown -> conservative
        self.assertEqual(c("PENDING", None, None, 1000, None), "PENDING")

    def test_v0_f1_like_cohort_is_degraded(self):
        rows = ([out("AVAILABLE", observed=1000)] + [out("AVAILABLE", observed=2005)] * 9
                + [out("PROVIDER_ERROR", *E429)] * 27 + [out("PROVIDER_ERROR", *E400)] * 2)
        a = rc.assess_cohort(rows, 39)
        self.assertEqual(a["cohort_validity"], rc.DEGRADED)
        self.assertAlmostEqual(a["technical_unusable_share"], 36 / 39)
        self.assertEqual(a["counts_900"]["STRUCTURAL"], 2)

    def test_healthy_cohort_valid_and_structural_never_degrades(self):
        rows = [out("AVAILABLE", observed=1001)] * 25 + [out("PROVIDER_ERROR", *E400)] * 14
        a = rc.assess_cohort(rows, 39)
        self.assertEqual(a["cohort_validity"], rc.VALID)
        self.assertEqual(a["technical_unusable_share"], 0.0)

    def test_threshold_is_strictly_above_20_percent(self):
        ok = [out("AVAILABLE")] * 32 + [out("PROVIDER_ERROR", *E429)] * 8   # 8/40 = 20% -> VALID
        bad = [out("AVAILABLE")] * 31 + [out("PROVIDER_ERROR", *E429)] * 9  # 22.5% -> DEGRADED
        self.assertEqual(rc.assess_cohort(ok, 40)["cohort_validity"], rc.VALID)
        self.assertEqual(rc.assess_cohort(bad, 40)["cohort_validity"], rc.DEGRADED)
        self.assertEqual(rc.assess_cohort([], 0)["cohort_validity"], rc.DEGRADED)


class StateTests(unittest.TestCase):
    def put(self, root, label, validity, classification=rc.ACQ_DONE):
        rc._write({"classification": classification, "cohort_validity": validity}, label, root)

    def test_state_machine(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(rc.study_state(root)["next"], "G1")
            self.put(root, "G1", rc.VALID)
            self.put(root, "G2", rc.DEGRADED)
            s = rc.study_state(root)
            self.assertEqual((s["status"], s["next"]), ("CONTINUE", "G3"))
            for l in ("G3", "G4", "G5"):
                self.put(root, l, rc.VALID)
            s = rc.study_state(root)
            self.assertEqual((s["status"], s["valid"], s["degraded"]), ("COMPLETE", ["G1", "G3", "G4", "G5"], ["G2"]))

    def test_too_many_degraded_ends_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l in ("G1", "G2", "G3"):
                self.put(root, l, rc.DEGRADED)
            self.assertEqual(rc.study_state(root)["status"], "INCONCLUSIVE_ACQUISITION")

    def test_two_degraded_still_allows_four_valid(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for l, v in (("G1", rc.DEGRADED), ("G2", rc.DEGRADED), ("G3", rc.VALID), ("G4", rc.VALID), ("G5", rc.VALID)):
                self.put(root, l, v)
            s = rc.study_state(root)
            self.assertEqual((s["status"], s["next"]), ("CONTINUE", "G6"))

    def test_not_fresh_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.put(root, "G1", rc.DEGRADED, classification=rc.NOT_FRESH)
            with self.assertRaises(SystemExit):
                rc.study_state(root)


class PreflightTests(unittest.TestCase):
    def bootstrap(self, d, **kw):
        data = {"classification": rc.BOOTSTRAP_PASS, "valid_bootstrap": True, "ended_at": int(time.time()) - 3600}
        data.update(kw)
        p = Path(d) / "b.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_bootstrap_checks(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(rc.bootstrap_problem(self.bootstrap(d)))
            self.assertIn("older", rc.bootstrap_problem(self.bootstrap(d, ended_at=int(time.time()) - 90000)))
            self.assertIn("valid", rc.bootstrap_problem(self.bootstrap(d, valid_bootstrap=False)))
            self.assertIn("valid", rc.bootstrap_problem(self.bootstrap(d, classification="FAIL_X")))
            self.assertIn("ended_at", rc.bootstrap_problem(self.bootstrap(d, ended_at=None)))
            self.assertIn("not found", rc.bootstrap_problem(Path(d) / "missing.json"))

    def test_env_checks(self):
        orig = rc.settings
        try:
            with tempfile.TemporaryDirectory() as d:
                good = self.bootstrap(d)
                rc.settings = SimpleNamespace(jupiter_api_key="k", rpc_url="https://solana-mainnet.g.alchemy.com/v2/x")
                self.assertIsNone(rc.preflight_problem(good))
                rc.settings = SimpleNamespace(jupiter_api_key="", rpc_url="https://solana-mainnet.g.alchemy.com/v2/x")
                self.assertIn("JUPITER", rc.preflight_problem(good))
                rc.settings = SimpleNamespace(jupiter_api_key="k", rpc_url="https://api.mainnet.solana.com")
                self.assertIn("public default", rc.preflight_problem(good))
        finally:
            rc.settings = orig

    def test_frozen_protocol_hash_matches_repo_file(self):
        rc.verify_protocol()  # real frozen file vs recorded constant

    def test_unfrozen_protocol_and_missing_flag_refuse(self):
        orig = rc.PROTOCOL_SHA256
        try:
            rc.PROTOCOL_SHA256 = None
            with self.assertRaises(SystemExit):
                rc.verify_protocol()  # no hash recorded => not frozen
        finally:
            rc.PROTOCOL_SHA256 = orig
        with self.assertRaises(SystemExit):
            rc.main(["--bootstrap-report", "x.json"])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.md"
            f.write_text("x", encoding="utf-8")
            with self.assertRaises(SystemExit):
                rc.verify_protocol(f, expected="0" * 64)
            rc.verify_protocol(f, expected=rc.protocol_hash(f))


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
                            target_at=1000, observed_at=1001) for _ in range(30)]

    def tearDown(self):
        (rc.bridge.run_bridge, rc._strict_run_keys_fresh, rc._schedule_audit,
         rc.collect_route_research_forward_through_900_v0, rc.load_route_research_outcomes) = self.orig

    def run_it(self, label="G1"):
        with tempfile.TemporaryDirectory() as d:
            return rc.run_cohort(label=label, bootstrap_report=Path("b.json"), artifact_root=Path(d))

    def test_valid_cohort_uses_frozen_parameters(self):
        r = self.run_it()
        self.assertEqual(r["cohort_validity"], rc.VALID)
        kw = self.calls["bridge"]
        self.assertEqual(kw["run_key"], "rejection-filter-v1-20260929-01-G1")
        self.assertEqual((kw["duration_seconds"], kw["max_episodes"], kw["research_notional_usd"],
                          kw["research_slippage_bps"], kw["hazard_start_interval_ms"], kw["entry_start_interval_ms"]),
                         (120.0, 40, 25.0, 100, 650, 1000))
        self.assertTrue(r["no_verdict_computed"])

    def test_not_fresh_makes_no_provider_call(self):
        rc._strict_run_keys_fresh = lambda keys: (False, "G1:t:3")
        r = self.run_it()
        self.assertEqual(r["classification"], rc.NOT_FRESH)
        self.assertNotIn("bridge", self.calls)

    def test_bridge_or_forward_failure_is_degraded(self):
        rc._schedule_audit = lambda key: (29, 87, True)
        self.assertEqual(self.run_it()["cohort_validity"], rc.DEGRADED)
        rc._schedule_audit = lambda key: (40, 120, True)
        rc.collect_route_research_forward_through_900_v0 = lambda **kw: SimpleNamespace(
            classification="FAIL", statuses_target={}, target_lateness_p95_seconds=9)
        self.assertEqual(self.run_it()["degraded_reason"], "forward_900_maturity_failure")

    def test_late_quotes_degrade_the_cohort(self):
        rc.load_route_research_outcomes = lambda **kw: [
            SimpleNamespace(horizon_seconds=900, status="AVAILABLE", error_type=None, error_message=None,
                            target_at=1000, observed_at=2005) for _ in range(30)]
        r = self.run_it()
        self.assertEqual(r["cohort_validity"], rc.DEGRADED)
        self.assertEqual(r["degraded_reason"], "technical_unusable_share_above_threshold")


if __name__ == "__main__":
    unittest.main()
