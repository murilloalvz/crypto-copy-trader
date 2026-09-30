import tempfile
import unittest
from pathlib import Path

import rejection_filter_holdout_v2_analyze as an
import rejection_filter_holdout_v2_collect as collect
from research import diagnose_rejection_filter_v1_token_overlap_v0 as diag

COH = ("H1", "H2", "H3", "H4", "H5")
DATES = {"H1": "2026-10-05", "H2": "2026-10-05", "H3": "2026-10-05", "H4": "2026-10-06", "H5": "2026-10-06"}
_n = [0]


def make(c, impact, ret, token=None, o900="AVAILABLE_ON_TIME", as_of=None):
    _n[0] += 1
    return {"cohort": c, "episode_key": f"{c}-{_n[0]}", "token": token or f"tok{_n[0]}", "as_of": as_of or _n[0],
            "impact": impact, "mint_auth": False, "freeze_auth": False,
            "labels": {300: None, 900: ret, 3600: None}, "statuses": {}, "o900": o900}


def cohort(c, rej_n, rej_cat, kept_n, kept_cat):
    rows = []
    for impact, n, cat in ((5.0, rej_n, rej_cat), (0.5, kept_n, kept_cat)):
        rows += [make(c, impact, -95.0 if i < cat else 10.0) for i in range(n)]
    return rows


def study(spec):
    out = []
    for c, s in zip(COH, spec):
        out += cohort(c, *s)
    return out


def evaluate(raw, prior=None, dates=DATES):
    return an.evaluate_v2(an.prepare_rows_v2(raw), COH, prior or set(), dates)


class TokenExclusionTests(unittest.TestCase):
    def test_first_per_token_wins_and_prior_tokens_excluded(self):
        raw = [make("H1", 0.5, 1.0, token="A", as_of=10), make("H2", 0.5, 1.0, token="A", as_of=5),
               make("H1", 0.5, 1.0, token="B", as_of=1), make("H3", 0.5, 1.0, token="C", as_of=2)]
        rows = an.prepare_rows_v2(raw)
        an.apply_token_exclusions(rows, {"C"})
        status = {(r["token"], r["as_of"]): r["token_status"] for r in rows}
        self.assertEqual(status[("A", 5)], "OK")              # earliest decision wins
        self.assertEqual(status[("A", 10)], "REPEAT")
        self.assertEqual(status[("B", 1)], "OK")
        self.assertEqual(status[("C", 2)], "SEEN_IN_PRIOR_STUDY")

    def test_repeats_do_not_enter_the_gates(self):
        base = study([(15, 7, 15, 1)] * 5)
        clone = [dict(r, episode_key=r["episode_key"] + "-dup", token=r["token"], as_of=r["as_of"] + 10_000)
                 for r in base]
        with_dups = evaluate(base + clone)
        without = evaluate(base)
        self.assertEqual(with_dups["aggregate"]["paired"], without["aggregate"]["paired"])
        self.assertEqual(with_dups["token_exclusions_non_gating"]["ALL"]["REPEAT"], len(base))

    def test_dedup_helper_for_diagnostics(self):
        rows = an.prepare_rows_v2([make("G1", 0.5, 1.0, token="A", as_of=2), make("G2", 0.5, 1.0, token="A", as_of=1)])
        self.assertEqual([r["as_of"] for r in an.dedup_first_per_token(rows)], [1])


class VerdictTests(unittest.TestCase):
    def test_replicated(self):
        r = evaluate(study([(15, 7, 15, 1)] * 5))
        self.assertEqual(r["classification"], an.REPLICATED)
        self.assertIn("rejected_gt_kept_in_at_least_4_cohorts", r["effect_checks"])

    def test_four_of_five_direction_rule(self):
        good = [(15, 7, 15, 1)] * 4
        wrong = (15, 1, 15, 3)  # REJECTED < KEPT in one cohort
        r = evaluate(study(good + [wrong]))
        self.assertEqual(r["classification"], an.REPLICATED)
        self.assertEqual(r["effect_values"]["cohorts_with_correct_direction"], 4)
        r = evaluate(study(good[:3] + [wrong, wrong]))
        self.assertEqual(r["classification"], an.NOT_REPLICATED)
        self.assertFalse(r["effect_checks"]["rejected_gt_kept_in_at_least_4_cohorts"])

    def test_not_replicated_when_effect_small(self):
        self.assertEqual(evaluate(study([(15, 4, 15, 2)] * 5))["classification"], an.NOT_REPLICATED)

    def test_support_inconclusive(self):
        self.assertEqual(evaluate(study([(8, 4, 8, 0)] * 5))["classification"], an.INC_SUPPORT)

    def test_coverage_measured_before_token_exclusions(self):
        # Every episode of H1 repeats a token seen in a prior study -> excluded, but coverage must still be 100%
        raw = study([(15, 7, 15, 1)] * 5)
        prior = {r["token"] for r in raw if r["cohort"] == "H1"}
        r = evaluate(raw, prior=prior)
        self.assertTrue(r["support_checks"]["impact_coverage_ge_80_every_cohort"])
        self.assertFalse(r["support_checks"]["rejected_and_kept_ge_5_every_cohort"])  # but H1 has no pairs left
        self.assertEqual(r["classification"], an.INC_SUPPORT)

    def test_low_pre_exclusion_coverage_fails_support(self):
        raw = study([(15, 7, 15, 1)] * 5)
        for r in [x for x in raw if x["cohort"] == "H2"][:12]:
            r["impact"] = None
        self.assertFalse(evaluate(raw)["support_checks"]["impact_coverage_ge_80_every_cohort"])

    def test_single_day_is_support_failure(self):
        one_day = {c: "2026-10-05" for c in COH}
        r = evaluate(study([(15, 7, 15, 1)] * 5), dates=one_day)
        self.assertFalse(r["support_checks"]["utc_days_ge_2_and_max_3_per_day"])
        self.assertEqual(r["classification"], an.INC_SUPPORT)
        self.assertNotIn("effect_checks", r)

    def test_late_labels_discarded_and_worst_case_flag(self):
        raw = study([(15, 7, 15, 1)] * 5)
        raw += [make(c, 5.0, -99.0, o900="LATE") for c in COH for _ in range(20)]
        self.assertEqual(evaluate(raw)["aggregate"]["paired"], evaluate(study([(15, 7, 15, 1)] * 5))["aggregate"]["paired"])
        many_nr = study([(15, 7, 15, 1)] * 5) + [make(c, 0.5, None, o900="STRUCTURAL") for c in COH for _ in range(30)]
        self.assertTrue(evaluate(many_nr)["worst_case_sensitivity_non_gating"]["direction_reverses_under_worst_case"])

    def test_pooled_with_v1_descriptive(self):
        groups = {"KEPT": {"n": 10, "catastrophic": 1}, "REJECTED": {"n": 10, "catastrophic": 5}}
        v1r = {"aggregate": {"groups": {"KEPT": {"n": 66, "catastrophic": 8}, "REJECTED": {"n": 76, "catastrophic": 31}}}}
        p = an.pooled_with_v1(groups, v1r)
        self.assertEqual((p["KEPT"]["n"], p["REJECTED"]["catastrophic"]), (76, 36))
        self.assertIsNone(an.pooled_with_v1(groups, None))


class ReportGuardTests(unittest.TestCase):
    def test_refuses_until_frozen_and_complete_and_checks_dates(self):
        orig = collect.PROTOCOL_SHA256
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                collect.PROTOCOL_SHA256 = None
                self.assertIn("not frozen", an.check_reports(root)[2])
                collect.PROTOCOL_SHA256 = "a" * 64
                self.assertIn("CONTINUE", an.check_reports(root)[2])
                for i, l in enumerate(COH):
                    collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                    "protocol_sha256": "a" * 64, "started_utc_date": DATES[l]}, l, root)
                valid, dates, problem = an.check_reports(root)
                self.assertEqual((valid, problem), (list(COH), None))
                self.assertEqual(dates, DATES)
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "protocol_sha256": "a" * 64, "started_utc_date": "2026-09-30"}, "H5", root)
                self.assertIn("V1 collection day", an.check_reports(root)[2])
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "protocol_sha256": "b" * 64, "started_utc_date": "2026-10-06"}, "H5", root)
                self.assertIn("hash", an.check_reports(root)[2])
        finally:
            collect.PROTOCOL_SHA256 = orig


class DiagnosticTests(unittest.TestCase):
    def test_overlap_counts(self):
        pairs = [("G1", "A"), ("G1", "B"), ("G2", "A"), ("G2", "C"), ("G2", "C")]
        o = diag.overlap_counts(pairs)
        self.assertEqual((o["episodes"], o["distinct_tokens"], o["repeat_episodes"], o["tokens_in_more_than_one_cohort"]),
                         (5, 3, 2, 1))
        self.assertEqual(o["per_cohort"]["G2"], {"episodes": 3, "distinct_tokens": 2})


if __name__ == "__main__":
    unittest.main()
