import unittest

from src.pumpswap_hol_diagnostics_v7 import (
    PumpSwapHOLDiagnosticsV7,
    pearson_correlation,
)


class PumpSwapHOLDiagnosticsV7Tests(unittest.TestCase):
    def test_dependency_and_capacity_waits_are_separate(self):
        diagnostics = PumpSwapHOLDiagnosticsV7()
        diagnostics.record(
            blocking_assets=("HOT",),
            dependency_wait_seconds=5.0,
            ready_capacity_wait_seconds=2.0,
            writer_result_wait_seconds=1.0,
            finalizer_occupied_seconds=0.1,
            is_demoted=False,
        )
        snapshot = diagnostics.snapshot()
        self.assertEqual(snapshot.stateful_predecessor_incomplete_p95_seconds, 5.0)
        self.assertEqual(snapshot.stateful_capacity_wait_p95_seconds, 2.0)
        self.assertEqual(snapshot.dependency_wait_by_asset_p95_seconds, (("HOT", 5.0),))

    def test_hot_asset_share_and_writer_correlation_are_observable(self):
        diagnostics = PumpSwapHOLDiagnosticsV7()
        for asset, dependency, capacity, writer in (
            ("HOT-A", 10.0, 1.0, 10.0),
            ("HOT-B", 8.0, 2.0, 8.0),
            ("COLD", 1.0, 3.0, 1.0),
        ):
            diagnostics.record(
                blocking_assets=(asset,),
                dependency_wait_seconds=dependency,
                ready_capacity_wait_seconds=capacity,
                writer_result_wait_seconds=writer,
                finalizer_occupied_seconds=0.1,
                is_demoted=asset == "COLD",
            )
        snapshot = diagnostics.snapshot()
        self.assertEqual(snapshot.top_hot_asset_count, 3)
        self.assertAlmostEqual(snapshot.top_hot_dependency_wait_share_pct, 100.0)
        self.assertGreater(snapshot.writer_vs_dependency_correlation, 0.99)
        self.assertEqual(snapshot.stateful_records, 2)
        self.assertEqual(snapshot.demoted_records, 1)

    def test_constant_series_has_safe_zero_correlation(self):
        self.assertEqual(pearson_correlation((1.0, 1.0), (2.0, 2.0)), 0.0)


if __name__ == "__main__":
    unittest.main()
