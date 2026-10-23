from dataclasses import asdict
import unittest

from benchmarks.integrated_market_signal_plane_v1.differential import generate_long_horizon_trace
from src.market_signal_kernel import IndexedMarketSignalKernel
from src.market_signal_kernel_v3 import IndexedMarketSignalKernelV3


def _snapshot(trigger):
    return None if trigger is None else asdict(trigger)


class IndexedMarketSignalKernelV3Tests(unittest.TestCase):
    def test_v3_matches_v2_on_long_horizon_with_late_chain_inserts(self):
        for seed in (11, 68, 97):
            v2 = IndexedMarketSignalKernel()
            v3 = IndexedMarketSignalKernelV3()
            for record in generate_long_horizon_trace(seed=seed, trades=1800):
                if record.kind == "lifecycle":
                    v2.ingest_lifecycle(record.lifecycle)
                    v3.ingest_lifecycle(record.lifecycle)
                    continue
                expected = v2.ingest_trade(record.trade)
                actual = v3.ingest_trade(record.trade)
                self.assertEqual(_snapshot(actual), _snapshot(expected), (seed, record.sequence))

            self.assertEqual(v3.stats(), v2.stats())
            self.assertGreater(v3.stats().late_chain_time_inserts, 0)
            self.assertGreater(v3.stats().compactions, 0)


if __name__ == "__main__":
    unittest.main()
