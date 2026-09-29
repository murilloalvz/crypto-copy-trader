import json
import tempfile
import unittest
from pathlib import Path

import rejection_filter_holdout_v0_analyze as an
import rejection_filter_holdout_v0_collect as collect


def raw(cohort, n, impact, ret, mint=None, freeze=None):
    return [{"cohort": cohort, "episode_key": f"{cohort}-{impact}-{ret}-{i}", "impact": impact,
             "mint_auth": mint, "freeze_auth": freeze,
             "labels": {300: ret, 900: ret, 3600: None}, "statuses": {}} for i in range(n)]


def cohort_rows(c, rej_n, rej_cat, kept_n, kept_cat):
    """rej_cat/kept_cat catastrophic (-95) rows, rest +10."""
    rows = []
    for group_impact, n, cat in ((5.0, rej_n, rej_cat), (0.5, kept_n, kept_cat)):
        for i in range(n):
            ret = -95.0 if i < cat else 10.0
            rows.append({"cohort": c, "episode_key": f"{c}-{group_impact}-{i}", "impact": group_impact,
                         "mint_auth": False, "freeze_auth": False,
                         "labels": {300: None, 900: ret, 3600: None}, "statuses": {}})
    return rows


def evaluate(rows):
    return an.evaluate(an.prepare_rows(rows))


class ClassificationTests(unittest.TestCase):
    def test_boundaries_and_missing(self):
        self.assertEqual(an.classify(2.0), "KEPT")          # <= 2.0 kept
        self.assertEqual(an.classify(-2.0), "KEPT")         # abs semantics
        self.assertEqual(an.classify(2.0001), "REJECTED")
        self.assertEqual(an.classify(-2.5), "REJECTED")     # signed negative beyond cap
        for missing in (None, float("nan"), float("inf"), True, "x"):
            self.assertEqual(an.classify(missing), "UNCLASSIFIED")
        self.assertTrue(an.is_catastrophic(-80.0))          # inclusive
        self.assertFalse(an.is_catastrophic(-79.99))

    def test_authority_present_is_excluded_unknown_is_not(self):
        rows = an.prepare_rows(raw("F1", 1, 0.5, 10.0, mint=True) + raw("F1", 1, 0.5, 10.0, mint=None))
        self.assertTrue(rows[0]["excluded_authority"] and rows[0]["group"] is None)
        self.assertFalse(rows[1]["excluded_authority"])
        self.assertEqual(rows[1]["group"], "KEPT")


class StatsTests(unittest.TestCase):
    def test_fisher_known_values(self):
        self.assertAlmostEqual(an.fisher_one_sided(0, 5, 0, 5), 1.0)
        # 5/5 vs 0/5: only one arrangement of 252 -> 1/252
        self.assertAlmostEqual(an.fisher_one_sided(5, 5, 0, 5), 1 / 252)

    def test_clopper_pearson_known_values(self):
        lo, hi = an.clopper_pearson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.3085, places=3)
        lo, hi = an.clopper_pearson(5, 10)
        self.assertAlmostEqual(lo, 0.1871, places=3)
        self.assertAlmostEqual(hi, 0.8129, places=3)
        self.assertIsNone(an.clopper_pearson(0, 0))


class VerdictTests(unittest.TestCase):
    def rows(self, spec):
        out = []
        for c, (rn, rc, kn, kc) in zip(an.COHORTS, spec):
            out += cohort_rows(c, rn, rc, kn, kc)
        return out

    def test_keep(self):
        # each cohort: REJ 15 (7 cat = 47%), KEPT 15 (1 cat = 7%); kept share 50%
        r = evaluate(self.rows([(15, 7, 15, 1)] * 4))
        self.assertEqual(r["classification"], an.KEEP)
        self.assertTrue(all(r["effect_checks"].values()))

    def test_kill_when_a_cohort_goes_the_wrong_way(self):
        spec = [(15, 7, 15, 1)] * 3 + [(15, 1, 15, 3)]
        r = evaluate(self.rows(spec))
        self.assertEqual(r["classification"], an.KILL)
        self.assertFalse(r["effect_checks"]["rejected_gt_kept_in_every_cohort"])

    def test_kill_when_effect_too_small(self):
        r = evaluate(self.rows([(15, 4, 15, 2)] * 4))  # 26.7% vs 13.3% = 13.3pp < 15
        self.assertEqual(r["classification"], an.KILL)
        self.assertFalse(r["effect_checks"]["diff_ge_15pp"])

    def test_kill_when_kept_share_out_of_band(self):
        r = evaluate(self.rows([(40, 20, 6, 0)] * 4))  # kept share ~13%
        self.assertEqual(r["classification"], an.KILL)
        self.assertFalse(r["effect_checks"]["kept_share_30_to_85"])

    def test_inconclusive_support_variants(self):
        # too few paired outcomes
        self.assertEqual(evaluate(self.rows([(8, 4, 8, 0)] * 4))["classification"], an.INC_SUPPORT)
        # group below 5 in one cohort
        spec = [(15, 7, 15, 1)] * 3 + [(3, 2, 30, 1)]
        self.assertEqual(evaluate(self.rows(spec))["classification"], an.INC_SUPPORT)
        # not enough catastrophic events overall (9 < 10)
        spec = [(15, 2, 15, 0)] * 3 + [(15, 3, 15, 0)]
        r = evaluate(self.rows(spec))
        self.assertFalse(r["support_checks"]["catastrophic_total_ge_10"])
        self.assertEqual(r["classification"], an.INC_SUPPORT)

    def test_low_impact_coverage_is_support_failure_not_zero_fill(self):
        rows = self.rows([(15, 7, 15, 1)] * 4)
        for r in rows:
            if r["cohort"] == "F1" and r["episode_key"].endswith(("-0", "-1", "-2", "-3", "-4", "-5", "-6")):
                r["impact"] = None  # unclassified, dropped from both groups
        res = evaluate(rows)
        self.assertFalse(res["support_checks"]["impact_coverage_ge_80_every_cohort"])
        self.assertEqual(res["classification"], an.INC_SUPPORT)

    def test_descriptive_does_not_affect_verdict(self):
        prepared = an.prepare_rows(self.rows([(15, 7, 15, 1)] * 4))
        d = an.descriptive(prepared)
        self.assertIn("900s", d["KEPT"])
        self.assertEqual(an.evaluate(prepared)["classification"], an.KEEP)


class GuardTests(unittest.TestCase):
    def write_reports(self, root, classifications, sha=None):
        for i, cls in enumerate(classifications, start=1):
            collect._write({"classification": cls, "protocol_sha256": sha or collect.PROTOCOL_SHA256}, i, root)

    def test_no_partial_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIn("missing", an.check_acquisition_reports(root))
            self.write_reports(root, [collect.ACQ_PASS] * 3)
            self.assertIn("F4", an.check_acquisition_reports(root))
            self.write_reports(root, [collect.ACQ_PASS] * 3 + [collect.ACQ_INCONCLUSIVE])
            self.assertIn("F4", an.check_acquisition_reports(root))

    def test_all_pass_and_hash_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.write_reports(root, [collect.ACQ_PASS] * 4)
            self.assertIsNone(an.check_acquisition_reports(root))
            self.write_reports(root, [collect.ACQ_PASS] * 4, sha="0" * 64)
            self.assertIn("hash", an.check_acquisition_reports(root))

    def test_run_analysis_reports_acquisition_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(an.run_analysis(Path(d))["classification"], an.INC_ACQ)


if __name__ == "__main__":
    unittest.main()
