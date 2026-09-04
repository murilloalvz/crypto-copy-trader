import unittest
from types import SimpleNamespace

from src.market_opportunity_episode_store import MarketOpportunityEpisode
from unified_market_latency_smoke_v27 import (
    _EpisodeContinuationCache,
    _prepared_requires_stateful_episode,
)


class UnifiedMarketLatencyV27Tests(unittest.TestCase):
    def _episode(self, *, first=100, closes=160):
        return MarketOpportunityEpisode(
            episode_key="episode-1",
            acquisition_run_key="run-a",
            token_mint="T",
            first_trigger_key="t1",
            first_trigger_kind="activity_acceleration",
            first_trigger_direction="upward_pressure",
            first_trigger_chain_time=99,
            first_trigger_observed_at=first,
            episode_closes_at=closes,
            decision_as_of=None,
        )

    def test_trigger_inside_cached_episode_is_continuation_only(self):
        cache = _EpisodeContinuationCache()
        cache.remember(self._episode())
        prepared = SimpleNamespace(
            observed_at=120,
            tokens=(SimpleNamespace(token_mint="T", trigger=object()),),
        )
        self.assertFalse(_prepared_requires_stateful_episode(prepared, cache))

    def test_trigger_exactly_at_episode_close_requires_stateful_assignment(self):
        cache = _EpisodeContinuationCache()
        cache.remember(self._episode())
        prepared = SimpleNamespace(
            observed_at=160,
            tokens=(SimpleNamespace(token_mint="T", trigger=object()),),
        )
        self.assertTrue(_prepared_requires_stateful_episode(prepared, cache))

    def test_older_trigger_before_cached_episode_remains_stateful(self):
        cache = _EpisodeContinuationCache()
        cache.remember(self._episode(first=120, closes=180))
        prepared = SimpleNamespace(
            observed_at=110,
            tokens=(SimpleNamespace(token_mint="T", trigger=object()),),
        )
        self.assertTrue(_prepared_requires_stateful_episode(prepared, cache))

    def test_pumpswap_token_as_of_controls_continuation_window(self):
        cache = _EpisodeContinuationCache()
        cache.remember(self._episode())
        prepared = SimpleNamespace(
            observed_at=999,
            tokens=(
                SimpleNamespace(
                    token_mint="T",
                    token_as_of=130,
                    trigger=object(),
                ),
            ),
        )
        self.assertFalse(_prepared_requires_stateful_episode(prepared, cache))

    def test_unseen_trigger_token_requires_stateful_assignment(self):
        cache = _EpisodeContinuationCache()
        cache.remember(self._episode())
        prepared = SimpleNamespace(
            observed_at=120,
            tokens=(SimpleNamespace(token_mint="OTHER", trigger=object()),),
        )
        self.assertTrue(_prepared_requires_stateful_episode(prepared, cache))

    def test_no_trigger_tokens_need_no_stateful_assignment(self):
        cache = _EpisodeContinuationCache()
        prepared = SimpleNamespace(
            observed_at=120,
            tokens=(SimpleNamespace(token_mint="T", trigger=None),),
        )
        self.assertFalse(_prepared_requires_stateful_episode(prepared, cache))


if __name__ == "__main__":
    unittest.main()
