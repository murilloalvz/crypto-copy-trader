import random
import unittest

from research import discover_kept_group_v0 as dk

_n = [0]


def raw_row(study, impact, ret900, features, token=None, o900="AVAILABLE_ON_TIME", ret300=None, group_impact=None):
    _n[0] += 1
    return {"cohort": "G1" if study == "V1" else "H1", "episode_key": f"e{_n[0]}", "token": token or f"t{_n[0]}",
            "as_of": _n[0], "impact": impact, "mint_auth": False, "freeze_auth": False,
            "labels": {300: ret300 if ret300 is not None else ret900, 900: ret900, 3600: None}, "statuses": {},
            "o900": o900, "features": {"entry_price_impact_pct_points": impact, **features}, "study": study}


def synthetic(n=120, signal=True, seed=3):
    r = random.Random(seed)
    raw = []
    for i in range(n):
        s = "V1" if i % 2 == 0 else "V2"
        sig = r.random()
        noise = r.random()
        ret = (sig * 100 - 50 + r.gauss(0, 10)) if signal else r.gauss(0, 40)
        raw.append(raw_row(s, 0.5 + 1.0 * r.random(), ret, {"f_signal": sig, "f_noise": noise,
                                                           "f_const": 1.0, "f_bool": r.random() < 0.5,
                                                           "f_text": "a", "f_sparse": None if i % 2 else 1.0}))
    return raw


class StatsTests(unittest.TestCase):
    def test_spearman_and_permutation(self):
        x = list(range(30))
        self.assertAlmostEqual(dk.spearman(x, [v * 2 for v in x]), 1.0)
        self.assertAlmostEqual(dk.spearman(x, [-v for v in x]), -1.0)
        rho, p = dk.perm_p_two_sided(x, [v + 0.1 * (i % 3) for i, v in enumerate(x)], random.Random(1), perms=2000)
        self.assertGreater(rho, 0.95)
        self.assertLess(p, 0.01)
        rho, p = dk.perm_p_two_sided(x, [(i * 7) % 11 for i in x], random.Random(1), perms=2000)
        self.assertGreater(p, 0.05)

    def test_min_detectable_rho(self):
        self.assertLess(dk.min_detectable_rho(400, 22), dk.min_detectable_rho(100, 22))
        self.assertLess(dk.min_detectable_rho(100, 1), dk.min_detectable_rho(100, 22))
        self.assertAlmostEqual(dk.min_detectable_rho(100, 22), 0.40, delta=0.05)
        self.assertIsNone(dk.min_detectable_rho(3, 5))


class DiscoveryTests(unittest.TestCase):
    def sample(self, raw):
        return dk.kept_sample(dk.prepare(raw))

    def test_finds_planted_signal_and_not_noise_and_reports_skips(self):
        res = dk.discover(self.sample(synthetic(120, signal=True)))
        by = {r["feature"]: r for r in res["features"]}
        self.assertIn("f_signal", res["robust_candidates"])
        self.assertTrue(by["f_signal"]["sign_agreement"])
        self.assertNotIn("f_noise", res["robust_candidates"])
        self.assertNotIn("f_bool", res["robust_candidates"])
        skipped = {n for n, _ in res["skipped"]}
        self.assertEqual(skipped, {"f_const", "f_text", "f_sparse"})
        self.assertEqual([r["feature"] for r in res["features"]], sorted(by))  # alphabetical, no ranking
        self.assertIn("abs_entry_price_impact_pp", by)
        self.assertNotIn("entry_price_impact_pct_points", by)

    def test_pure_noise_has_no_candidates(self):
        res = dk.discover(self.sample(synthetic(120, signal=False, seed=11)))
        self.assertEqual(res["robust_candidates"], [])

    def test_sign_disagreement_between_studies_blocks_candidate(self):
        raw = []
        r = random.Random(5)
        for i in range(160):
            s = "V1" if i % 2 == 0 else "V2"
            f = r.random()
            ret = (f * 100 if s == "V1" else -f * 100)  # opposite relation in the two studies
            raw.append(raw_row(s, 1.0, ret + r.gauss(0, 5), {"f_flip": f}))
        res = dk.discover(self.sample(raw))
        flip = res["features"][0]
        self.assertFalse(flip["sign_agreement"])
        self.assertEqual(res["robust_candidates"], [])

    def test_sample_rules(self):
        raw = [raw_row("V1", 0.5, 10.0, {"f": 1.0}, token="A"),
               raw_row("V2", 0.5, -5.0, {"f": 2.0}, token="A"),                 # repeat token -> dropped
               raw_row("V1", 5.0, -90.0, {"f": 3.0}, token="B"),                # REJECTED -> not KEPT
               raw_row("V1", 0.5, 7.0, {"f": 4.0}, token="C", o900="LATE"),     # late label -> dropped
               raw_row("V2", 1.9, 3.0, {"f": 5.0}, token="D"),
               raw_row("V2", 2.0, 4.0, {"f": 6.0}, token="E")]                  # boundary impact 2.0 -> KEPT
        kept = self.sample(raw)
        self.assertEqual(sorted(r["token"] for r in kept), ["A", "D", "E"])
        self.assertEqual([r["study"] for r in kept if r["token"] == "A"], ["V1"])  # earliest wins

    def test_render_has_label_and_all_features(self):
        res = dk.discover(self.sample(synthetic(120)))
        text = dk.render(res)
        self.assertIn("HYPOTHESIS GENERATION ONLY", text)
        self.assertIn("não é validação", text.lower().replace("Não", "não"))
        for r in res["features"]:
            self.assertIn(r["feature"], text)


if __name__ == "__main__":
    unittest.main()
