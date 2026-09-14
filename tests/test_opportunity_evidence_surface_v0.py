import unittest

from src.direct_funding_link_v61 import DirectFundingLinkEvidenceV61
from src.market_intelligence_baseline import (
    MarketIntelligenceBaselineV0,
    MarketWindowMicrostructureFactsV0,
)
from src.opportunity_evidence_surface_v0 import build_opportunity_evidence_surface_v0
from src.opportunity_snapshot_core import ExecutionSurfaceFeatures
from src.token_structural_risk_v0 import (
    StructuralRiskObservationV0,
    build_token_structural_risk_facts_v0,
)


class OpportunityEvidenceSurfaceV0Tests(unittest.TestCase):
    def _market(self, *, token="MINT", as_of=100):
        window = MarketWindowMicrostructureFactsV0(
            window_seconds=10,
            event_count=4,
            event_rate_per_second=0.4,
            buy_count=3,
            sell_count=1,
            buy_event_share_pct=75.0,
            event_imbalance_pct=50.0,
            unique_buy_wallet_count=2,
            unique_sell_wallet_count=1,
            wallet_identity_coverage_pct=50.0,
            repeated_wallet_event_share_pct=None,
            notional_coverage_pct=100.0,
            signed_notional_usd=20.0,
            notional_imbalance_pct=25.0,
            price_coverage_pct=0.0,
            return_pct=None,
            median_observation_lag_seconds=None,
            max_observation_lag_seconds=None,
            data_quality_flags=("partial_wallet_identity_coverage",),
        )
        execution = ExecutionSurfaceFeatures(
            quote_count=2,
            buy_quote_count=1,
            sell_quote_count=1,
            executable_quote_count=0,
            latest_quote_observed_at=99,
            latest_buy_price_usd=1.0,
            latest_sell_price_usd=0.9,
            latest_buy_liquidity_usd=None,
            latest_sell_liquidity_usd=None,
            latest_buy_price_impact_pct_points=1.0,
            latest_sell_price_impact_pct_points=1.0,
            latest_buy_router="router",
            latest_sell_router="router",
            latest_buy_observation_age_seconds=1,
            latest_sell_observation_age_seconds=1,
            latest_buy_market_age_seconds=1,
            latest_sell_market_age_seconds=1,
            quote_notional_min_usd=25.0,
            quote_notional_max_usd=25.0,
            data_quality_flags=("proxy_quotes_only",),
        )
        return MarketIntelligenceBaselineV0(
            method_version="fixture",
            token_mint=token,
            as_of=as_of,
            chain_as_of=95,
            lifecycle_label="PUMP_BONDING_ACTIVE",
            protocol=None,
            windows=(window,),
            execution=execution,
            matched_unit_flow=None,
            liquidity_normalized_flow_available=False,
            provenance_keys=("market:e1",),
            data_quality_flags=("market_flag",),
        )

    def _risk(self, *, token="MINT", as_of=100, conflict=False):
        rows = [
            StructuralRiskObservationV0(
                token_mint=token,
                observed_at=90,
                evidence_key="risk:a",
                source="a",
                holder_count=100,
                top10_holder_pct=30.0,
                freeze_authority_active=False,
            )
        ]
        if conflict:
            rows.append(
                StructuralRiskObservationV0(
                    token_mint=token,
                    observed_at=91,
                    evidence_key="risk:b",
                    source="b",
                    holder_count=101,
                    top10_holder_pct=31.0,
                    freeze_authority_active=True,
                )
            )
        return build_token_structural_risk_facts_v0(
            token_mint=token, as_of=as_of, observations=rows
        )

    def _funding(self, *, token="MINT", as_of=100, count=1):
        return DirectFundingLinkEvidenceV61(
            method_version="fixture",
            reference_key="launch:1",
            chain_namespace="solana",
            chain_reference="mainnet-beta",
            token_address=token,
            deployer_wallet="DEPLOYER",
            participant_wallet="PARTICIPANT",
            as_of=as_of,
            launch_chain_time=80,
            launch_observed_at=81,
            candidate_transfer_count=count,
            known_prelaunch_transfer_count=count,
            deployer_to_participant_count=count,
            participant_to_deployer_count=0,
            deployer_to_participant_native_count=count,
            participant_to_deployer_native_count=0,
            first_direct_link_offset_seconds=-10 if count else None,
            last_direct_link_offset_seconds=-10 if count else None,
            latest_deployer_to_participant_offset_seconds=-10 if count else None,
            direct_link_transaction_keys=("tx:1",) if count else (),
            evidence_classification=(
                "DIRECT_NATIVE_DEPLOYER_TO_PARTICIPANT_PRELAUNCH"
                if count
                else "NO_CAUSALLY_KNOWN_DIRECT_PRELAUNCH_LINK"
            ),
            data_quality_flags=(),
        )

    def test_surface_exposes_evidence_states_without_score(self):
        surface = build_opportunity_evidence_surface_v0(
            market=self._market(),
            structural_risk=self._risk(),
        )
        states = {item.name: item.state for item in surface.dimensions}
        self.assertEqual(states["market_flow"], "OBSERVED")
        self.assertEqual(states["wallet_identity"], "PARTIAL")
        self.assertEqual(states["notional"], "COMPLETE")
        self.assertEqual(states["price"], "MISSING")
        self.assertEqual(states["execution"], "PROXY_ONLY")
        self.assertEqual(states["structural_risk"], "OBSERVED")
        self.assertEqual(states["direct_funding_links"], "NOT_EVALUATED")
        self.assertFalse(hasattr(surface, "score"))
        self.assertFalse(hasattr(surface, "recommendation"))

    def test_structural_conflict_and_direct_link_are_visible(self):
        surface = build_opportunity_evidence_surface_v0(
            market=self._market(),
            structural_risk=self._risk(conflict=True),
            direct_funding_links=(self._funding(),),
        )
        states = {item.name: item.state for item in surface.dimensions}
        self.assertEqual(states["structural_risk"], "CONFLICT")
        self.assertEqual(states["direct_funding_links"], "DIRECT_LINK_OBSERVED")
        self.assertIn("source_conflict:freeze_authority_active", surface.data_quality_flags)
        self.assertEqual(
            surface.provenance_keys,
            ("market:e1", "risk:a", "risk:b", "launch:1", "tx:1"),
        )

    def test_evaluated_no_direct_link_is_distinct_from_not_evaluated(self):
        surface = build_opportunity_evidence_surface_v0(
            market=self._market(),
            structural_risk=self._risk(),
            direct_funding_links=(self._funding(count=0),),
        )
        states = {item.name: item.state for item in surface.dimensions}
        self.assertEqual(
            states["direct_funding_links"], "EVALUATED_NO_DIRECT_LINK"
        )

    def test_token_or_clock_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            build_opportunity_evidence_surface_v0(
                market=self._market(token="A"),
                structural_risk=self._risk(token="B"),
            )
        with self.assertRaises(ValueError):
            build_opportunity_evidence_surface_v0(
                market=self._market(as_of=100),
                structural_risk=self._risk(as_of=99),
            )


if __name__ == "__main__":
    unittest.main()
