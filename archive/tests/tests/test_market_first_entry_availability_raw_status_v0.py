from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_entry_availability_diagnostic_v0.raw_status import run_raw_status_v0


class MarketFirstEntryAvailabilityRawStatusV0Tests(unittest.TestCase):
    def test_raw_status_report_opens_other_bucket_without_selector_use(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = {
                "classification": "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_DIAGNOSTIC_V0",
                "source_integrity": {"route_contract_hash_sha256": "h"},
                "rows": [
                    {
                        "episode_key": "e1",
                        "baseline_admitted": True,
                        "sniper_selected": True,
                        "entry_group": "ENTRY_UNAVAILABLE",
                        "collection_entry_status": "UNAVAILABLE",
                        "collection_status_family": "OTHER_COLLECTION_STATUS",
                        "provider_calls_started": True,
                        "provider_start_delay_after_cutoff_ms": None,
                        "provider_start_delay_after_ready_ms": None,
                    },
                    {
                        "episode_key": "e2",
                        "baseline_admitted": True,
                        "sniper_selected": False,
                        "entry_group": "ENTRY_UNAVAILABLE",
                        "collection_entry_status": "ERROR:JupiterOrderError:429 too many requests",
                        "collection_status_family": "JUPITER_RATE_LIMIT",
                        "provider_calls_started": True,
                        "provider_start_delay_after_cutoff_ms": None,
                        "provider_start_delay_after_ready_ms": None,
                    },
                ],
            }
            route_input = {
                "episodes": [
                    {
                        "episode_key": "e1",
                        "collection": {
                            "entry_status": "UNAVAILABLE",
                            "provider_calls_started": True,
                            "provider_started_at": 10,
                        },
                    },
                    {
                        "episode_key": "e2",
                        "collection": {
                            "entry_status": "ERROR:JupiterOrderError:429 too many requests",
                            "provider_calls_started": True,
                        },
                    },
                ]
            }
            (root / "market-first-entry-availability-diagnostic-v0.json").write_text(
                json.dumps(source), encoding="utf-8"
            )
            (root / "route-input-v2.json").write_text(json.dumps(route_input), encoding="utf-8")
            report = run_raw_status_v0(run_dir=root)

        self.assertEqual(report["classification"], "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_RAW_STATUS_V0")
        baseline = report["cohorts"]["baseline_entry_unavailable"]
        self.assertEqual(baseline["raw_collection_entry_status_counts"]["UNAVAILABLE"], 1)
        self.assertEqual(baseline["provider_started_but_cutoff_delay_missing"], 2)
        self.assertEqual(baseline["original_collection_key_presence_counts"]["entry_status"], 2)
        self.assertEqual(baseline["original_collection_key_presence_counts"]["provider_started_at"], 1)
        self.assertTrue(report["source_integrity"]["raw_status_route_input_join_exact"])
        self.assertFalse(report["provider_collection_metadata_used_as_selector_feature"])


if __name__ == "__main__":
    unittest.main()
