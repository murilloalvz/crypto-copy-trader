from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import database
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_onchain_hazard import (
    SolanaRPCMintHazardProbe,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
)
from src.solana import SolanaRPCError


TOKEN = "TokenMint111111111111111111111111111111111"


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-onchain-hazard-1",
        acquisition_run_key="run-onchain-hazard-1",
        token_mint=TOKEN,
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=99,
        first_trigger_observed_at=100,
        episode_closes_at=160,
        decision_as_of=None,
    )


def _rpc_result(*, owner=TOKEN_PROGRAM, mint_authority=None, freeze_authority=None, extensions=None, supply="1000000000"):
    info = {
        "decimals": 6,
        "supply": supply,
        "mintAuthority": mint_authority,
        "freezeAuthority": freeze_authority,
    }
    if extensions is not None:
        info["extensions"] = extensions
    return {
        "context": {"slot": 12345},
        "value": {
            "owner": owner,
            "data": {"parsed": {"type": "mint", "info": info}, "program": "spl-token"},
        },
    }


def _largest_result(amounts, *, slot=12346):
    return {
        "context": {"slot": slot},
        "value": [
            {
                "address": f"TokenAccount{index}",
                "amount": str(amount),
                "decimals": 6,
                "uiAmount": amount / 1_000_000,
                "uiAmountString": str(amount / 1_000_000),
            }
            for index, amount in enumerate(amounts, start=1)
        ],
    }


class OpportunityOnchainHazardTests(unittest.TestCase):
    def test_classic_mint_authorities_and_token_account_concentration_are_persisted_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.side_effect = [
                    _rpc_result(
                        mint_authority="MintAuthority11111111111111111111111111111",
                        freeze_authority=None,
                    ),
                    _largest_result([300_000_000, 200_000_000, 100_000_000, 50_000_000, 40_000_000, 30_000_000, 20_000_000, 10_000_000, 5_000_000, 5_000_000, 1_000_000]),
                ]
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    probe = SolanaRPCMintHazardProbe()
                    first = probe.capture(_episode())
                    second = probe.capture(_episode())

        self.assertEqual(first.attempt.status, "AVAILABLE")
        self.assertFalse(first.reused_attempt)
        self.assertTrue(second.reused_attempt)
        self.assertEqual(client.call.call_count, 2)
        self.assertEqual(first.evidence.context_slot, 12345)
        self.assertEqual(first.evidence.largest_accounts_context_slot, 12346)
        self.assertEqual(first.evidence.observed_at, 110)
        self.assertTrue(first.evidence.mint_authority_present)
        self.assertFalse(first.evidence.freeze_authority_present)
        self.assertFalse(first.evidence.token_2022)
        self.assertAlmostEqual(first.evidence.top10_token_account_concentration_pct, 76.0)
        self.assertEqual(first.evidence.largest_token_accounts_observed, 11)
        self.assertEqual(first.evidence.largest_accounts_sum_raw, "760000000")
        self.assertIn(
            "top10_token_account_concentration_is_not_holder_concentration",
            first.evidence.data_quality_flags,
        )
        self.assertIn(
            "largest_accounts_are_token_accounts_not_unique_owners",
            first.evidence.data_quality_flags,
        )

    def test_token_2022_extensions_are_preserved_without_inventing_risk_score(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.side_effect = [
                    _rpc_result(
                        owner=TOKEN_2022_PROGRAM,
                        extensions=[{"extension": "permanentDelegate"}, {"extension": "transferFeeConfig"}],
                    ),
                    _largest_result([500_000_000, 200_000_000]),
                ]
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "AVAILABLE")
        self.assertTrue(result.evidence.token_2022)
        self.assertEqual(
            result.evidence.extensions_present,
            ("permanentDelegate", "transferFeeConfig"),
        )
        self.assertAlmostEqual(result.evidence.top10_token_account_concentration_pct, 70.0)
        self.assertFalse(hasattr(result.evidence, "risk_score"))

    def test_largest_accounts_rpc_failure_keeps_core_authority_evidence_available_and_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.side_effect = [
                    _rpc_result(mint_authority=None, freeze_authority=None),
                    SolanaRPCError("largest accounts unavailable"),
                ]
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "AVAILABLE")
        self.assertFalse(result.evidence.mint_authority_present)
        self.assertFalse(result.evidence.freeze_authority_present)
        self.assertIsNone(result.evidence.top10_token_account_concentration_pct)
        self.assertEqual(result.evidence.largest_accounts_error_type, "SolanaRPCError")
        self.assertIn("largest_accounts_rpc_unavailable", result.evidence.data_quality_flags)

    def test_cross_slot_concentration_over_100_is_not_reported_as_valid_metric(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.side_effect = [
                    _rpc_result(supply="100"),
                    _largest_result([80, 40]),
                ]
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "AVAILABLE")
        self.assertIsNone(result.evidence.top10_token_account_concentration_pct)
        self.assertEqual(result.evidence.largest_accounts_sum_raw, "120")
        self.assertIn(
            "top10_token_account_concentration_unavailable_cross_slot_supply_mismatch",
            result.evidence.data_quality_flags,
        )

    def test_missing_mint_account_is_explicit_unavailable_without_auxiliary_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.return_value = {"context": {"slot": 12345}, "value": None}
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "UNAVAILABLE")
        self.assertIn("mint_account_missing", result.evidence.data_quality_flags)
        self.assertEqual(client.call.call_count, 1)

    def test_rpc_failure_on_core_mint_is_terminal_provider_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.side_effect = SolanaRPCError("rpc unavailable")
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "PROVIDER_ERROR")
        self.assertEqual(result.attempt.error_type, "SolanaRPCError")

    def test_non_mint_json_is_normalization_error(self):
        bad = {
            "context": {"slot": 12345},
            "value": {
                "owner": TOKEN_PROGRAM,
                "data": {"parsed": {"type": "account", "info": {}}},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.return_value = bad
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "NORMALIZATION_ERROR")
        self.assertIn("jsonParsed mint state", result.attempt.error_message)

    def test_unsupported_owner_program_is_not_silently_treated_as_valid_spl_mint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hazard.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                client = Mock()
                client.call.return_value = _rpc_result(owner="UnknownProgram111111111111111111111111111")
                with patch("src.opportunity_onchain_hazard.SolanaClient", return_value=client), patch(
                    "src.opportunity_onchain_hazard.time.time", return_value=110
                ):
                    result = SolanaRPCMintHazardProbe().capture(_episode())

        self.assertEqual(result.attempt.status, "NORMALIZATION_ERROR")
        self.assertIn("supported SPL Token program", result.attempt.error_message)


if __name__ == "__main__":
    unittest.main()
