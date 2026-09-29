import unittest

from research import study_v55_rejection_lens_v0 as st


class RejectionLensTests(unittest.TestCase):
    def rows(self, n=40):
        out = []
        for i in range(n):
            ret = -95.0 if i < 10 else 10.0  # first 10 catastrophic
            out.append({
                "episode_key": f"e{i}", "cohort": "A", "decision_as_of": str(i),
                "return_pct_300s": "", "return_pct_900s": str(ret), "return_pct_3600s": "",
                "status_300s": "", "status_900s": "AVAILABLE", "status_3600s": "",
                "f_signal": str(i),           # perfectly separates the tail
                "f_noise": str((i * 7) % 5),  # unrelated
                "f_sparse": "" if i % 2 else "1",  # 50% coverage -> skipped
                "f_text": "abc",
            })
        return out

    def test_separating_feature_found_and_skips_reported(self):
        usable, ncat, res, skipped = st.study(self.rows())
        self.assertEqual((len(usable), ncat), (40, 10))
        by = {r["feature"]: r for r in res}
        self.assertLess(by["f_signal"]["p_adj"], 0.05)
        self.assertGreater(by["f_signal"]["cat_low"], by["f_signal"]["cat_high"])
        self.assertEqual({f for f, _ in skipped}, {"f_sparse", "f_text"})
        self.assertEqual([r["feature"] for r in res], sorted(by))  # alphabetical, no cherry-pick


if __name__ == "__main__":
    unittest.main()
