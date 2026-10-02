import json
import math
import tempfile
import unittest
from pathlib import Path

import rejection_filter_holdout_v3_analyze as an
import rejection_filter_holdout_v3_collect as collect

COHORTS = tuple(f"T{i}" for i in range(1, 11))
DATES = {c: f"2026-10-{5 + i // 3:02d}" for i, c in enumerate(COHORTS)}  # 3/3/3/1 -> 4 days
STARTS = {c: 1000 + i for i, c in enumerate(COHORTS)}
_n = [0]


def raw(cohort, impact, ret, feat=None, token=None, o900="AVAILABLE_ON_TIME", mint=None):
    _n[0] += 1
    return {"cohort": cohort, "episode_key": f"e{_n[0]}", "token": token or f"tok{_n[0]}", "as_of": _n[0],
            "impact": impact, "mint_auth": mint, "freeze_auth": None,
            "labels": {300: ret, 900: ret, 3600: None}, "statuses": {}, "o900": o900,
            "features": {an.FEATURE: feat}}


def build(spec_per_cohort):
    """spec: list of (impact, ret, feat)."""
    data = []
    for c in COHORTS:
        data += [raw(c, *s) for s in spec_per_cohort]
    return an.prepare_rows_v3(data)


# per cohort: 4 REJECTED (3 catastrophic), 4 KEPT (0 catastrophic) -> 40 + 40 = 80 paired
P1_SPEC = [(5.0, -90.0, 0.0), (6.0, -95.0, 0.0), (7.0, -85.0, 0.0), (3.0, 10.0, 0.0),
           (0.5, 5.0, 0.0), (1.0, -10.0, 0.0), (0.2, 20.0, 0.0), (1.5, 8.0, 0.0)]


def evaluate(rows, **kw):
    return an.evaluate_v3(rows, COHORTS, kw.get("prior", set()), kw.get("dates", DATES), STARTS)


class P1Tests(unittest.TestCase):
    def rows(self, n_cohort_repeat=2):
        return build(P1_SPEC * n_cohort_repeat)

    def test_confirmed(self):
        rep = evaluate(self.rows(2))["p1"]
        # tokens are unique, so 16 paired per cohort -> 160 total
        self.assertTrue(all(rep["support_checks"].values()), rep["support_checks"])
        self.assertEqual(rep["classification"], an.P1_CONFIRMED)
        self.assertAlmostEqual(rep["effect_values"]["cat_diff_pp"], 75.0)

    def test_support_failure_when_too_few_paired(self):
        rep = evaluate(self.rows(1))["p1"]  # 80 paired < 120
        self.assertEqual(rep["classification"], an.P1_INC_SUPPORT)
        self.assertFalse(rep["support_checks"]["paired_total_ge_120"])

    def test_day_rule_failure_is_support(self):
        dates = {c: "2026-10-05" for c in COHORTS}
        rep = evaluate(self.rows(2), dates=dates)["p1"]
        self.assertEqual(rep["classification"], an.P1_INC_SUPPORT)
        self.assertFalse(rep["support_checks"]["utc_days_ge_3_and_max_3_per_day"])

    def test_no_effect_is_not_confirmed(self):
        spec = [(5.0, -90.0, 0.0), (6.0, 10.0, 0.0), (7.0, 10.0, 0.0), (3.0, 10.0, 0.0),
                (0.5, -90.0, 0.0), (1.0, 10.0, 0.0), (0.2, 20.0, 0.0), (1.5, 8.0, 0.0)]
        rep = evaluate(build(spec * 2))["p1"]
        self.assertEqual(rep["classification"], an.P1_NOT_CONFIRMED)
        self.assertFalse(rep["effect_checks"]["diff_ge_15pp"] and rep["effect_checks"]["fisher_one_sided_p_lt_0_025"])

    def test_kept_share_gate(self):
        spec = [(5.0, -90.0, 0.0)] * 6 + [(5.0, 10.0, 0.0)] * 4 + [(0.5, 5.0, 0.0)] * 2  # KEPT 12.5%
        rep = evaluate(build(spec * 2))["p1"]
        self.assertFalse(rep["effect_checks"]["kept_share_30_to_85"])
        self.assertEqual(rep["classification"], an.P1_NOT_CONFIRMED)

    def test_direction_gate_counts_only_evaluable_cohorts(self):
        rows = self.rows(2)
        # make the last cohort wrong-way AND the second-last not evaluable: still >=70% of evaluable correct
        for r in rows:
            if r["cohort"] == "T10":
                r["ret900"] = -90.0 if r["group"] == "KEPT" else 10.0
                r["labels"] = {**r["labels"], 900: r["ret900"]}
        rep = evaluate(rows)["p1"]
        self.assertEqual(rep["effect_values"]["cohorts_with_correct_direction"], 9)
        self.assertEqual(rep["classification"], an.P1_CONFIRMED)

    def test_coverage_measured_before_token_exclusions(self):
        rows = self.rows(2)
        prior = {r["token"] for r in rows if r["cohort"] == "T1"}
        out = evaluate(rows, prior=prior)
        self.assertEqual(out["token_exclusions_non_gating"]["T1"]["SEEN_IN_PRIOR_STUDY"], 16)
        # T1 loses all rows after exclusion but coverage is judged on the pre-exclusion rows
        self.assertTrue(out["p1"]["support_checks"]["impact_coverage_ge_80_every_cohort"])

    def test_missing_late_and_authority_are_never_values(self):
        data = [raw("T1", 5.0, -90.0, o900="LATE"), raw("T1", None, 10.0), raw("T1", 5.0, -90.0, mint=True)]
        rows = an.prepare_rows_v3(data)
        self.assertIsNone(rows[0]["ret900"])
        self.assertEqual(rows[1]["group"], "UNCLASSIFIED")
        self.assertTrue(rows[2]["excluded_authority"])

    def test_negative_signed_impact_uses_abs(self):
        rows = an.prepare_rows_v3([raw("T1", -5.0, -90.0), raw("T1", -1.0, 1.0)])
        self.assertEqual([r["group"] for r in rows], ["REJECTED", "KEPT"])


def p2_rows(corr=True, n_per_cohort=16):
    data = []
    for i, c in enumerate(COHORTS):
        for k in range(n_per_cohort):
            feat = float(k)
            ret = (feat * 3.0 - 20.0 + (k % 3)) if corr else (-(feat) * 3.0 + 10.0)
            data.append(raw(c, 0.5, ret, feat=feat))
    return an.prepare_rows_v3(data)


class P2Tests(unittest.TestCase):
    def test_keep_on_positive_relation(self):
        rep = evaluate(p2_rows(True))["p2"]
        self.assertTrue(all(rep["support_checks"].values()), rep["support_checks"])
        self.assertEqual(rep["classification"], an.P2_KEEP)
        self.assertTrue(all(rep["effect_checks"].values()), rep["effect_checks"])

    def test_kill_on_reverse_relation(self):
        rep = evaluate(p2_rows(False))["p2"]
        self.assertEqual(rep["classification"], an.P2_KILL)
        self.assertFalse(rep["effect_checks"]["spearman_rho_gt_0_perm_p_lt_0_025"])

    def test_support_failures(self):
        rep = evaluate(p2_rows(True, n_per_cohort=8))["p2"]  # 80 < 120
        self.assertEqual(rep["classification"], an.P2_INC_SUPPORT)
        rows = p2_rows(True)
        for i, r in enumerate(rows):
            if i % 2:
                r["features"] = {an.FEATURE: None}
        rep = evaluate(rows)["p2"]
        self.assertFalse(rep["support_checks"]["feature_known_ge_80pct_of_kept_paired"])
        self.assertEqual(rep["classification"], an.P2_INC_SUPPORT)

    def test_cutoff_is_outcome_blind(self):
        rows = p2_rows(True)
        before = an.p2_cutoff(rows)
        for r in rows:
            r["ret900"] = -r["ret900"]
        self.assertEqual(an.p2_cutoff(rows), before)
        # rows without a usable outcome still shape the cutoff (eligible = KEPT with feature known)
        extra = an.prepare_rows_v3([raw("T1", 0.5, 5.0, feat=1000.0, o900="LATE")] * 40)
        self.assertGreater(an.p2_cutoff(rows + extra), before)

    def test_ties_go_to_low(self):
        rows = an.prepare_rows_v3([raw("T1", 0.5, float(i), feat=1.0) for i in range(10)])
        rep = an.evaluate_p2(rows, {"T1": 1}, True)
        self.assertEqual(rep["groups_non_gating"]["HIGH"]["n"], 0)
        self.assertEqual(rep["groups_non_gating"]["LOW"]["n"], 10)

    def test_half_split_sign_consistency_gate(self):
        rows = p2_rows(True)
        # flip the relation in the later half only
        for r in rows:
            if int(r["cohort"][1:]) > 5:
                r["ret900"] = -r["ret900"]
                r["labels"] = {**r["labels"], 900: r["ret900"]}
        rep = evaluate(rows)["p2"]
        self.assertFalse(rep["effect_checks"]["rho_gt_0_in_both_halves"])
        self.assertEqual(rep["classification"], an.P2_KILL)

    def test_p2_independent_of_p1(self):
        out = evaluate(p2_rows(True))
        self.assertEqual(out["p2"]["classification"], an.P2_KEEP)
        self.assertEqual(out["p1"]["classification"], an.P1_INC_SUPPORT)  # no REJECTED rows at all


class MathTests(unittest.TestCase):
    def test_profit_factor_infinity_and_json(self):
        self.assertEqual(an.profit_factor([5.0, 1.0]), math.inf)
        self.assertEqual(an.profit_factor([-5.0, 10.0]), 2.0)
        self.assertIsNone(an.profit_factor([]))
        self.assertEqual(an.mean_without_best([1.0, 2.0, 9.0]), 1.5)
        self.assertIsNone(an.mean_without_best([1.0]))
        json.dumps(an.clean({"a": [math.inf, {"b": -math.inf}]}), allow_nan=False)

    def test_permutation_is_deterministic_and_one_sided(self):
        x = [float(i) for i in range(30)]
        y = [float(i) + (i % 3) for i in range(30)]
        a = an.one_sided_perm_p(x, y, perms=500)
        self.assertEqual(a, an.one_sided_perm_p(x, y, perms=500))
        self.assertLess(a[1], 0.01)
        rho, p = an.one_sided_perm_p(x, [-v for v in y], perms=500)
        self.assertLess(rho, 0)
        self.assertGreater(p, 0.9)

    def test_impact_bins_and_reports_cover_all_rows(self):
        rep = evaluate(build(P1_SPEC * 2))
        total = sum(b["n"] for b in rep["impact_bins_non_gating"])
        self.assertEqual(total, 160)
        self.assertIn("flow60_buy_share_pct", rep["other_buy_pressure_features_rho_non_gating"])
        self.assertEqual(rep["kept_share_vs_projection_non_gating"]["projected_pct"], 57.0)


class GateTests(unittest.TestCase):
    def test_refuses_unfrozen_protocol_and_partial_study(self):
        with self.assertRaises(SystemExit):
            an.run_analysis()  # PROTOCOL_SHA256 is None until freeze
        orig = collect.PROTOCOL_SHA256
        try:
            collect.PROTOCOL_SHA256 = "a" * 64
            with tempfile.TemporaryDirectory() as d:
                valid, dates, starts, problem = an.check_reports(Path(d))
                self.assertIsNone(valid)
                self.assertIn("CONTINUE", problem)
                root = Path(d)
                for i, c in enumerate(COHORTS):
                    collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                    "started_utc_date": DATES[c], "started_at": STARTS[c],
                                    "protocol_sha256": "a" * 64, "order_notional_usd": 10.0}, c, root)
                valid, dates, starts, problem = an.check_reports(root)
                self.assertIsNone(problem)
                self.assertEqual(valid, list(COHORTS))
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "started_utc_date": "2026-10-05", "started_at": 1, "protocol_sha256": "b" * 64,
                                "order_notional_usd": 10.0}, "T1", root)
                self.assertIn("hash", an.check_reports(root)[3])
                collect._write({"classification": collect.ACQ_DONE, "cohort_validity": collect.VALID,
                                "started_utc_date": "2026-10-05", "started_at": 1, "protocol_sha256": "a" * 64,
                                "order_notional_usd": 25.0}, "T1", root)
                self.assertIn("order size", an.check_reports(root)[3])
        finally:
            collect.PROTOCOL_SHA256 = orig

    def test_prior_run_keys_cover_v0_v1_v2(self):
        keys = an.prior_run_keys()
        self.assertIn("rejection-filter-v0-20260929-01-F1", keys)
        self.assertIn("rejection-filter-v1-20260929-01-G6", keys)
        self.assertIn("rejection-filter-v2-20260930-01-H7", keys)
        self.assertEqual(len(keys), 1 + 6 + 7)


if __name__ == "__main__":
    unittest.main()
