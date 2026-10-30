import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_t0_builder_v0 import (
    EXECUTION_CONTEXT_POLICY,
    build_market_activity_discovery_t0_v0,
)
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import MarketTradeObservation


class MarketActivityDiscoveryT0BuilderV0Tests(unittest.TestCase):
    def _episode(self):
        return assign_market_opportunity_trigger(
            acquisition_run_key="RUN1",
            trigger_key="TRIGGER1",
            token_mint="MINT_A",
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=1100,
            observed_at=1000,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def _trade(
        self,
        *,
        run_key="RUN1",
        event_key,
        mint="MINT_A",
        chain_time,
        observed_at,
        side="buy",
        notional=10.0,
        price=1.0,
    ):
        record_market_trade(
            acquisition_run_key=run_key,
            event_key=event_key,
            source_provider="test_source",
            observation=MarketTradeObservation(
                token_mint=mint,
                side=side,
                chain_time=chain_time,
                observed_at=observed_at,
                wallet_address=f"wallet-{event_key}",
                notional_usd=notional,
                price_usd=price,
                venue="pump",
                transaction_key=f"tx-{event_key}",
            ),
        )

    def test_uses_only_same_run_rows_available_by_exact_first_trigger_t0_and_chain_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "builder.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                self._trade(event_key="eligible-old", chain_time=810, observed_at=950)
                self._trade(event_key="eligible-mid", chain_time=1000, observed_at=990, side="sell")
                self._trade(event_key="eligible-trigger", chain_time=1100, observed_at=1000)
                self._trade(event_key="late-local", chain_time=1090, observed_at=1001)
                self._trade(event_key="future-chain", chain_time=1101, observed_at=999)
                self._trade(event_key="boundary-old", chain_time=800, observed_at=900)
                self._trade(run_key="RUN2", event_key="other-run", chain_time=1095, observed_at=999)
                self._trade(event_key="other-mint", mint="MINT_B", chain_time=1095, observed_at=999)

                result = build_market_activity_discovery_t0_v0(episode)

        self.assertEqual(result.decision_as_of, 1000)
        self.assertEqual(result.chain_as_of, 1100)
        self.assertEqual(result.flow_row_count, 3)
        self.assertEqual(
            result.flow_event_keys,
            ("eligible-old", "eligible-mid", "eligible-trigger"),
        )
        self.assertEqual(result.provider_calls_performed, 0)
        self.assertEqual(result.opportunity_snapshot.as_of, 1000)
        self.assertEqual(result.opportunity_snapshot.chain_as_of, 1100)
        self.assertEqual(result.market_intelligence.as_of, 1000)
        self.assertEqual(result.activity_dynamics.as_of, 1000)
        self.assertEqual(
            tuple(item.window_seconds for item in result.opportunity_snapshot.flow_windows),
            (10, 30, 60, 300),
        )
        self.assertTrue(set(result.flow_event_keys).issubset(result.market_intelligence.provenance_keys))

    def test_chain_clock_ahead_of_local_clock_is_valid_and_never_cross_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dual-clock.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                self._trade(event_key="trade", chain_time=1099, observed_at=999)
                result = build_market_activity_discovery_t0_v0(episode)

        self.assertEqual(result.decision_as_of, 1000)
        self.assertEqual(result.chain_as_of, 1100)
        self.assertEqual(result.flow_row_count, 1)

    def test_execution_protocol_and_creation_enrichment_fail_missing_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-context.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                with patch("src.causal_quote_store.load_causal_quotes") as quote_loader:
                    result = build_market_activity_discovery_t0_v0(episode)
                    quote_loader.assert_not_called()

        self.assertEqual(result.execution_context_policy, EXECUTION_CONTEXT_POLICY)
        self.assertEqual(result.opportunity_snapshot.execution.quote_count, 0)
        self.assertEqual(result.market_intelligence.lifecycle_label, "UNKNOWN")
        self.assertFalse(result.market_intelligence.protocol.pump_activity_observed)
        self.assertFalse(result.market_intelligence.protocol.pumpswap_activity_observed)
        self.assertIn("pump_create_v2_mode_not_observed", result.pump_creation_mode.data_quality_flags)
        self.assertIn(
            "execution_context_missing_no_run_scoped_quote_source",
            result.market_intelligence.data_quality_flags,
        )
        self.assertEqual(result.provider_calls_performed, 0)


if __name__ == "__main__":
    unittest.main()
