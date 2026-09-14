import unittest

from src.token_structural_risk_v0 import (
    StructuralRiskObservationV0,
    build_token_structural_risk_facts_v0,
)


class TokenStructuralRiskV0Tests(unittest.TestCase):
    def test_causal_filter_and_latest_per_source(self):
        rows = [
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=100,
                evidence_key="birdeye:old",
                source="birdeye",
                holder_count=10,
                top10_holder_pct=50.0,
            ),
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=110,
                evidence_key="birdeye:new",
                source="birdeye",
                holder_count=12,
                top10_holder_pct=45.0,
            ),
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=130,
                evidence_key="future",
                source="solanatracker",
                holder_count=99,
            ),
            StructuralRiskObservationV0(
                token_mint="OTHER",
                observed_at=105,
                evidence_key="other",
                source="rpc",
                holder_count=999,
            ),
        ]
        facts = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=120, observations=rows
        )
        self.assertEqual(facts.source_count, 1)
        self.assertEqual(facts.sources, ("birdeye",))
        self.assertEqual(facts.holder_count.min_value, 12.0)
        self.assertEqual(facts.holder_count.max_value, 12.0)
        self.assertEqual(facts.top10_holder_pct.min_value, 45.0)
        self.assertEqual(facts.provenance_keys, ("birdeye:new",))

    def test_numeric_ranges_do_not_invent_consensus(self):
        rows = [
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=100,
                evidence_key="a",
                source="birdeye",
                holder_count=100,
                top10_holder_pct=31.0,
                insider_holder_pct=4.0,
            ),
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=101,
                evidence_key="b",
                source="solanatracker",
                holder_count=104,
                top10_holder_pct=33.5,
                insider_holder_pct=5.0,
            ),
        ]
        facts = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=101, observations=rows
        )
        self.assertEqual(facts.holder_count.min_value, 100.0)
        self.assertEqual(facts.holder_count.max_value, 104.0)
        self.assertEqual(facts.top10_holder_pct.min_value, 31.0)
        self.assertEqual(facts.top10_holder_pct.max_value, 33.5)
        self.assertEqual(facts.insider_holder_pct.known_source_count, 2)

    def test_boolean_claims_require_unanimous_provider_consensus(self):
        rows = [
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=100,
                evidence_key="a",
                source="birdeye",
                mint_authority_active=False,
                freeze_authority_active=False,
                provider_honeypot_flag=False,
            ),
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=101,
                evidence_key="b",
                source="provider-b",
                mint_authority_active=False,
                freeze_authority_active=True,
                provider_honeypot_flag=False,
            ),
        ]
        facts = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=101, observations=rows
        )
        self.assertFalse(facts.mint_authority_active.conflict)
        self.assertFalse(facts.mint_authority_active.consensus_value)
        self.assertTrue(facts.freeze_authority_active.conflict)
        self.assertIsNone(facts.freeze_authority_active.consensus_value)
        self.assertIn(
            "source_conflict:freeze_authority_active", facts.data_quality_flags
        )
        self.assertFalse(facts.provider_honeypot_flag.consensus_value)

    def test_missingness_is_explicit_and_score_free(self):
        facts = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=100, observations=[]
        )
        self.assertEqual(facts.source_count, 0)
        self.assertIsNone(facts.top10_holder_pct.min_value)
        self.assertIsNone(facts.mint_authority_active.consensus_value)
        self.assertIn("no_structural_risk_observations", facts.data_quality_flags)
        self.assertIn("holder_concentration_unavailable", facts.data_quality_flags)
        self.assertFalse(hasattr(facts, "score"))
        self.assertFalse(hasattr(facts, "recommendation"))

    def test_provider_claims_and_creator_wallets_are_preserved(self):
        rows = [
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=100,
                evidence_key="a",
                source="birdeye",
                dev_holder_pct=7.0,
                sniper_holder_pct=3.0,
                bundler_holder_pct=2.0,
                liquidity_burned_pct=100.0,
                creator_wallet="CREATOR",
            ),
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=100,
                evidence_key="b",
                source="solanatracker",
                dev_holder_pct=8.0,
                insider_holder_pct=4.0,
                creator_wallet="CREATOR",
            ),
        ]
        facts = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=100, observations=rows
        )
        self.assertEqual(facts.creator_wallets, ("CREATOR",))
        self.assertEqual(facts.dev_holder_pct.min_value, 7.0)
        self.assertEqual(facts.dev_holder_pct.max_value, 8.0)
        self.assertEqual(facts.liquidity_burned_pct.max_value, 100.0)
        self.assertNotIn(
            "provider_tagged_holder_profile_unavailable", facts.data_quality_flags
        )

    def test_invalid_percent_and_bool_are_rejected(self):
        with self.assertRaises(ValueError):
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=1,
                evidence_key="bad",
                source="provider",
                top10_holder_pct=101.0,
            )
        with self.assertRaises(ValueError):
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=1,
                evidence_key="bad",
                source="provider",
                mint_authority_active=1,
            )


if __name__ == "__main__":
    unittest.main()
