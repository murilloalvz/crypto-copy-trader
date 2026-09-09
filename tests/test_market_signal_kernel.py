from dataclasses import asdict
import unittest

from benchmarks.integrated_market_signal_plane_v1.differential import generate_long_horizon_trace
from benchmarks.commodity_signal_plane_v0.benchmark import ReferenceRadarState
from src.market_opportunity_radar import MarketTradeObservation
from src.market_signal_kernel import IndexedMarketSignalKernel


def _snapshot(trigger):
    if trigger is None:
        return None
    return {
        "token_mint": trigger.token_mint,
        "as_of": trigger.as_of,
        "method_version": trigger.method_version,
        "trigger_kind": trigger.trigger_kind,
        "direction": trigger.direction,
        "features": asdict(trigger.features),
    }


class IndexedMarketSignalKernelTests(unittest.TestCase):
    def test_long_horizon_differential_matches_frozen_radar(self):
        for seed in (11, 29, 68, 97):
            reference = ReferenceRadarState()
            kernel = IndexedMarketSignalKernel()
            for record in generate_long_horizon_trace(seed=seed, trades=1800):
                expected = reference.ingest(record)
                if record.kind == "lifecycle":
                    kernel.ingest_lifecycle(record.lifecycle)
                    actual = None
                else:
                    actual = kernel.ingest_trade(record.trade)
                    self.assertEqual(_snapshot(actual), _snapshot(expected), (seed, record.sequence))

            stats = kernel.stats()
            self.assertGreater(stats.late_chain_time_inserts, 0)
            self.assertGreater(stats.compactions, 0)
            self.assertLess(stats.retained_trade_rows, 1800)

    def test_invalid_trade_fails_on_ingress(self):
        kernel = IndexedMarketSignalKernel()
        with self.assertRaises(ValueError):
            kernel.ingest_trade(
                MarketTradeObservation(
                    token_mint="T",
                    side="invalid",
                    chain_time=10,
                    observed_at=10,
                    venue="pumpswap",
                )
            )

    def test_same_asset_observed_at_regression_fails_closed(self):
        kernel = IndexedMarketSignalKernel()
        kernel.ingest_trade(
            MarketTradeObservation(
                token_mint="T",
                side="buy",
                chain_time=100,
                observed_at=101,
                wallet_address="W1",
                venue="pumpswap",
                transaction_key="TX1",
            )
        )
        with self.assertRaisesRegex(ValueError, "observed_at regression"):
            kernel.ingest_trade(
                MarketTradeObservation(
                    token_mint="T",
                    side="buy",
                    chain_time=99,
                    observed_at=100,
                    wallet_address="W2",
                    venue="pumpswap",
                    transaction_key="TX2",
                )
            )


if __name__ == "__main__":
    unittest.main()
