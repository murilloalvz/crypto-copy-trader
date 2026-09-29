import unittest

from research import export_v55_price_path_v0 as pathx
from research import simulate_exit_hypotheses_v0 as sim


def ep(key, as_of, buckets, ref=1.0):
    return {"episode_key": key, "decision_as_of": as_of, "ref_trade_price_usd": ref, "buckets": buckets}


class ExitRuleTests(unittest.TestCase):
    def test_tp_fills_at_level(self):
        e = ep("k1", 0, [[5, 1.0, 1.6, 1.5]])
        self.assertEqual(sim.simulate_exit(e, 50.0, None, 3600, 120), (50.0, 5))

    def test_sl_wins_same_bucket_and_gap_aware(self):
        e = ep("k1", 0, [[5, 0.5, 2.0, 0.4]])
        ret, _ = sim.simulate_exit(e, 50.0, -30.0, 3600, 120)
        self.assertAlmostEqual(ret, -60.0)  # min(SL level 0.7, last 0.4)

    def test_time_exit_and_stale(self):
        e = ep("k1", 0, [[100, 1.0, 1.2, 1.1]])
        self.assertAlmostEqual(sim.simulate_exit(e, None, None, 3600, 120) is None, True)
        self.assertAlmostEqual(sim.simulate_exit(e, None, None, 150, 120)[0], 10.0)

    def test_no_reference_not_evaluable(self):
        self.assertIsNone(sim.simulate_exit(ep("k", 0, [[5, 1, 1, 1]], ref=None), None, None, 300, 300))

    def test_overlap_skipped(self):
        eps = [ep("aaaaaaaa1", 0, [[300, 1, 1.1, 1.1]]), ep("aaaaaaaa2", 100, [[300, 1, 1.1, 1.1]])]
        s, se, so = sim.run_rule(eps, None, None, 300, stale=300, cost_pct=0, balance=100, allocation=30, overlap="skip")
        self.assertEqual((len(s.points), so), (1, 1))

    def test_checkpoint_csv_path_and_sequential_default(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "r.csv"
            f.write_text(
                "episode_key,cohort,decision_as_of,flow60_buy_share_pct,return_pct_300s,return_pct_900s,"
                "return_pct_3600s,status_300s,status_900s,status_3600s\n"
                "aaaaaaaa1,A,0,50,20,120,,A,A,U\n"
                "aaaaaaaa2,A,10,60,-40,,,A,U,U\n", encoding="utf-8")
            eps = sim.episodes_from_returns_csv(f)
        self.assertEqual(sim.simulate_exit(eps[0], 100.0, None, 3600, 120), (100.0, 900))
        self.assertAlmostEqual(sim.simulate_exit(eps[1], None, -30.0, 3600, 120)[0], -40.0)
        s1, _, so1 = sim.run_rule(eps, 100.0, -30.0, 3600, stale=120, cost_pct=0, balance=100, allocation=30)
        self.assertEqual((len(s1.points), so1), (2, 0))  # sequential default: overlap not skipped
        s2, _, so2 = sim.run_rule(eps, 100.0, -30.0, 3600, stale=120, cost_pct=0, balance=100, allocation=30, overlap="skip")
        self.assertEqual((len(s2.points), so2), (1, 1))

    def test_path_builder_causal(self):
        from types import SimpleNamespace as N
        def t(obs, price):
            return N(observation=N(observed_at=obs, chain_time=obs, price_usd=price))
        p = pathx.build_path([t(90, 2.0), t(105, 3.0), t(200, 1.0), t(9999, 5.0)], 100)
        self.assertEqual(p["ref_trade_price_usd"], 2.0)  # last at/before decision
        self.assertEqual(p["buckets"][0], [5, 3.0, 3.0, 3.0])
        self.assertEqual(p["n_trades_after"], 2)  # beyond 3600s excluded


if __name__ == "__main__":
    unittest.main()
