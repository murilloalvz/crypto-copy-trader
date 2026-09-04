import unittest
from types import SimpleNamespace
from unittest.mock import patch

import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19


class _FakeProbe:
    captured = []

    def __init__(self, config):
        self.config = config

    def capture(self, episode):
        type(self).captured.append(episode.episode_key)
        attempt = SimpleNamespace(status="AVAILABLE")
        quote = SimpleNamespace(executable=True)
        return SimpleNamespace(attempt=attempt, quote=quote, reused_attempt=False)


class UnifiedMarketExecutionQuoteSmokeV31Tests(unittest.IsolatedAsyncioTestCase):
    async def test_only_new_admissions_enter_predeclared_first_n_quote_cohort(self):
        decisions = iter([True, False, True, True])

        def fake_original_admit(**kwargs):
            return next(decisions)

        async def fake_v30_run(**kwargs):
            for index in range(4):
                v19.admit_opportunity_episode(
                    acquisition_run_key="run",
                    episode_key=f"episode-{index}",
                    admitted_at=100 + index,
                )

        def fake_episode(episode_key):
            return SimpleNamespace(
                episode_key=episode_key,
                acquisition_run_key="run",
                token_mint=f"token-{episode_key}",
                first_trigger_observed_at=100,
            )

        _FakeProbe.captured = []
        with patch.object(v19, "admit_opportunity_episode", fake_original_admit), patch.object(
            v31.v30, "run_smoke_v30", side_effect=fake_v30_run
        ), patch.object(v31, "get_market_opportunity_episode", side_effect=fake_episode), patch.object(
            v31, "JupiterEpisodeQuoteProbe", _FakeProbe
        ):
            await v31.run_smoke_v31(
                max_quote_episodes=2,
                quote_workers=1,
                jupiter_timeout_seconds=5,
                quote_notional_usd=25.0,
                quote_slippage_bps=100,
                default_io_workers=32,
                run_key="run",
                duration_seconds=1,
                commitment="confirmed",
                max_hydrations=10,
                rpc_timeout_seconds=3,
                pump_batch_size=32,
                pump_batch_max_wait_ms=25,
                pump_prepare_workers=12,
                pumpswap_workers=256,
                pumpswap_prepare_submitters=64,
                pumpswap_prepare_executor_workers=32,
                pumpswap_writer_batch_size=32,
                pumpswap_writer_batch_max_wait_ms=10,
                max_concurrent_resolutions=18,
                queue_size=5000,
                continuation_batch_size=32,
                continuation_batch_max_wait_ms=5,
            )

        # episode-1 was a replay; episode-3 was a real admission but beyond the predeclared cap.
        self.assertEqual(_FakeProbe.captured, ["episode-0", "episode-2"])
        self.assertIs(v19.admit_opportunity_episode, fake_original_admit)


if __name__ == "__main__":
    unittest.main()
