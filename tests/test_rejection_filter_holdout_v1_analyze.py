import json
import tempfile
import unittest
from pathlib import Path

import rejection_filter_holdout_v1_analyze as an
import rejection_filter_holdout_v1_collect as collect

COH = ("G1", "G2", "G3", "G4")


def cohort_raw(c, rej_n, rej_cat, kept_n, kept_cat, late_rej=0, structural_kept=0):
    rows = []
    for impact, n, cat in ((5.0, rej_n, rej_cat), (0.5, kept_n, kept_cat)):
        for i in range(n):
            ret = -95.0 if i < cat else 10.0
            rows.append({"cohort": c, "episode_key": f"{c}-{impact}-{i}", "impact": impact,
                         "mint_auth": False, "freeze_auth": False, "labels": {300: None, 900: ret, 3600: None},
                         "statuses": {}, "o900": "AVAILABLE_ON_TIME"})
    for i in range(late_rej):  # AVAILABLE but collected late: value present, must be discarded
        rows.append({"cohort": c, "episode_key": f"{c}-late-{i}", "impact": 5.0, "mint_auth": False,
                     "freeze_auth": False, "labels": {300: None, 900: -99.0, 3600: None}, "statuses": {}, "o900": "LATE"})
    for i in range(structural_kept):
        rows.append({"cohort": c, "episode_key": f"{c}-nr-{i}", "impact": 0.5, "mint_auth": False,
                     "freeze_auth": False, "labels": {300: None, 900: None, 3600: None}, "statuses": {}, "o900": "STRUCTURAL"})
    return rows


def raw_all(spec, **kw):
    out = []
    for c, s in zip(COH, spec):
        out += cohort_raw(c, *s, **kw)
    return out


class OnTimeAndVerdictTests(unittest.TestCase):
    def test_keep_with_v1_names(self):
        r = an.analyze(raw_all([(15, 7, 15, 1)] * 4), COH)
        self.assertEqual(r["classification"], an.KEEP)

    def test_late_labels_are_discarded_not_used(self):
        # 20 LATE catastrophic-looking rows per cohort must not enter pairing
        base = an.analyze(raw_all([(15, 7, 15, 1)] * 4), COH)
        with_late = an.analyze(raw_all([(15, 7, 15, 1)] * 4, late_rej=20), COH)
        self.assertEqual(base["aggregate"]["paired"], with_late["aggregate"]["paired"])
        self.assertEqual(base["effect_values"]["cat_diff_pp"], with_late["effect_values"]["cat_diff_pp"])
        self.assertEqual(with_late["missingness_non_gating"]["ALL"]["REJECTED"]["LATE"], 80)

    def test_kill_and_support_inconclusive_names(self):
        self.assertEqual(an.analyze(raw_all([(15, 4, 15, 2)] * 4), COH)["classification"], an.KILL)
        self.assertEqual(an.analyze(raw_all([(8, 4, 8, 0)] * 4), COH)["classification"], an.INC_SUPPORT)

    def test_replacement_labels_supported(self):
        cohorts = ("G1", "G3", "G4", "G5")
        raw = []
        for c in cohorts:
            raw += cohort_raw(c, 15, 7, 15, 1)
        self.assertEqual(an.analyze(raw, cohorts)["classification"], an.KEEP)


class MissingnessTests(unittest.TestCase):
    def test_worst_case_sensitivity_can_flag_reversal(self):
        # primary: REJECTED 7/15 vs KEPT 1/15 (favourable). 30 no-route KEPT per cohort flips it.
        raw = raw_all([(15, 7, 15, 1)] * 4, structural_kept=30)
        r = an.analyze(raw, COH)
        self.assertEqual(r["classification"], an.KEEP)  # primary never converts missing to loss
        self.assertTrue(r["worst_case_sensitivity_non_gating"]["direction_reverses_under_worst_case"])
        self.assertEqual(r["missingness_non_gating"]["ALL"]["KEPT"]["STRUCTURAL"], 120)

    def test_no_reversal_when_structural_is_small(self):
        r = an.analyze(raw_all([(15, 7, 15, 1)] * 4, structural_kept=1), COH)
        self.assertFalse(r["worst_case_sensitivity_non_gating"]["direction_reverses_under_worst_case"])


class GuardTests(unittest.TestCase):
    def test_refuses_until_frozen_and_complete(self):
        orig = collect.PROTOCOL_SHA256
        try:
            with tempfile.TemporaryDirectory() as d:
                collect.PROTOCOL_SHA256 = None
                self.assertIn("not frozen", an.check_reports(Path(d))[1])
                collect.PROTOCOL_SHA256 = "a" * 64
                self.assertIn("CONTINUE", an.check_reports(Path(d))[1])
                root = Path(d)
                for label in ("G1", "G2", "G3"):
                    collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                    "protocol_sha256": "a" * 64}, label, root)
                self.assertIn("CONTINUE", an.check_reports(root)[1])  # 3 valid is not enough
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "protocol_sha256": "b" * 64}, "G4", root)
                self.assertIn("hash", an.check_reports(root)[1])
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "protocol_sha256": "a" * 64}, "G4", root)
                valid, problem = an.check_reports(root)
                self.assertEqual((valid, problem), (["G1", "G2", "G3", "G4"], None))
        finally:
            collect.PROTOCOL_SHA256 = orig

    def test_degraded_cohorts_excluded_from_valid_list(self):
        orig = collect.PROTOCOL_SHA256
        try:
            collect.PROTOCOL_SHA256 = "a" * 64
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                spec = [("G1", collect.VALID), ("G2", collect.DEGRADED), ("G3", collect.VALID),
                        ("G4", collect.VALID), ("G5", collect.VALID)]
                for label, v in spec:
                    collect._write({"classification": collect.ACQ_DONE, "cohort_validity": v,
                                    "protocol_sha256": "a" * 64}, label, root)
                self.assertEqual(an.check_reports(root), (["G1", "G3", "G4", "G5"], None))
        finally:
            collect.PROTOCOL_SHA256 = orig


if __name__ == "__main__":
    unittest.main()
