from __future__ import annotations

import unittest

from benchmarks.market_first_entry_availability_diagnostic_v0.run import (
    _cohort,
    _status_family,
)


class MarketFirstEntryAvailabilityDiagnosticV0Tests(unittest.TestCase):
    def test_status_family_separates_provider_rpc_and_processing_failures(self):
        self.assertEqual(_status_family("AVAILABLE_ASSEMBLED"), "AVAILABLE_ASSEMBLED")
        self.assertEqual(
            _status_family("ENTRY_WINDOW_MISSED_BY_PROCESSING"),
            "ENTRY_WINDOW_MISSED_BY_PROCESSING",
        )
        self.assertEqual(
            _status_family("ERROR:SolanaRPCError:getTokenSupply did not return token decimals"),
            "SOLANA_RPC_ERROR_BEFORE_PROVIDER_ROUTE",
        )
        self.assertEqual(
            _status_family("ERROR:JupiterOrderError:no route found"),
            "JUPITER_NO_ROUTE_OR_NOT_TRADABLE",
        )
        self.assertEqual(
            _status_family("ERROR:JupiterOrderError:429 too many requests"),
            "JUPITER_RATE_LIMIT",
        )
        self.assertEqual(
            _status_family("ERROR:JupiterOrderError:request timed out"),
            "JUPITER_TIMEOUT",
        )

    def test_cohort_cross_tabs_route_and_collection_status(self):
        rows = [
            {
                "entry_group": "ENTRY_UNAVAILABLE",
                "collection_status_family": "JUPITER_NO_ROUTE_OR_NOT_TRADABLE",
                "provider_calls_started": True,
                "provider_start_delay_after_cutoff_ms": 2000.0,
                "provider_start_delay_after_ready_ms": 10.0,
            },
            {
                "entry_group": "ENTRY_USABLE",
                "collection_status_family": "AVAILABLE_ASSEMBLED",
                "provider_calls_started": True,
                "provider_start_delay_after_cutoff_ms": 2000.0,
                "provider_start_delay_after_ready_ms": 20.0,
            },
        ]
        report = _cohort(rows)
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["route_entry_group_counts"]["ENTRY_UNAVAILABLE"], 1)
        self.assertEqual(
            report["collection_status_by_route_entry_group"]["ENTRY_UNAVAILABLE"][
                "JUPITER_NO_ROUTE_OR_NOT_TRADABLE"
            ],
            1,
        )
        self.assertEqual(report["provider_calls_started_true"], 2)
        self.assertEqual(report["provider_start_delay_after_ready_ms"]["median"], 15.0)


if __name__ == "__main__":
    unittest.main()
