import unittest

from src.pump_creation_mode_facts import (
    PUMP_CREATION_MODE_FACTS_VERSION,
    PumpCreationModeObservation,
    build_pump_creation_mode_facts_v0,
)


class PumpCreationModeFactsV0Tests(unittest.TestCase):
    def _obs(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            chain_time=100,
            observed_at=101,
            evidence_key="tx:create-v2:0",
            source="carbon_pumpfun_decoder",
            evidence_kind="pump_create_v2_instruction",
            is_mayhem_mode=True,
            decoder_version="carbon-pumpfun-decoder-2.x",
        )
        values.update(overrides)
        return PumpCreationModeObservation(**values)

    def test_unknown_without_explicit_create_v2_evidence(self):
        facts = build_pump_creation_mode_facts_v0(token_mint="MINT_A", as_of=100)
        self.assertEqual(facts.method_version, PUMP_CREATION_MODE_FACTS_VERSION)
        self.assertIsNone(facts.mayhem_mode)
        self.assertIn("pump_create_v2_mode_not_observed", facts.data_quality_flags)

    def test_true_and_false_are_explicit_protocol_facts(self):
        true_facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A", as_of=101, observations=(self._obs(),)
        )
        false_facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A",
            as_of=101,
            observations=(self._obs(is_mayhem_mode=False),),
        )
        self.assertTrue(true_facts.mayhem_mode)
        self.assertFalse(false_facts.mayhem_mode)

    def test_future_observed_evidence_is_invisible(self):
        facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A",
            as_of=105,
            observations=(self._obs(observed_at=106),),
        )
        self.assertIsNone(facts.mayhem_mode)

    def test_observation_cannot_precede_chain_time(self):
        with self.assertRaises(ValueError):
            self._obs(chain_time=101, observed_at=100)

    def test_exact_mint_isolation(self):
        facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A",
            as_of=101,
            observations=(self._obs(token_mint="MINT_B"),),
        )
        self.assertIsNone(facts.mayhem_mode)

    def test_conflicting_explicit_evidence_fails_closed(self):
        rows = (
            self._obs(evidence_key="a", is_mayhem_mode=True),
            self._obs(
                chain_time=101,
                observed_at=102,
                evidence_key="b",
                is_mayhem_mode=False,
            ),
        )
        facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A", as_of=102, observations=rows
        )
        self.assertIsNone(facts.mayhem_mode)
        self.assertIn("pump_create_v2_mayhem_mode_conflict", facts.data_quality_flags)
        self.assertEqual(facts.provenance_keys, ("a", "b"))

    def test_rejects_non_protocol_or_inferred_evidence_kind(self):
        with self.assertRaises(ValueError):
            self._obs(evidence_kind="high_trade_intensity_inference")

    def test_output_has_no_score_confidence_or_recommendation(self):
        facts = build_pump_creation_mode_facts_v0(
            token_mint="MINT_A", as_of=101, observations=(self._obs(),)
        )
        forbidden = {"score", "confidence", "recommendation", "take", "skip"}
        self.assertTrue(forbidden.isdisjoint(facts.__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
