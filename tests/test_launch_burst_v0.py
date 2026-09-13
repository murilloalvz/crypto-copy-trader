import unittest

from src.launch_burst_v0 import (
    LAUNCH_BURST_VERSION,
    LaunchBurstConfig,
    build_launch_burst_snapshot,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class LaunchBurstV0Tests(unittest.TestCase):
    def _life(self, *, venue="pump_bonding_curve", started=1000, observed=2000):
        return MarketLifecycleObservation(
            token_mint="TOKEN",
            market_started_at=started,
            observed_at=observed,
            venue=venue,
        )

    def _trade(
        self,
        *,
        chain_time,
        observed_at,
        side="buy",
        token="TOKEN",
        wallet="wallet",
        tx="tx",
        notional=10.0,
        price=1.0,
        venue="pump_bonding_curve",
    ):
        return MarketTradeObservation(
            token_mint=token,
            side=side,
            chain_time=chain_time,
            observed_at=observed_at,
            wallet_address=wallet,
            transaction_key=tx,
            notional_usd=notional,
            price_usd=price,
            venue=venue,
        )

    def test_snapshot_uses_independent_chain_and_observation_cutoffs(self):
        trades = [
            self._trade(chain_time=1000, observed_at=2001, tx="a", price=1.0),
            self._trade(chain_time=1030, observed_at=2030, tx="b", price=1.2),
            self._trade(chain_time=1031, observed_at=2020, tx="outside-chain"),
            self._trade(chain_time=1010, observed_at=2031, tx="future-observation"),
            self._trade(chain_time=1010, observed_at=2010, token="OTHER", tx="other-token"),
        ]
        snapshot = build_launch_burst_snapshot(
            trades,
            lifecycle=self._life(),
            decision_as_of=2030,
            config=LaunchBurstConfig(observation_window_seconds=30),
        )
        self.assertEqual(snapshot.event_count, 2)
        self.assertEqual(snapshot.chain_t0, 1000)
        self.assertEqual(snapshot.observed_t0, 2000)
        self.assertEqual(snapshot.chain_window_end, 1030)
        self.assertEqual(snapshot.window_return_pct, 20.0)
        self.assertEqual(snapshot.method_version, LAUNCH_BURST_VERSION)

    def test_trade_not_locally_available_by_decision_is_never_used(self):
        visible = self._trade(chain_time=1005, observed_at=2005, tx="visible")
        leaked = self._trade(
            chain_time=1006,
            observed_at=2099,
            side="sell",
            tx="future",
            notional=999.0,
            price=0.1,
        )
        snapshot = build_launch_burst_snapshot(
            [visible, leaked], lifecycle=self._life(), decision_as_of=2030
        )
        self.assertEqual(snapshot.event_count, 1)
        self.assertEqual(snapshot.buy_count, 1)
        self.assertEqual(snapshot.sell_count, 0)
        self.assertEqual(snapshot.known_notional_usd, 10.0)

    def test_pump_and_pumpswap_are_separate_strata(self):
        pump = build_launch_burst_snapshot(
            [], lifecycle=self._life(venue="pump_bonding_curve"), decision_as_of=2030
        )
        swap = build_launch_burst_snapshot(
            [], lifecycle=self._life(venue="pump_swap"), decision_as_of=2030
        )
        self.assertEqual(pump.stratum, "pump_launch")
        self.assertEqual(swap.stratum, "pumpswap_liquidity_launch")
        self.assertNotEqual(pump.stratum, swap.stratum)

    def test_boundary_is_inclusive_at_chain_window_end(self):
        snapshot = build_launch_burst_snapshot(
            [
                self._trade(chain_time=1030, observed_at=2020, tx="inside"),
                self._trade(chain_time=1031, observed_at=2020, tx="outside"),
            ],
            lifecycle=self._life(),
            decision_as_of=2030,
            config=LaunchBurstConfig(observation_window_seconds=30),
        )
        self.assertEqual(snapshot.event_count, 1)

    def test_partial_data_is_explicit_not_silently_imputed(self):
        snapshot = build_launch_burst_snapshot(
            [
                self._trade(
                    chain_time=1005,
                    observed_at=2005,
                    wallet=None,
                    tx=None,
                    notional=None,
                    price=None,
                )
            ],
            lifecycle=self._life(),
            decision_as_of=2030,
        )
        self.assertIsNone(snapshot.known_notional_buy_share_pct)
        self.assertIsNone(snapshot.window_return_pct)
        self.assertIn("partial_wallet_identity_coverage", snapshot.data_quality_flags)
        self.assertIn("partial_transaction_identity_coverage", snapshot.data_quality_flags)
        self.assertIn("partial_notional_coverage", snapshot.data_quality_flags)
        self.assertIn("partial_price_coverage", snapshot.data_quality_flags)

    def test_unsupported_lifecycle_venue_fails_closed(self):
        with self.assertRaises(ValueError):
            build_launch_burst_snapshot(
                [], lifecycle=self._life(venue="unknown"), decision_as_of=2030
            )

    def test_decision_cannot_precede_lifecycle_observation(self):
        with self.assertRaises(ValueError):
            build_launch_burst_snapshot(
                [], lifecycle=self._life(), decision_as_of=1999
            )


if __name__ == "__main__":
    unittest.main()
