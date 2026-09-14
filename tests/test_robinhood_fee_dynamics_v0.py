import unittest

from benchmarks.robinhood_launch_burst_v0.fee_dynamics import build_fee_dynamics_snapshot_v0
from src.robinhood_pons_launch_burst_v0 import (
    PonsLaunchObservationV0,
    PonsTradeObservationV0,
    ZERO_ADDRESS,
)


class RobinhoodFeeDynamicsV0Tests(unittest.TestCase):
    def setUp(self):
        self.launch = PonsLaunchObservationV0(
            "0x" + "11" * 20,
            "0x" + "22" * 20,
            "0x" + "33" * 20,
            ZERO_ADDRESS,
            0,
            1000,
            100,
            0,
            1,
            "0xlaunch",
            "0xblock100",
            1_000_000_000,
            1000,
        )

    def trade(self, actor, quote, fee, tax, delay_ms, block_ts, idx):
        return PonsTradeObservationV0(
            "BUY",
            self.launch.curve,
            actor,
            actor,
            quote,
            1000,
            fee,
            tax,
            100 + idx,
            0,
            idx,
            f"0xtx{idx}",
            f"0xblock{100 + idx}",
            self.launch.observed_at_ns + delay_ms * 1_000_000,
            block_ts,
        )

    def test_fee_decay_is_measured_not_decomposed(self):
        buyer = "0x" + "44" * 20
        rows = [
            self.trade(buyer, 10_000, 5_000, 100, 200, 1000, 2),
            self.trade(buyer, 10_000, 1_000, 100, 800, 1001, 3),
            self.trade(buyer, 10_000, 200, 100, 1800, 1002, 4),
        ]
        result = build_fee_dynamics_snapshot_v0(
            launch=self.launch,
            trades=rows,
            horizon_seconds=5,
        )
        self.assertEqual(result["buy_count"], 3)
        self.assertEqual(result["first_buy_fee_bps_observed"], 5000.0)
        self.assertEqual(result["last_buy_fee_bps_observed"], 200.0)
        self.assertEqual(result["fee_drop_first_to_last_bps"], 4800.0)
        self.assertEqual(result["first_buy_chain_age_s"], 0)
        self.assertEqual(result["last_buy_chain_age_s"], 2)

    def test_known_deployer_exemption_is_separated(self):
        buyer = "0x" + "44" * 20
        rows = [
            self.trade(self.launch.deployer, 10_000, 100, 100, 100, 1000, 2),
            self.trade(buyer, 10_000, 3_000, 100, 300, 1000, 3),
        ]
        result = build_fee_dynamics_snapshot_v0(
            launch=self.launch,
            trades=rows,
            horizon_seconds=1,
        )
        self.assertEqual(result["first_buy_fee_bps_observed"], 100.0)
        self.assertEqual(result["first_non_deployer_buy_fee_bps_observed"], 3000.0)
        self.assertEqual(result["non_deployer_buy_count"], 1)


if __name__ == "__main__":
    unittest.main()
