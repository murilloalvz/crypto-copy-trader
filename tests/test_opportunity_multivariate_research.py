import unittest

from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_multivariate_research import (
    INTERACTION_FAMILY_SPECS,
    build_outcome_blind_opportunity_vector,
)
from src.participant_distribution_research import build_participant_distribution_window
from src.temporal_flow_structure_research import build_temporal_flow_structure_window


def _trade(*, wallet: str, chain_time: int, side: str = "buy") -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint="TOKEN",
        side=side,
        chain_time=chain_time,
        observed_at=chain_time,
        wallet_address=wallet,
        transaction_key=f"{wallet}-{side}-{chain_time}",
    )


def _components():
    observations = [
        _trade(wallet="A", chain_time=50),
        _trade(wallet="B", chain_time=65),
        _trade(wallet="C", chain_time=80),
        _trade(wallet="D", chain_time=95),
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
    return participant, temporal


class OpportunityMultivariateResearchTests(unittest.TestCase):
    def test_vector_joins_complementary_components_without_score(self):
        participant, temporal = _components()
        vector = build_outcome_blind_opportunity_vector(
            episode_key="episode-1",
            token_mint="TOKEN",
            episode_t0=100,
            research_decision_as_of=110,
            base_features={
                "flow60_event_count": 4,
                "flow60_buy_share_pct": 100.0,
            },
            base_feature_observed_at={
                "flow60_event_count": 105,
                "flow60_buy_share_pct": 105,
            },
            participant=participant,
            temporal=temporal,
        )
        features = vector.feature_dict()
        self.assertEqual(features["flow60_event_count"], 4)
        self.assertEqual(features["participant60_buyer_breadth_ratio"], 1.0)
        self.assertEqual(features["participant60_top1_buyer_event_share_pct"], 25.0)
        self.assertEqual(features["temporal60_active_subwindow_share_pct"], 100.0)
        self.assertEqual(features["temporal60_event_hhi"], 0.25)
        self.assertFalse(any("score" in name for name in features))
        self.assertIn("component_vector_is_not_an_entry_score", vector.science_cautions)

    def test_interaction_families_are_questions_not_weights(self):
        keys = {spec.key for spec in INTERACTION_FAMILY_SPECS}
        self.assertIn("intensity_x_participant_distribution", keys)
        self.assertIn("direction_x_participant_distribution", keys)
        self.assertIn("intensity_x_temporal_structure", keys)
        self.assertIn("participant_distribution_x_temporal_structure", keys)
        self.assertTrue(all(spec.research_question for spec in INTERACTION_FAMILY_SPECS))

    def test_failed_univariate_feature_can_be_carried_without_being_rescored(self):
        participant, temporal = _components()
        vector = build_outcome_blind_opportunity_vector(
            episode_key="episode-1",
            token_mint="TOKEN",
            episode_t0=100,
            research_decision_as_of=110,
            base_features={"flow60_event_count": 4},
            base_feature_observed_at={"flow60_event_count": 105},
            participant=participant,
            temporal=temporal,
        )
        self.assertEqual(vector.feature_dict()["flow60_event_count"], 4)
        self.assertIn(
            "failed_univariate_rule_may_reenter_only_as_a_new_interaction_hypothesis",
            vector.science_cautions,
        )

    def test_base_feature_observed_after_decision_is_rejected(self):
        participant, temporal = _components()
        with self.assertRaisesRegex(ValueError, "observed after research decision"):
            build_outcome_blind_opportunity_vector(
                episode_key="episode-1",
                token_mint="TOKEN",
                episode_t0=100,
                research_decision_as_of=110,
                base_features={"flow60_event_count": 4},
                base_feature_observed_at={"flow60_event_count": 111},
                participant=participant,
                temporal=temporal,
            )

    def test_component_anchor_must_match_episode_t0(self):
        participant, _temporal = _components()
        observations = [_trade(wallet="A", chain_time=90)]
        mismatched_temporal = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=99,
            knowledge_as_of=105,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=observations,
        )
        with self.assertRaisesRegex(ValueError, "temporal market anchor"):
            build_outcome_blind_opportunity_vector(
                episode_key="episode-1",
                token_mint="TOKEN",
                episode_t0=100,
                research_decision_as_of=110,
                base_features={},
                base_feature_observed_at={},
                participant=participant,
                temporal=mismatched_temporal,
            )

    def test_missing_component_metric_stays_missing(self):
        observations = [
            MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=95,
                observed_at=95,
                wallet_address=None,
                transaction_key="missing-wallet",
            )
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
        vector = build_outcome_blind_opportunity_vector(
            episode_key="episode-1",
            token_mint="TOKEN",
            episode_t0=100,
            research_decision_as_of=110,
            base_features={},
            base_feature_observed_at={},
            participant=participant,
            temporal=temporal,
        )
        self.assertIsNone(vector.feature_dict()["participant60_buyer_breadth_ratio"])
        self.assertTrue(any(flag.startswith("participant:") for flag in vector.data_quality_flags))


if __name__ == "__main__":
    unittest.main()
