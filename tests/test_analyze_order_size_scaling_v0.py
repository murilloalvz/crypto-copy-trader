import unittest

from research import analyze_order_size_scaling_v0 as sz


def row(impact, ret, status="OK", authority=False):
    return {"token_status": status, "excluded_authority": authority, "impact": impact, "ret900": ret}


class ScalingTests(unittest.TestCase):
    def test_equivalent_cap_and_projection(self):
        self.assertAlmostEqual(sz.equivalent_cap_at_base(25.0), 2.0)
        self.assertAlmostEqual(sz.equivalent_cap_at_base(10.0), 5.0)
        self.assertAlmostEqual(sz.equivalent_cap_at_base(50.0), 1.0)
        impacts = [0.5, 1.0, 1.9, 3.0, 6.0, 12.0, 40.0, 0.2]
        self.assertAlmostEqual(sz.projected_kept_share(impacts, 25.0), 100 * 4 / 8)   # <= 2.0
        self.assertAlmostEqual(sz.projected_kept_share(impacts, 10.0), 100 * 5 / 8)   # <= 5.0
        self.assertAlmostEqual(sz.projected_kept_share(impacts, 50.0), 100 * 3 / 8)   # <= 1.0
        self.assertIsNone(sz.projected_kept_share([], 25.0))
        # smaller orders keep a larger share, larger orders a smaller one
        shares = [sz.projected_kept_share(impacts, s) for s in (10.0, 25.0, 50.0)]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_dose_response_bins_and_boundaries(self):
        pairs = [(0.0, 5.0), (0.5, 1.0), (0.6, -90.0), (2.0, -50.0), (2.1, -95.0), (30.0, -99.0)]
        bins = {b["bin_pp"]: b for b in sz.dose_response(pairs)}
        self.assertEqual(bins["(0, 0.5]"]["n"], 2)        # 0.0 and 0.5 (upper bound inclusive, 0 in first bin)
        self.assertEqual(bins["(0.5, 1]"]["n"], 1)
        self.assertEqual(bins["(1, 2]"]["n"], 1)          # 2.0 belongs here, matching the rule (<= 2.0 is KEPT)
        self.assertEqual(bins["(2, 5]"]["n"], 1)
        self.assertEqual(bins["> 25"]["catastrophic"], 1)
        self.assertEqual(sum(b["n"] for b in bins.values()), len(pairs))

    def test_cap_table_two_pp_matches_the_frozen_rule(self):
        pairs = [(0.5, 10.0), (1.0, -90.0), (2.0, 5.0), (2.5, -95.0), (9.0, -99.0)]
        t = {c["cap_at_25_pp"]: c for c in sz.cap_table(pairs)}
        self.assertEqual((t[2.0]["kept_n"], t[2.0]["rejected_n"]), (3, 2))
        self.assertAlmostEqual(t[2.0]["kept_cat_rate_pct"], 100 / 3)
        self.assertAlmostEqual(t[2.0]["rejected_cat_rate_pct"], 100.0)

    def test_analyze_applies_dedup_authority_and_missing(self):
        rows = [row(0.5, 5.0), row(1.0, None), row(3.0, -90.0), row(0.7, 1.0, status="REPEAT"),
                row(0.9, 2.0, authority=True), row(None, 4.0), row("x", 1.0)]
        res = sz.analyze(rows)
        self.assertEqual(res["episodes_deduped_with_impact"], 3)
        self.assertEqual(res["paired_with_900s_return"], 2)
        text = sz.render(res)
        self.assertIn("NÃO testa outros tamanhos", text)
        self.assertIn("US$25", text)


class PipelineTests(unittest.TestCase):
    """Goes through the real preparation path (raw loader rows -> prepare -> dedup -> analyze)."""

    def raw(self, ep, token, impact, ret, study="V1", o900="AVAILABLE_ON_TIME"):
        return {"cohort": "G1", "episode_key": ep, "token": token, "as_of": int(ep[1:]), "impact": impact,
                "mint_auth": False, "freeze_auth": False, "labels": {300: ret, 900: ret, 3600: None},
                "statuses": {}, "o900": o900, "features": {"entry_price_impact_pct_points": impact}, "study": study}

    def test_real_preparation_path_keeps_impact(self):
        from research import discover_kept_group_v0 as dk
        import rejection_filter_holdout_v2_analyze as an2
        raw = [self.raw("e1", "A", 0.5, 5.0), self.raw("e2", "B", -3.0, -90.0, study="V2"),
               self.raw("e3", "A", 0.6, 9.0), self.raw("e4", "C", 8.0, None, o900="STRUCTURAL")]
        rows = dk.prepare(raw)
        an2.apply_token_exclusions(rows, set())
        res = sz.analyze(rows)
        self.assertEqual(res["episodes_deduped_with_impact"], 3)   # e3 is a REPEAT of token A
        self.assertEqual(res["paired_with_900s_return"], 2)        # e4 has no 900s return
        bins = {b["bin_pp"]: b for b in res["dose_response_vs_impact_at_25"]}
        self.assertEqual(bins["(2, 5]"]["catastrophic"], 1)        # |-3.0| uses the absolute value


if __name__ == "__main__":
    unittest.main()
