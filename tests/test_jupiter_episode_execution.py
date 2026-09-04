import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.causal_quote_store import load_causal_quotes
from src.jupiter_episode_execution import (
    JupiterEpisodeQuoteConfig,
    JupiterEpisodeQuoteProbe,
)
from src.jupiter_swap_v2 import JupiterOrder, JupiterOrderError
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_provider_attempt_store import list_provider_attempts


TOKEN = "TokenMint111111111111111111111111111111111"


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-1",
        acquisition_run_key="run-1",
        token_mint=TOKEN,
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=99,
        first_trigger_observed_at=100,
        episode_closes_at=160,
        decision_as_of=None,
    )


def _config(*, api_key="key", taker="Taker1111111111111111111111111111111111"):
    return JupiterEpisodeQuoteConfig(
        api_key=api_key,
        taker_public_key=taker,
        rpc_url="https://rpc.invalid",
        rpc_fallback_urls=(),
        rpc_timeout_seconds=3,
        jupiter_timeout_seconds=5,
        notional_usd=25.0,
        slippage_bps=100,
    )


def _order(*, transaction="base64tx") -> JupiterOrder:
    return JupiterOrder(
        input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        output_mint=TOKEN,
        in_amount_raw="25000000",
        out_amount_raw="5000000000",
        in_usd_value=25.0,
        out_usd_value=24.9,
        swap_usd_value=24.95,
        slippage_bps=100,
        price_impact_pct_points=-0.05,
        router="metis",
        mode="ultra",
        request_id="request-1",
        quote_id="quote-1",
        transaction=transaction,
        last_valid_block_height="123",
        expire_at=None,
        error_code=None,
        error_message=None,
        observed_at=111,
    )


class JupiterEpisodeExecutionTests(unittest.TestCase):
    def _patch_decimals(self):
        client = Mock()
        client.call.return_value = {"value": {"decimals": 9}}
        return patch("src.jupiter_episode_execution.SolanaClient", return_value=client), client

    def test_success_persists_executable_quote_and_replay_does_not_recall_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                decimals_patch, solana = self._patch_decimals()
                jupiter = Mock()
                jupiter.order.return_value = _order(transaction="base64tx")
                with decimals_patch, patch(
                    "src.jupiter_episode_execution.JupiterSwapV2Client",
                    return_value=jupiter,
                ) as client_cls, patch(
                    "src.jupiter_episode_execution.time.time", return_value=110
                ):
                    probe = JupiterEpisodeQuoteProbe(_config())
                    first = probe.capture(_episode())
                    second = probe.capture(_episode())

                quotes = load_causal_quotes(
                    quote_keys=(JupiterEpisodeQuoteProbe.quote_key(_episode()),)
                )
                attempts = list_provider_attempts(acquisition_run_key="run-1")

        self.assertEqual(first.attempt.status, "AVAILABLE")
        self.assertTrue(first.quote.executable)
        self.assertAlmostEqual(first.quote.price_usd, 5.0)
        self.assertFalse(first.reused_attempt)
        self.assertTrue(second.reused_attempt)
        self.assertEqual(second.attempt.status, "AVAILABLE")
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(jupiter.order.call_count, 1)
        self.assertEqual(client_cls.call_count, 1)
        self.assertEqual(solana.call.call_count, 1)
        kwargs = jupiter.order.call_args.kwargs
        self.assertEqual(kwargs["amount_raw"], 25_000_000)
        self.assertEqual(kwargs["taker"], _config().taker_public_key)

    def test_quote_without_assembled_transaction_is_explicit_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                decimals_patch, _ = self._patch_decimals()
                jupiter = Mock()
                jupiter.order.return_value = _order(transaction=None)
                with decimals_patch, patch(
                    "src.jupiter_episode_execution.JupiterSwapV2Client",
                    return_value=jupiter,
                ), patch("src.jupiter_episode_execution.time.time", return_value=110):
                    result = JupiterEpisodeQuoteProbe(_config()).capture(_episode())

        self.assertEqual(result.attempt.status, "UNAVAILABLE")
        self.assertIsNotNone(result.quote)
        self.assertFalse(result.quote.executable)
        self.assertEqual(
            result.attempt.details["assembled_transaction_present"], False
        )

    def test_missing_config_is_persisted_without_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with patch("src.jupiter_episode_execution.SolanaClient") as solana_cls, patch(
                    "src.jupiter_episode_execution.JupiterSwapV2Client"
                ) as jupiter_cls, patch(
                    "src.jupiter_episode_execution.time.time", return_value=110
                ):
                    result = JupiterEpisodeQuoteProbe(
                        _config(api_key="", taker="")
                    ).capture(_episode())

        self.assertEqual(result.attempt.status, "CONFIG_MISSING")
        self.assertEqual(
            result.attempt.details["missing"],
            ["JUPITER_API_KEY", "JUPITER_TAKER_PUBLIC_KEY"],
        )
        solana_cls.assert_not_called()
        jupiter_cls.assert_not_called()

    def test_provider_failure_is_not_converted_into_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                decimals_patch, _ = self._patch_decimals()
                jupiter = Mock()
                jupiter.order.side_effect = JupiterOrderError("no route")
                with decimals_patch, patch(
                    "src.jupiter_episode_execution.JupiterSwapV2Client",
                    return_value=jupiter,
                ), patch("src.jupiter_episode_execution.time.time", return_value=110):
                    result = JupiterEpisodeQuoteProbe(_config()).capture(_episode())

        self.assertEqual(result.attempt.status, "PROVIDER_ERROR")
        self.assertIsNone(result.quote)
        self.assertEqual(result.attempt.error_type, "JupiterOrderError")

    def test_token_metadata_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                solana = Mock()
                solana.call.return_value = {"value": {}}
                with patch(
                    "src.jupiter_episode_execution.SolanaClient", return_value=solana
                ), patch(
                    "src.jupiter_episode_execution.JupiterSwapV2Client"
                ) as jupiter_cls, patch(
                    "src.jupiter_episode_execution.time.time", return_value=110
                ):
                    result = JupiterEpisodeQuoteProbe(_config()).capture(_episode())

        self.assertEqual(result.attempt.status, "METADATA_ERROR")
        self.assertIsNone(result.quote)
        jupiter_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
