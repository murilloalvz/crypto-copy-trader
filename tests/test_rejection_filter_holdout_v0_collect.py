import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import rejection_filter_holdout_v0_collect as rc


class RunnerGuardTests(unittest.TestCase):
    def test_frozen_protocol_hash_matches_repo_file(self):
        rc.verify_protocol()  # real file vs frozen constant

    def test_hash_is_line_ending_insensitive_and_detects_edits(self):
        with tempfile.TemporaryDirectory() as d:
            lf = Path(d) / "a.md"
            lf.write_bytes(b"x\ny\n")
            crlf = Path(d) / "b.md"
            crlf.write_bytes(b"x\r\ny\r\n")
            self.assertEqual(rc.protocol_hash(lf), rc.protocol_hash(crlf))
            with self.assertRaises(SystemExit):
                rc.verify_protocol(lf, expected="0" * 64)

    def test_run_keys_are_frozen(self):
        self.assertEqual(rc.run_key_for(1), "rejection-filter-v0-20260929-01-F1")
        self.assertEqual(rc.run_key_for(4), "rejection-filter-v0-20260929-01-F4")
        for bad in (0, 5):
            with self.assertRaises(ValueError):
                rc.run_key_for(bad)

    def test_cohort_order_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rc.require_previous_cohort(1, root)  # F1 always allowed
            with self.assertRaises(SystemExit):
                rc.require_previous_cohort(2, root)
            rc._write({"classification": rc.ACQ_INCONCLUSIVE}, 1, root)
            with self.assertRaises(SystemExit):
                rc.require_previous_cohort(2, root)
            rc._write({"classification": rc.ACQ_PASS}, 1, root)
            rc.require_previous_cohort(2, root)

    def test_live_flag_required(self):
        with self.assertRaises(SystemExit):
            rc.main(["--cohort", "1", "--bootstrap-report", "x.json"])


class ConsoleGuardTests(unittest.TestCase):
    def test_noop_off_windows(self):
        ran = []
        with rc.console_guards():
            ran.append(1)
        self.assertEqual(ran, [1])

    def test_windows_disables_quickedit_prevents_sleep_and_restores(self):
        import ctypes
        import sys as _sys
        calls = []

        class K32:
            def GetStdHandle(self, n):
                calls.append(("handle", n))
                return 7

            def GetConsoleMode(self, h, ref):
                ref._obj.value = 0x00C7  # quick edit (0x40) on
                return 1

            def SetConsoleMode(self, h, m):
                calls.append(("mode", m))

            def SetThreadExecutionState(self, f):
                calls.append(("exec", f))

        orig_platform, had = _sys.platform, hasattr(ctypes, "windll")
        old_windll = getattr(ctypes, "windll", None)
        _sys.platform = "win32"
        ctypes.windll = type("W", (), {"kernel32": K32()})()
        try:
            with rc.console_guards():
                pass
        finally:
            _sys.platform = orig_platform
            if had:
                ctypes.windll = old_windll
            else:
                del ctypes.windll
        modes = [m for k, m in calls if k == "mode"]
        self.assertEqual(modes[0] & 0x40, 0)          # quick edit cleared
        self.assertEqual(modes[-1], 0x00C7)           # restored
        execs = [f for k, f in calls if k == "exec"]
        self.assertEqual(execs, [0x80000001, 0x80000000])  # sleep blocked, then released


class RunnerFlowTests(unittest.TestCase):
    """No live calls: bridge, freshness, audit and collector are stubbed."""

    def setUp(self):
        self.orig = (rc.bridge.run_bridge, rc._strict_run_keys_fresh, rc._schedule_audit,
                     rc.collect_route_research_forward_through_900_v0)
        self.calls = {}

        async def fake_bridge(**kw):
            self.calls["bridge"] = kw
            return {"classification": rc.bridge.PASS_CLASSIFICATION}

        rc.bridge.run_bridge = fake_bridge
        rc._strict_run_keys_fresh = lambda keys: (True, "")
        rc._schedule_audit = lambda key: (35, 105, True)
        rc.collect_route_research_forward_through_900_v0 = lambda **kw: SimpleNamespace(
            classification=rc.FORWARD_PASS, statuses_target={"AVAILABLE": 60}, target_lateness_p95_seconds=1)

    def tearDown(self):
        (rc.bridge.run_bridge, rc._strict_run_keys_fresh, rc._schedule_audit,
         rc.collect_route_research_forward_through_900_v0) = self.orig

    def run_it(self):
        with tempfile.TemporaryDirectory() as d:
            return rc.run_cohort(cohort=1, bootstrap_report=Path("b.json"), artifact_root=Path(d))

    def test_pass_uses_frozen_parameters_and_writes_no_verdict(self):
        report = self.run_it()
        self.assertEqual(report["classification"], rc.ACQ_PASS)
        kw = self.calls["bridge"]
        self.assertEqual(kw["run_key"], "rejection-filter-v0-20260929-01-F1")
        self.assertEqual((kw["duration_seconds"], kw["max_episodes"], kw["research_notional_usd"],
                          kw["research_slippage_bps"], kw["hazard_start_interval_ms"],
                          kw["entry_start_interval_ms"]), (120.0, 40, 25.0, 100, 650, 1000))
        self.assertTrue(report["no_verdict_computed"])

    def test_not_fresh_makes_no_provider_call(self):
        rc._strict_run_keys_fresh = lambda keys: (False, "F1:table:3")
        report = self.run_it()
        self.assertEqual(report["classification"], rc.ACQ_NOT_FRESH)
        self.assertNotIn("bridge", self.calls)

    def test_too_few_decisions_is_inconclusive(self):
        rc._schedule_audit = lambda key: (29, 87, True)
        self.assertEqual(self.run_it()["classification"], rc.ACQ_INCONCLUSIVE)

    def test_schedule_mismatch_is_inconclusive(self):
        rc._schedule_audit = lambda key: (35, 100, True)
        self.assertEqual(self.run_it()["classification"], rc.ACQ_INCONCLUSIVE)

    def test_forward_failure_is_inconclusive(self):
        rc.collect_route_research_forward_through_900_v0 = lambda **kw: SimpleNamespace(
            classification="FAIL", statuses_target={}, target_lateness_p95_seconds=9)
        self.assertEqual(self.run_it()["classification"], rc.ACQ_INCONCLUSIVE)


if __name__ == "__main__":
    unittest.main()
