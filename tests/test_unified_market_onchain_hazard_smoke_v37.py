from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.market_opportunity_episode_store import MarketOpportunityEpisode
import unified_market_onchain_hazard_smoke_v37 as v37


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode-1",
        acquisition_run_key="run-1",
        token_mint="TokenMint111111111111111111111111111111111",
        first_trigger_key="trigger-1",
        first_trigger_kind="established_acceleration",
        first_trigger_direction="buy_pressure",
        first_trigger_chain_time=99,
        first_trigger_observed_at=100,
        episode_closes_at=160,
        decision_as_of=None,
    )


def _evidence(*, concentration=42.0, flags=None, largest_error=None):
    return SimpleNamespace(
        observed_at=110,
        status="AVAILABLE",
        mint_authority_present=False,
        freeze_authority_present=False,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        decimals=6,
        supply_raw="1000000",
        token_2022=False,
        top10_token_account_concentration_pct=concentration,
        largest_accounts_error_type=largest_error,
        data_quality_flags=tuple(
            flags
            if flags is not None
            else (
                "largest_accounts_are_token_accounts_not_unique_owners",
                "top10_token_account_concentration_is_not_holder_concentration",
            )
        ),
    )


class UnifiedMarketOnchainHazardSmokeV37Tests(unittest.TestCase):
    def _run(self, evidence):
        original_admit = v37.v19.admit_opportunity_episode
        original_resolver = v37.v19.BoundedConcurrentResolver
        original_scheduler = v37.v19.ReadyAssetScheduler
        original_cache = v37.v27._EpisodeContinuationCache

        admitted = Mock(return_value=True)
        probe = Mock()
        probe.capture.return_value = SimpleNamespace(
            attempt=SimpleNamespace(status="AVAILABLE"),
            reused_attempt=False,
            evidence=evidence,
        )

        async def fake_v30(**kwargs):
            v37.v19.admit_opportunity_episode(
                acquisition_run_key="run-1",
                episode_key="episode-1",
                admitted_at=100,
            )

        output = io.StringIO()
        with patch.object(v37.v19, "admit_opportunity_episode", admitted), patch.object(
            v37, "get_market_opportunity_episode", return_value=_episode()
        ), patch.object(
            v37, "SolanaRPCMintHazardProbe", return_value=probe
        ), patch.object(
            v37.v30, "run_smoke_v30", side_effect=fake_v30
        ), redirect_stdout(output):
            asyncio.run(
                v37.run_smoke_v37(
                    max_hazard_episodes=1,
                    hazard_workers=1,
                    hazard_rpc_timeout_seconds=1,
                    hydration_batch_size=1,
                    hydration_batch_max_wait_ms=0,
                    hedge_endpoints=1,
                    default_io_workers=32,
                    run_key="run-1",
                    duration_seconds=1,
                    commitment="confirmed",
                    max_hydrations=1,
                    rpc_timeout_seconds=1,
                    pump_batch_size=1,
                    pump_batch_max_wait_ms=0,
                    pump_prepare_workers=12,
                    pumpswap_workers=256,
                    pumpswap_prepare_submitters=64,
                    pumpswap_prepare_executor_workers=32,
                    pumpswap_writer_batch_size=1,
                    pumpswap_writer_batch_max_wait_ms=0,
                    max_concurrent_resolutions=1,
                    queue_size=10,
                    continuation_batch_size=1,
                    continuation_batch_max_wait_ms=0,
                )
            )

        self.assertEqual(probe.capture.call_count, 1)
        self.assertIs(v37.v19.admit_opportunity_episode, original_admit)
        self.assertIs(v37.v19.BoundedConcurrentResolver, original_resolver)
        self.assertIs(v37.v19.ReadyAssetScheduler, original_scheduler)
        self.assertIs(v37.v27._EpisodeContinuationCache, original_cache)
        return output.getvalue()

    def test_wrapper_passes_with_complete_core_and_explicit_token_account_semantics(self):
        text = self._run(_evidence())
        self.assertIn(
            "onchain_hazard_provider_classification=PASS_CAUSAL_ONCHAIN_HAZARD_PROVIDER",
            text,
        )
        self.assertIn("available_core_complete=1", text)
        self.assertIn("concentration_available=1", text)
        self.assertIn("concentration_semantic_violations=0", text)

    def test_auxiliary_largest_accounts_failure_does_not_fail_core_provider_gate(self):
        text = self._run(
            _evidence(
                concentration=None,
                flags=("largest_accounts_rpc_unavailable",),
                largest_error="SolanaRPCError",
            )
        )
        self.assertIn(
            "onchain_hazard_provider_classification=PASS_CAUSAL_ONCHAIN_HAZARD_PROVIDER",
            text,
        )
        self.assertIn("concentration_available=0", text)
        self.assertIn("largest_accounts_aux_errors=1", text)

    def test_concentration_without_not_holder_semantic_flag_fails_gate(self):
        text = self._run(
            _evidence(
                concentration=42.0,
                flags=("largest_accounts_are_token_accounts_not_unique_owners",),
            )
        )
        self.assertIn("concentration_semantic_violations=1", text)
        self.assertIn(
            "onchain_hazard_provider_classification=FAIL_CAUSAL_ONCHAIN_HAZARD_PROVIDER",
            text,
        )

    def test_incomplete_authority_core_fails_gate(self):
        evidence = _evidence()
        evidence.mint_authority_present = None
        text = self._run(evidence)
        self.assertIn("available_core_incomplete=1", text)
        self.assertIn(
            "onchain_hazard_provider_classification=FAIL_CAUSAL_ONCHAIN_HAZARD_PROVIDER",
            text,
        )


if __name__ == "__main__":
    unittest.main()
