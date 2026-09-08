import unittest

from src.market_observation_store import StoredMarketTrade
from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_multivariate_research import build_outcome_blind_opportunity_vector
from src.opportunity_wallet_convergence_v60 import (
    FrozenWalletCohortMemberV60,
    build_wallet_convergence_evidence_v60,
)
from src.participant_distribution_research import build_participant_distribution_window
from src.temporal_flow_structure_research import build_temporal_flow_structure_window


def _trade(wallet: str, chain_time: int, *, side: str = "buy") -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint="TOKEN",
        side=side,
        chain_time=chain_time,
        observed_at=chain_time,
        wallet_address=wallet,
        transaction_key=f"{wallet}-{side}-{chain_time}",
    )


def _stored(key: str, wallet: str, chain_time: int) -> StoredMarketTrade:
    return StoredMarketTrade(
        acquisition_run_key="run",
        event_key=key,
        source_provider="test",
        observation=_trade(wallet, chain_time),
    )


class OpportunityMultivariateWalletConvergenceTests(unittest.TestCase):
    def test_prefrozen_wallet_convergence_is_joined_as_separate_family(self):
        observations = [
            _trade("SMART", 55),
            _trade("B", 70),
            _trade("C", 85),
            _trade("D", 95),
        ]
        participant = build_participant_distribution_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=105,
            window_seconds=60,
            observations=observations,
        )
        temporal = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=105,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=observations,
        )
        wallet = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=105,
            window_seconds=60,
            cohort_key="frozen-alpha",
            members=[FrozenWalletCohortMemberV60("SMART", "frozen-alpha", 80, "selective")],
            stored_trades=[
                _stored("1", "SMART", 95),
                _stored("2", "OTHER", 90),
            ],
        )

        vector = build_outcome_blind_opportunity_vector(
            episode_key="episode-1",
            token_mint="TOKEN",
            episode_t0=100,
            research_decision_as_of=110,
            base_features={"flow60_buy_share_pct": 75.0},
            base_feature_observed_at={"flow60_buy_share_pct": 105},
            participant=participant,
            temporal=temporal,
            wallet_convergence=wallet,
        )

        features = vector.feature_dict()
        self.assertEqual(features["walletconv60_cohort_buy_event_count"], 1)
        self.assertEqual(features["walletconv60_unique_cohort_wallet_count"], 1)
        self.assertEqual(
            vector.context_dict()["wallet_convergence_cohort_key"],
            "frozen-alpha",
        )
        self.assertIn(
            "participant_distribution_x_wallet_convergence",
            vector.interaction_families,
        )
        self.assertIn(
            "temporal_structure_x_wallet_convergence",
            vector.interaction_families,
        )

    def test_wallet_convergence_from_different_t0_is_rejected(self):
        observations = [_trade("A", 95)]
        participant = build_participant_distribution_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=105,
            window_seconds=60,
            observations=observations,
        )
        temporal = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=105,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=observations,
        )
        wallet = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            market_anchor_time=99,
            as_of=105,
            window_seconds=60,
            cohort_key="cohort",
            members=[FrozenWalletCohortMemberV60("A", "cohort", 80, "sig")],
            stored_trades=[_stored("1", "A", 95)],
        )
        with self.assertRaisesRegex(ValueError, "wallet convergence market anchor"):
            build_outcome_blind_opportunity_vector(
                episode_key="episode-1",
                token_mint="TOKEN",
                episode_t0=100,
                research_decision_as_of=110,
                base_features={},
                base_feature_observed_at={},
                participant=participant,
                temporal=temporal,
                wallet_convergence=wallet,
            )


if __name__ == "__main__":
    unittest.main()
