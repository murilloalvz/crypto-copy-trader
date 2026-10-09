from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.assets import USDC_MINT
from src.causal_quote_store import load_causal_quotes, record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.jupiter_forward_exit_route import (
    JUPITER_FORWARD_ROUTE_PROVIDER,
    JupiterForwardExitRouteConfig,
    JupiterForwardExitRouteProbe,
    forward_route_purpose,
)
from src.jupiter_swap_v2 import JupiterOrder
from src.opportunity_forward_outcome_store import OpportunityForwardOutcome
from src.opportunity_provider_attempt_store import (
    begin_provider_attempt,
    complete_provider_attempt,
    list_provider_attempts,
)


TOKEN = "TokenMint111111111111111111111111111111111"
RUN = "run-forward-route"
EPISODE = "episode-forward-route"
ENTRY_QUOTE_KEY = "entry-quote"


def _outcome(*, target_at: int = 1300) -> OpportunityForwardOutcome:
    return OpportunityForwardOutcome(
        outcome_key="forward-outcome:v1:run:episode:300s",
        acquisition_run_key=RUN,
        episode_key=EPISODE,
        token_mint=TOKEN,
        decision_as_of=1000,
        horizon_seconds=300,
        target_at=target_at,
        status="PENDING",
        observed_at=None,
        quote_key=None,
        error_type=None,
        error_message=None,
    )


def _seed_entry_lineage() -> None:
    attempt_key = f"provider:{JUPITER_ENTRY_PROVIDER}:{JUPITER_ENTRY_PURPOSE}:{RUN}:{EPISODE}"
    begin_provider_attempt(
        attempt_key=attempt_key,
        acquisition_run_key=RUN,
        episode_key=EPISODE,
        provider=JUPITER_ENTRY_PROVIDER,
        purpose=JUPITER_ENTRY_PURPOSE,
        started_at=995,
    )
    record_causal_quote(
        CausalQuoteObservation(
            token_mint=TOKEN,
            side="buy",
            market_time=998,
            observed_at=998,
            price_usd=0.5,
            source="jupiter_swap_v2_order:test",
            executable=True,
            resolution_seconds=1,
            input_mint=USDC_MINT,
            output_mint=TOKEN,
            input_amount_raw="25000000",
            output_amount_raw="50000000",
            route_id="entry-route",
        ),
        quote_key=ENTRY_QUOTE_KEY,
    )
    complete_provider_attempt(
        attempt_key=attempt_key,
        status="AVAILABLE",
        completed_at=999,
        artifact_key=ENTRY_QUOTE_KEY,
        details={
            "assembled_transaction_present": True,
            "token_decimals": 6,
        },
    )


def _route_order(*, observed_at: int = 1302, transaction: str | None = None) -> JupiterOrder:
    return JupiterOrder(
        input_mint=TOKEN,
        output_mint=USDC_MINT,
        in_amount_raw="50000000",
        out_amount_raw="30000000",
        in_usd_value=25.0,
        out_usd_value=30.0,
        swap_usd_value=30.0,
        slippage_bps=100,
        price_impact_pct_points=0.2,
        router="test-router",
        mode=None,
        request_id="request-1",
        quote_id="quote-1",
        transaction=transaction,
        last_valid_block_height=None,
        expire_at=None,
        error_code=None,
        error_message=None,
        observed_at=observed_at,
    )


class JupiterForwardExitRouteProbeTests(unittest.TestCase):
    def test_refuses_to_probe_before_exact_target_without_persisting_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                _seed_entry_lineage()
                probe = JupiterForwardExitRouteProbe(
                    JupiterForwardExitRouteConfig(api_key="key")
                )
                with patch("src.jupiter_forward_exit_route.time.time", return_value=1299):
                    with self.assertRaises(ValueError):
                        probe.capture(_outcome())
                attempts = list_provider_attempts(
                    acquisition_run_key=RUN,
                    provider=JUPITER_FORWARD_ROUTE_PROVIDER,
                    purpose=forward_route_purpose(300),
                )
        self.assertEqual(attempts, ())

    def test_available_route_is_persisted_non_executable_and_does_not_complete_official_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                _seed_entry_lineage()
                client = Mock()
                client.order.return_value = _route_order()
                probe = JupiterForwardExitRouteProbe(
                    JupiterForwardExitRouteConfig(api_key="key")
                )
                with patch("src.jupiter_forward_exit_route.time.time", return_value=1302), patch(
                    "src.jupiter_forward_exit_route.JupiterSwapV2Client", return_value=client
                ):
                    result = probe.capture(_outcome())
                rows = load_causal_quotes(quote_keys=(result.attempt.artifact_key or "",))

        self.assertEqual(result.attempt.status, "AVAILABLE")
        self.assertFalse(result.reused_attempt)
        self.assertIsNotNone(result.quote)
        assert result.quote is not None
        self.assertFalse(result.quote.executable)
        self.assertEqual(result.quote.side, "sell")
        self.assertEqual(result.quote.input_amount_raw, "50000000")
        self.assertEqual(result.quote.price_usd, 0.6)
        self.assertEqual(len(rows), 1)
        self.assertTrue(result.attempt.details["route_only"])
        self.assertFalse(result.attempt.details["official_forward_outcome_completed"])
        self.assertFalse(result.attempt.details["taker_supplied"])
        self.assertFalse(result.attempt.details["assembled_transaction_present"])
        self.assertEqual(result.attempt.details["target_lateness_seconds"], 2)

    def test_route_only_probe_fails_closed_if_api_returns_assembled_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                _seed_entry_lineage()
                client = Mock()
                client.order.return_value = _route_order(transaction="unexpected")
                probe = JupiterForwardExitRouteProbe(
                    JupiterForwardExitRouteConfig(api_key="key")
                )
                with patch("src.jupiter_forward_exit_route.time.time", return_value=1302), patch(
                    "src.jupiter_forward_exit_route.JupiterSwapV2Client", return_value=client
                ):
                    result = probe.capture(_outcome())

        self.assertEqual(result.attempt.status, "NORMALIZATION_ERROR")
        self.assertIsNone(result.quote)
        self.assertIn("assembled transaction", result.attempt.error_message or "")


if __name__ == "__main__":
    unittest.main()
