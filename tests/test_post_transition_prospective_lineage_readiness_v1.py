from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.post_transition_reacceleration_v0.prospective_lineage_readiness_v1 import (
    _lineage_clock_gate,
    _persist_pump_births,
    _subscription_source,
)
from src import database
from src.market_observation_store import inspect_known_market_lifecycle
from src.pump_bonding_stream import PumpCreateEvent, PumpLogNotification


class PostTransitionProspectiveLineageReadinessV1Tests(unittest.TestCase):
    def test_subscription_source_routes_by_server_subscription_id(self):
        pump = {
            "method": "logsNotification",
            "params": {"subscription": 101},
        }
        pumpswap = {
            "method": "logsNotification",
            "params": {"subscription": 202},
        }
        other = {
            "method": "logsNotification",
            "params": {"subscription": 303},
        }

        self.assertEqual(
            _subscription_source(
                pump,
                pump_subscription_id=101,
                pumpswap_subscription_id=202,
            ),
            "pump",
        )
        self.assertEqual(
            _subscription_source(
                pumpswap,
                pump_subscription_id=101,
                pumpswap_subscription_id=202,
            ),
            "pumpswap",
        )
        self.assertIsNone(
            _subscription_source(
                other,
                pump_subscription_id=101,
                pumpswap_subscription_id=202,
            )
        )

    def test_pump_birth_is_persisted_with_true_local_availability(self):
        notification = PumpLogNotification(
            signature="sig",
            slot=1,
            observed_at=105,
            events=(),
            lifecycle_events=(
                PumpCreateEvent(
                    mint="TOKEN",
                    bonding_curve="CURVE",
                    user="USER",
                    creator="CREATOR",
                    timestamp=100,
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "market.db"
            with patch.object(
                database,
                "settings",
                SimpleNamespace(database_path=db),
            ):
                seen, inserted = _persist_pump_births(
                    notification,
                    acquisition_run_key="lineage-run",
                )
                before = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=104,
                    venue="pump_bonding_curve",
                )
                at_birth = inspect_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=105,
                    venue="pump_bonding_curve",
                )
                replay_seen, replay_inserted = _persist_pump_births(
                    notification,
                    acquisition_run_key="lineage-run",
                )

        self.assertEqual((seen, inserted), (1, 1))
        self.assertEqual(before.status, "MISSING")
        self.assertEqual(at_birth.status, "FOUND")
        self.assertIsNotNone(at_birth.lifecycle)
        self.assertEqual((replay_seen, replay_inserted), (1, 0))

    def test_lineage_clock_gate_requires_strictly_prior_local_availability(self):
        self.assertEqual(
            _lineage_clock_gate(
                birth_chain_time=100,
                birth_observed_at=105,
                transition_chain_time=200,
                transition_observed_at=210,
            ),
            "PASS",
        )
        self.assertEqual(
            _lineage_clock_gate(
                birth_chain_time=201,
                birth_observed_at=105,
                transition_chain_time=200,
                transition_observed_at=210,
            ),
            "CHRONOLOGY_INVALID",
        )
        self.assertEqual(
            _lineage_clock_gate(
                birth_chain_time=100,
                birth_observed_at=211,
                transition_chain_time=200,
                transition_observed_at=210,
            ),
            "AVAILABILITY_INVALID",
        )
        self.assertEqual(
            _lineage_clock_gate(
                birth_chain_time=100,
                birth_observed_at=210,
                transition_chain_time=200,
                transition_observed_at=210,
            ),
            "SAME_SECOND_UNRESOLVED",
        )


if __name__ == "__main__":
    unittest.main()
