import unittest

from src.opportunity_evidence_explainer_v0 import explain_opportunity_evidence_v0
from src.opportunity_evidence_surface_v0 import (
    EvidenceDimensionV0,
    OpportunityEvidenceSurfaceV0,
)
from src.token_structural_risk_v0 import (
    StructuralRiskObservationV0,
    build_token_structural_risk_facts_v0,
)


class OpportunityEvidenceExplainerV0Tests(unittest.TestCase):
    def _surface(self, *, conflict=False):
        rows = [
            StructuralRiskObservationV0(
                token_mint="MINT",
                observed_at=90,
                evidence_key="risk:a",
                source="provider-a",
                holder_count=100,
                top10_holder_pct=30.0,
                insider_holder_pct=4.0,
                freeze_authority_active=False,
                creator_wallet="CREATOR",
            )
        ]
        if conflict:
            rows.append(
                StructuralRiskObservationV0(
                    token_mint="MINT",
                    observed_at=91,
                    evidence_key="risk:b",
                    source="provider-b",
                    holder_count=102,
                    top10_holder_pct=32.0,
                    insider_holder_pct=5.0,
                    freeze_authority_active=True,
                    creator_wallet="CREATOR",
                )
            )
        risk = build_token_structural_risk_facts_v0(
            token_mint="MINT", as_of=100, observations=rows
        )
        dimensions = (
            EvidenceDimensionV0("market_flow", "OBSERVED", ("10s_events=4",)),
            EvidenceDimensionV0("wallet_identity", "PARTIAL", ("10s=50.0",)),
            EvidenceDimensionV0("notional", "COMPLETE", ("10s=100.0",)),
            EvidenceDimensionV0("price", "MISSING", ("10s=0.0",)),
            EvidenceDimensionV0("execution", "PROXY_ONLY", ("quote_count=2", "executable_quote_count=0")),
            EvidenceDimensionV0(
                "structural_risk",
                "CONFLICT" if conflict else "OBSERVED",
                (f"source_count={risk.source_count}",),
            ),
            EvidenceDimensionV0("direct_funding_links", "NOT_EVALUATED", ()),
        )
        return OpportunityEvidenceSurfaceV0(
            method_version="fixture",
            token_mint="MINT",
            as_of=100,
            lifecycle_label="PUMP_BONDING_ACTIVE",
            market=None,
            structural_risk=risk,
            direct_funding_links=(),
            dimensions=dimensions,
            provenance_keys=("market:e1", *risk.provenance_keys),
            data_quality_flags=risk.data_quality_flags,
        )

    def test_explanation_is_factual_and_score_free(self):
        explanation = explain_opportunity_evidence_v0(self._surface())
        states = {section.name: section.state for section in explanation.sections}
        self.assertEqual(states["market_flow"], "OBSERVED")
        self.assertEqual(states["wallet_identity"], "PARTIAL")
        self.assertEqual(states["execution"], "PROXY_ONLY")
        structural = next(
            section for section in explanation.sections if section.name == "structural_risk"
        )
        self.assertIn("holder_count=100.0 (1 source(s))", structural.facts)
        self.assertIn("top10_holder_pct=30.0 (1 source(s))", structural.facts)
        self.assertIn("creator_wallets=CREATOR", structural.facts)
        self.assertFalse(hasattr(explanation, "score"))
        self.assertFalse(hasattr(explanation, "recommendation"))
        self.assertFalse(hasattr(explanation, "confidence_pct"))

    def test_missing_and_proxy_states_become_cautions(self):
        explanation = explain_opportunity_evidence_v0(self._surface())
        sections = {section.name: section for section in explanation.sections}
        self.assertIn("wallet_identity_evidence_partial", sections["wallet_identity"].cautions)
        self.assertIn("price_evidence_missing", sections["price"].cautions)
        self.assertIn("execution_evidence_proxy_only", sections["execution"].cautions)

    def test_provider_conflict_is_exposed_not_resolved(self):
        explanation = explain_opportunity_evidence_v0(self._surface(conflict=True))
        structural = next(
            section for section in explanation.sections if section.name == "structural_risk"
        )
        self.assertEqual(structural.state, "CONFLICT")
        self.assertIn("source_conflict:freeze_authority_active", structural.cautions)
        self.assertIn("holder_count_range=100.0..102.0 (2 source(s))", structural.facts)
        self.assertIn("top10_holder_pct_range=30.0..32.0 (2 source(s))", structural.facts)


if __name__ == "__main__":
    unittest.main()
