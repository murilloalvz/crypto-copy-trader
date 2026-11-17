import unittest

from benchmarks.launch_burst_live_feature_analysis_v0.run import (
    _distribution,
    _summarize_shadow,
    _validate_capture,
)


class LaunchBurstLiveFeatureAnalysisV0Tests(unittest.TestCase):
    def _capture(self):
        return {
            "classification": "PASS_LAUNCH_BURST_LIVE_CAPTURE_V2",
            "version": "launch_burst_live_capture_v2_signal_only",
            "gates": {
                "operational_shadow_active": True,
                "duration_elapsed": True,
                "chunks_bounded": True,
                "all_chunks_consumed": True,
                "all_chunks_processed": True,
                "no_chunk_errors": True,
                "no_semantic_errors": True,
                "no_persistence_errors": True,
                "no_transport_errors": True,
                "no_reconnects": True,
                "no_rpc_errors": True,
                "no_write_errors": True,
                "research_plane_disabled_by_design": True,
                "causal_lifecycle_seen": True,
                "causal_trade_seen": True,
                "no_fatal_error": True,
            },
            "scientific_scope": {
                "feature_research_only": True,
                "economic_edge_evaluated": False,
                "future_outcomes_loaded": False,
                "market_first_research_plane_disabled": True,
            },
            "acquisition": {"chunk_count": 2},
            "chunk_report_count": 2,
        }

    def test_clean_capture_is_admissible(self):
        _validate_capture(self._capture())

    def test_research_plane_activity_is_rejected(self):
        capture = self._capture()
        capture["gates"]["research_plane_disabled_by_design"] = False
        with self.assertRaises(ValueError):
            _validate_capture(capture)

    def test_distribution_is_deterministic(self):
        dist = _distribution([0, 1, 2, 3, 4])
        self.assertEqual(dist["n"], 5)
        self.assertEqual(dist["p50"], 2.0)
        self.assertEqual(dist["p90"], 3.6)
        self.assertEqual(dist["mean"], 2.0)

    def test_summaries_keep_strata_and_right_censoring_separate(self):
        shadow = {
            "launches": [
                {
                    "stratum": "pump_launch",
                    "horizons": {
                        "1": {
                            "complete": True,
                            "features": {
                                "event_count": 2,
                                "buy_count": 2,
                                "sell_count": 0,
                                "buy_sell_count_imbalance": 1.0,
                                "signed_flow_over_event_reserve": 0.1,
                                "gross_turnover_over_event_reserve": 0.1,
                                "unique_wallet_count": 2,
                                "unique_transaction_count": 2,
                                "first_trade_delay_ms": 50.0,
                                "time_to_n_events_ms": {"1": 50.0, "3": None, "5": None, "10": None},
                                "reserve_delta_fraction": 0.02,
                            },
                        },
                        "5": {"complete": False, "features": None},
                    },
                },
                {
                    "stratum": "pumpswap_liquidity_launch",
                    "horizons": {
                        "1": {
                            "complete": True,
                            "features": {
                                "event_count": 0,
                                "buy_count": 0,
                                "sell_count": 0,
                                "buy_sell_count_imbalance": None,
                                "signed_flow_over_event_reserve": 0.0,
                                "gross_turnover_over_event_reserve": 0.0,
                                "unique_wallet_count": 0,
                                "unique_transaction_count": 0,
                                "first_trade_delay_ms": None,
                                "time_to_n_events_ms": {"1": None, "3": None, "5": None, "10": None},
                                "reserve_delta_fraction": None,
                            },
                        },
                        "5": {
                            "complete": True,
                            "features": {
                                "event_count": 1,
                                "buy_count": 1,
                                "sell_count": 0,
                                "buy_sell_count_imbalance": 1.0,
                                "signed_flow_over_event_reserve": 0.02,
                                "gross_turnover_over_event_reserve": 0.02,
                                "unique_wallet_count": 1,
                                "unique_transaction_count": 1,
                                "first_trade_delay_ms": 1200.0,
                                "time_to_n_events_ms": {"1": 1200.0, "3": None, "5": None, "10": None},
                                "reserve_delta_fraction": 0.01,
                            },
                        },
                    },
                },
            ]
        }
        summary = _summarize_shadow(shadow, (1, 5))
        pump_5 = summary["pump_launch"]["5"]
        swap_1 = summary["pumpswap_liquidity_launch"]["1"]
        self.assertEqual(pump_5["right_censored_count"], 1)
        self.assertEqual(swap_1["nonempty_count"], 0)
        self.assertEqual(summary["pump_launch"]["1"]["features"]["event_count"]["p50"], 2.0)


if __name__ == "__main__":
    unittest.main()
