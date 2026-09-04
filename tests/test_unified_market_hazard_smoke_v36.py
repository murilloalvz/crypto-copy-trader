from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.market_opportunity_episode_store import MarketOpportunityEpisode
import unified_market_hazard_smoke_v36 as v36


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


class UnifiedMarketHazardSmokeV36Tests(unittest.TestCase):
    def test_wrapper_collects_hazard_and_restores_global_classes(self):
        original_admit = v36.v19.admit_opportunity_episode
        original_resolver = v36.v19.BoundedConcurrentResolver
        original_scheduler = v36.v19.ReadyAssetScheduler
        original_cache = v36.v27._EpisodeContinuationCache

        admitted = Mock(return_value=True)
        probe = Mock()
        probe.capture.return_value = SimpleNamespace(
            attempt=SimpleNamespace(status="AVAILABLE"),
            reused_attempt=False,
            evidence=SimpleNamespace(
                observed_at=110,
                status="AVAILABLE",
                risk_score=2.0,
                rugged=False,
                data_quality_flags=(),
            ),
        )

        async def fake_v30(**kwargs):
            v36.v19.admit_opportunity_episode(
                acquisition_run_key="run-1",
                episode_key="episode-1",
                admitted_at=100,
            )

        output = io.StringIO()
        with patch.object(v36.v19, "admit_opportunity_episode", admitted), patch.object(
            v36, "get_market_opportunity_episode", return_value=_episode()
        ), patch.object(
            v36, "SolanaTrackerTokenHazardProbe", return_value=probe
        ), patch.object(
            v36.v30, "run_smoke_v30", side_effect=fake_v30
        ), redirect_stdout(output):
            asyncio.run(
                v36.run_smoke_v36(
                    max_hazard_episodes=1,
                    hazard_workers=1,
                    hazard_timeout_seconds=1,
                    hazard_max_attempts=1,
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

        text = output.getvalue()
        self.assertIn("hazard_provider_classification=PASS_CAUSAL_HAZARD_PROVIDER", text)
        self.assertEqual(probe.capture.call_count, 1)
        self.assertIs(v36.v19.admit_opportunity_episode, admitted)
        self.assertIs(v36.v19.BoundedConcurrentResolver, original_resolver)
        self.assertIs(v36.v19.ReadyAssetScheduler, original_scheduler)
        self.assertIs(v36.v27._EpisodeContinuationCache, original_cache)

        # Restore the module-level admit patched by the context for clarity after assertion.
        v36.v19.admit_opportunity_episode = original_admit


if __name__ == "__main__":
    unittest.main()
