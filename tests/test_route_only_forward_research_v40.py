from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes
from src.jupiter_research_entry_route import (
    JupiterResearchEntryRouteConfig,
    JupiterResearchEntryRouteProbe,
)
from src.jupiter_research_exit_route import (
    JupiterResearchExitRouteConfig,
    JupiterResearchExitRouteProbe,
)
from src.jupiter_swap_v2 import JupiterOrder
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_onchain_hazard import ONCHAIN_HAZARD_PROVIDER, ONCHAIN_HAZARD_PURPOSE
from src.opportunity_provider_attempt_store import (
    begin_provider_attempt,
    complete_provider_attempt,
)
from src.opportunity_route_research_store import (
    complete_route_research_outcome,
    freeze_route_research_decision,
    load_due_route_research_outcomes,
    load_route_research_outcomes,
)


TOKEN = "TokenMint111111111111111111111111111111111"
RUN = "route-research-run"
EPISODE = "route-research-episode"


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key=EPISODE,
        acquisition_run_key=RUN,
        token_mint=TOKEN,
        first_trigger_key="trigger",
        first_trigger_kind="activity_acceleration",
        first_trigger_direction="upward_pressure",
        first_trigger_chain_time=990,
        first_trigger_observed_at=991,
        episode_closes_at=1051,
        decision_as_of=None,
    )


def _seed_hazard():
    attempt_key = f"provider:{ONCHAIN_HAZARD_PROVIDER}:{ONCHAIN_HAZARD_PURPOSE}:{RUN}:{EPISODE}"
    begin_provider_attempt(
        attempt_key=attempt_key,
        acquisition_run_key=RUN,
        episode_key=EPISODE,
        provider=ONCHAIN_HAZARD_PROVIDER,
        purpose=ONCHAIN_HAZARD_PURPOSE,
        started_at=995,
    )
    return complete_provider_attempt(
        attempt_key=attempt_key,
        status="AVAILABLE",
        completed_at=1000,
        details={
            "token_mint": TOKEN,
            "observed_at": 999,
            "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "decimals": 6,
            "supply_raw": "1000000000",
            "mint_authority_present": False,
            "freeze_authority_present": False,
        },
    )


def _buy_order(*, observed_at: int = 1002, transaction: str | None = None) -> JupiterOrder:
    return JupiterOrder(
        input_mint=USDC_MINT,
        output_mint=TOKEN,
        in_amount_raw="25000000",
        out_amount_raw="50000000",
        in_usd_value=25.0,
        out_usd_value=25.0,
        swap_usd_value=25.0,
        slippage_bps=100,
        price_impact_pct_points=0.1,
        router="router",
        mode=None,
        request_id="buy-request",
        quote_id="buy-quote",
        transaction=transaction,
        last_valid_block_height=None,
        expire_at=None,
        error_code=None,
        error_message=None,
        observed_at=observed_at,
    )


def _sell_order(*, observed_at: int = 1303, transaction: str | None = None) -> JupiterOrder:
    return JupiterOrder(
        input_mint=TOKEN,
        output_mint=USDC_MINT,
        in_amount_raw="50000000",
        out_amount_raw="30000000",
        in_usd_value=30.0,
        out_usd_value=30.0,
        swap_usd_value=30.0,
        slippage_bps=100,
        price_impact_pct_points=0.2,
        router="router",
        mode=None,
        request_id="sell-request",
        quote_id="sell-quote",
        transaction=transaction,
        last_valid_block_height=None,
        expire_at=None,
        error_code=None,
        error_message=None,
        observed_at=observed_at,
    )


class RouteOnlyForwardResearchV40Tests(unittest.TestCase):
    def test_entry_route_freezes_separate_research_clock_and_exact_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                hazard = _seed_hazard()
                client = Mock()
                client.order.return_value = _buy_order()
                probe = JupiterResearchEntryRouteProbe(
                    JupiterResearchEntryRouteConfig(api_key="key")
                )
                with patch("src.jupiter_research_entry_route.time.time", return_value=1002), patch(
                    "src.jupiter_research_entry_route.JupiterSwapV2Client", return_value=client
                ):
                    entry = probe.capture(_episode(), hazard_attempt=hazard)
                decision = freeze_route_research_decision(
                    episode=_episode(),
                    entry_attempt=entry.attempt,
                    hazard_attempt=hazard,
                )
                outcomes = load_route_research_outcomes(acquisition_run_key=RUN)

        self.assertEqual(entry.attempt.status, "AVAILABLE")
        self.assertIsNotNone(entry.quote)
        assert entry.quote is not None
        self.assertFalse(entry.quote.executable)
        self.assertEqual(decision.research_decision_as_of, 1002)
        self.assertEqual(_episode().decision_as_of, None)
        self.assertEqual([item.target_at for item in outcomes], [1302, 1902, 4602])
        self.assertTrue(all(item.status == "PENDING" for item in outcomes))

    def test_route_research_exit_cannot_run_early_and_completes_only_research_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                hazard = _seed_hazard()
                entry_client = Mock()
                entry_client.order.return_value = _buy_order()
                entry_probe = JupiterResearchEntryRouteProbe(
                    JupiterResearchEntryRouteConfig(api_key="key")
                )
                with patch("src.jupiter_research_entry_route.time.time", return_value=1002), patch(
                    "src.jupiter_research_entry_route.JupiterSwapV2Client", return_value=entry_client
                ):
                    entry = entry_probe.capture(_episode(), hazard_attempt=hazard)
                freeze_route_research_decision(
                    episode=_episode(), entry_attempt=entry.attempt, hazard_attempt=hazard
                )
                first = load_route_research_outcomes(acquisition_run_key=RUN)[0]
                exit_probe = JupiterResearchExitRouteProbe(
                    JupiterResearchExitRouteConfig(api_key="key")
                )
                with patch("src.jupiter_research_exit_route.time.time", return_value=1301):
                    with self.assertRaises(ValueError):
                        exit_probe.capture(first)

                exit_client = Mock()
                exit_client.order.return_value = _sell_order(observed_at=1303)
                with patch("src.jupiter_research_exit_route.time.time", return_value=1303), patch(
                    "src.jupiter_research_exit_route.JupiterSwapV2Client", return_value=exit_client
                ):
                    result = exit_probe.capture(first)
                stored = load_route_research_outcomes(acquisition_run_key=RUN)[0]
                quotes = load_causal_quotes(quote_keys=(stored.quote_key or "",))

        self.assertEqual(result.attempt.status, "AVAILABLE")
        self.assertEqual(stored.status, "AVAILABLE")
        self.assertEqual(stored.observed_at, 1303)
        self.assertEqual(len(quotes), 1)
        self.assertFalse(quotes[0].executable)
        self.assertEqual(quotes[0].side, "sell")
        self.assertFalse(result.attempt.details["official_forward_outcome_completed"])
        self.assertEqual(result.attempt.details["sell_amount_raw"], "50000000")

    def test_research_outcome_rejects_executable_sell_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                hazard = _seed_hazard()
                client = Mock()
                client.order.return_value = _buy_order()
                probe = JupiterResearchEntryRouteProbe(
                    JupiterResearchEntryRouteConfig(api_key="key")
                )
                with patch("src.jupiter_research_entry_route.time.time", return_value=1002), patch(
                    "src.jupiter_research_entry_route.JupiterSwapV2Client", return_value=client
                ):
                    entry = probe.capture(_episode(), hazard_attempt=hazard)
                freeze_route_research_decision(
                    episode=_episode(), entry_attempt=entry.attempt, hazard_attempt=hazard
                )
                first = load_route_research_outcomes(acquisition_run_key=RUN)[0]
                # Reusing a BUY artifact is also semantically invalid for a forward SELL label.
                with self.assertRaises(ValueError):
                    complete_route_research_outcome(
                        outcome_key=first.outcome_key,
                        status="AVAILABLE",
                        observed_at=first.target_at,
                        quote_key=entry.attempt.artifact_key,
                    )

    def test_due_loader_keeps_future_horizons_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                hazard = _seed_hazard()
                client = Mock()
                client.order.return_value = _buy_order()
                probe = JupiterResearchEntryRouteProbe(
                    JupiterResearchEntryRouteConfig(api_key="key")
                )
                with patch("src.jupiter_research_entry_route.time.time", return_value=1002), patch(
                    "src.jupiter_research_entry_route.JupiterSwapV2Client", return_value=client
                ):
                    entry = probe.capture(_episode(), hazard_attempt=hazard)
                freeze_route_research_decision(
                    episode=_episode(), entry_attempt=entry.attempt, hazard_attempt=hazard
                )
                due = load_due_route_research_outcomes(
                    acquisition_run_key=RUN,
                    as_of=1500,
                )

        self.assertEqual([item.horizon_seconds for item in due], [300])


if __name__ == "__main__":
    unittest.main()
