import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_handoff_v0 import build_market_activity_discovery_handoff_v0
from src.market_activity_discovery_research_processor_v0 import (
    process_market_activity_discovery_handoff_v0,
)
from src.market_activity_discovery_run_v0 import create_market_activity_discovery_run_v0
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import MarketTradeObservation


class MarketActivityDiscoveryResearchProcessorV0Tests(unittest.TestCase):
    def _episode(self, *, observed_at=1000, chain_time=1100, trigger_key="TRIGGER1"):
        return assign_market_opportunity_trigger(
            acquisition_run_key="RUN1",
            trigger_key=trigger_key,
            token_mint="MINT_A",
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=chain_time,
            observed_at=observed_at,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def _trade(self, *, event_key, chain_time, observed_at, side="buy"):
        record_market_trade(
            acquisition_run_key="RUN1",
            event_key=event_key,
            source_provider="test_source",
            observation=MarketTradeObservation(
                token_mint="MINT_A",
                side=side,
                chain_time=chain_time,
                observed_at=observed_at,
                wallet_address=f"wallet-{event_key}",
                notional_usd=25.0,
                price_usd=1.0,
                venue="pump",
                transaction_key=f"tx-{event_key}",
            ),
        )

    def test_first_trigger_handoff_builds_run_scoped_t0_and_registers_analyzable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processor.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=900
                )
                episode = self._episode()
                self._trade(event_key="e1", chain_time=1090, observed_at=990)
                self._trade(event_key="e2", chain_time=1100, observed_at=1000, side="sell")
                handoff = build_market_activity_discovery_handoff_v0(
                    episode=episode,
                    trigger_key=episode.first_trigger_key,
                )
                result = process_market_activity_discovery_handoff_v0(handoff)

        self.assertEqual(result.provider_calls_performed, 0)
        self.assertEqual(result.t0_build.flow_event_keys, ("e1", "e2"))
        self.assertEqual(result.t0_build.decision_as_of, 1000)
        self.assertEqual(result.t0_build.chain_as_of, 1100)
        self.assertEqual(result.admission.cohort_member.disposition, "ANALYZABLE_T0")
        self.assertEqual(result.admission.cohort_member.first_considered_at, 1000)
        self.assertEqual(
            [item.target_at for item in result.admission.preparation.forward_outcomes],
            [1300, 1900, 4600],
        )

    def test_exact_handoff_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=900
                )
                episode = self._episode()
                handoff = build_market_activity_discovery_handoff_v0(
                    episode=episode,
                    trigger_key=episode.first_trigger_key,
                )
                first = process_market_activity_discovery_handoff_v0(handoff)
                second = process_market_activity_discovery_handoff_v0(handoff)

        self.assertEqual(first.t0_build, second.t0_build)
        self.assertEqual(first.admission.cohort_member, second.admission.cohort_member)
        self.assertEqual(
            first.admission.preparation.snapshot_record,
            second.admission.preparation.snapshot_record,
        )

    def test_tampered_handoff_fails_before_t0_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=900
                )
                episode = self._episode()
                handoff = build_market_activity_discovery_handoff_v0(
                    episode=episode,
                    trigger_key=episode.first_trigger_key,
                )
                tampered = replace(handoff, token_mint="OTHER")
                with patch(
                    "src.market_activity_discovery_research_processor_v0.build_market_activity_discovery_t0_v0"
                ) as builder:
                    with self.assertRaises(ValueError):
                        process_market_activity_discovery_handoff_v0(tampered)
                    builder.assert_not_called()

    def test_trigger_at_half_open_close_is_rejected_before_t0_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=900
                )
                episode = self._episode(
                    observed_at=run.admission_closes_at,
                    chain_time=99999,
                    trigger_key="LATE",
                )
                handoff = build_market_activity_discovery_handoff_v0(
                    episode=episode,
                    trigger_key=episode.first_trigger_key,
                )
                with patch(
                    "src.market_activity_discovery_research_processor_v0.build_market_activity_discovery_t0_v0"
                ) as builder:
                    with self.assertRaises(ValueError):
                        process_market_activity_discovery_handoff_v0(handoff)
                    builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
