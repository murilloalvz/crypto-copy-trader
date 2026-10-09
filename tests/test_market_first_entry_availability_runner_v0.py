from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_entry_availability_diagnostic_v0.run import run_diagnostic_v0


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class MarketFirstEntryAvailabilityRunnerV0Tests(unittest.TestCase):
    def test_runner_attributes_unavailable_to_collection_failure_family(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)
            episodes = [
                {
                    "episode_key": "e1",
                    "token_mint": "m1",
                    "feature_snapshot": {
                        "decision_cutoff_wall_ns": 1_000_000_000,
                    },
                    "collection": {
                        "provider_calls_started": True,
                        "entry_ready_at": 3,
                        "entry_provider_started_wall_ns": 3_010_000_000,
                        "entry_status": "ERROR:JupiterOrderError:no route found",
                    },
                },
                {
                    "episode_key": "e2",
                    "token_mint": "m2",
                    "feature_snapshot": {
                        "decision_cutoff_wall_ns": 1_000_000_000,
                    },
                    "collection": {
                        "provider_calls_started": True,
                        "entry_ready_at": 3,
                        "entry_provider_started_wall_ns": 3_020_000_000,
                        "entry_status": "AVAILABLE_ASSEMBLED",
                    },
                },
            ]
            _write(
                run / "route-input-v2.json",
                {
                    "feature_snapshot_frozen_before_provider_quotes": True,
                    "contract_hash_sha256": "contract",
                    "episodes": episodes,
                },
            )
            _write(
                run / "route-result-v2.json",
                {
                    "contract_hash_sha256": "contract",
                    "decisions": [
                        {"episode_key": "e1", "admitted": True, "status": "ENTRY_UNAVAILABLE"},
                        {"episode_key": "e2", "admitted": True, "status": "ROUTE_CLOSED"},
                    ],
                },
            )
            _write(
                run / "sniper-comparison-v1.json",
                {
                    "primary_selector_diagnostics": {
                        "rows": [
                            {"episode_key": "e1", "selected": True},
                            {"episode_key": "e2", "selected": True},
                        ]
                    }
                },
            )

            report = run_diagnostic_v0(run_dir=run)

        self.assertEqual(report["classification"], "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_DIAGNOSTIC_V0")
        unavailable = report["cohorts"]["baseline_entry_unavailable"]
        self.assertEqual(unavailable["count"], 1)
        self.assertEqual(
            unavailable["collection_status_family_counts"]["JUPITER_NO_ROUTE_OR_NOT_TRADABLE"],
            1,
        )
        self.assertEqual(
            report["cohorts"]["baseline"]["provider_start_delay_after_ready_ms"]["median"],
            15.0,
        )


if __name__ == "__main__":
    unittest.main()
