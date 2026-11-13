import unittest

from src.market_protocol_facts import (
    MARKET_PROTOCOL_FACTS_VERSION,
    PumpCurveStateObservation,
    PumpMigrationEvidence,
    PumpSwapPoolObservation,
    build_market_protocol_facts_v0,
)


class MarketProtocolFactsV0Tests(unittest.TestCase):
    def _pump(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            chain_time=100,
            observed_at=101,
            evidence_key="pump-100",
            source="synthetic_pump",
            complete=False,
            quote_mint="SOL",
            virtual_token_reserves=1_000,
            virtual_quote_reserves=100,
            real_token_reserves=800,
            real_quote_reserves=20,
            token_total_supply=1_000,
        )
        values.update(overrides)
        return PumpCurveStateObservation(**values)

    def _swap(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            pool="POOL_A",
            chain_time=140,
            observed_at=141,
            evidence_key="swap-140",
            source="synthetic_pumpswap",
            base_mint="MINT_A",
            quote_mint="SOL",
            pool_index=0,
            pool_base_token_reserves=700,
            pool_quote_token_reserves=300,
            virtual_quote_reserves=5,
        )
        values.update(overrides)
        return PumpSwapPoolObservation(**values)

    def _migration(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            pool="POOL_A",
            pool_index=0,
            chain_time=145,
            observed_at=146,
            evidence_key="migration-145",
            source="synthetic_pump_migrate",
            evidence_kind="pump_migrate_instruction",
        )
        values.update(overrides)
        return PumpMigrationEvidence(**values)

    def test_unknown_when_no_causal_protocol_evidence_exists(self):
        facts = build_market_protocol_facts_v0(token_mint="MINT_A", as_of=100)
        self.assertEqual(facts.method_version, MARKET_PROTOCOL_FACTS_VERSION)
        self.assertEqual(facts.lifecycle_label, "UNKNOWN")
        self.assertFalse(facts.pump_activity_observed)
        self.assertFalse(facts.pumpswap_activity_observed)
        self.assertFalse(facts.canonical_migration_proven)

    def test_exact_mint_isolation(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A",
            as_of=200,
            pump_curve_observations=(self._pump(token_mint="MINT_B"),),
            pumpswap_pool_observations=(self._swap(token_mint="MINT_B"),),
            migration_evidence=(self._migration(token_mint="MINT_B"),),
        )
        self.assertEqual(facts.lifecycle_label, "UNKNOWN")
        self.assertEqual(facts.provenance_keys, ())

    def test_future_observed_at_is_invisible_and_future_append_is_invariant(self):
        current = self._pump()
        future = self._pump(
            chain_time=110,
            observed_at=130,
            evidence_key="future-complete",
            complete=True,
            real_token_reserves=0,
        )
        before = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=120, pump_curve_observations=(current,)
        )
        appended = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=120, pump_curve_observations=(current, future)
        )
        self.assertEqual(before, appended)
        self.assertFalse(appended.pump_curve_complete)
        later = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=130, pump_curve_observations=(current, future)
        )
        self.assertTrue(later.pump_curve_complete)
        self.assertEqual(later.lifecycle_label, "PUMP_CURVE_COMPLETE")

    def test_chain_clock_ahead_does_not_hide_already_observed_protocol_evidence(self):
        ahead = self._pump(
            chain_time=200,
            observed_at=100,
            evidence_key="chain-ahead",
            complete=True,
        )
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=150, pump_curve_observations=(ahead,)
        )
        self.assertEqual(facts.lifecycle_label, "PUMP_CURVE_COMPLETE")
        self.assertEqual(facts.pump_latest_chain_time, 200)
        self.assertIn(
            "chain_clock_ahead_of_local_snapshot_clock_observed",
            facts.data_quality_flags,
        )

    def test_late_observation_of_older_chain_state_is_causal_after_arrival(self):
        late = self._pump(chain_time=90, observed_at=150, evidence_key="late-90")
        before = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=149, pump_curve_observations=(late,)
        )
        after = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=150, pump_curve_observations=(late,)
        )
        self.assertEqual(before.lifecycle_label, "UNKNOWN")
        self.assertEqual(after.lifecycle_label, "PUMP_BONDING_ACTIVE")

    def test_curve_completion_is_not_inferred_from_reserves(self):
        zero_real = self._pump(complete=None, real_token_reserves=0)
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=120, pump_curve_observations=(zero_real,)
        )
        self.assertIsNone(facts.pump_curve_complete)
        self.assertEqual(facts.lifecycle_label, "PUMP_BONDING_ACTIVE")
        self.assertIn("pump_curve_complete_missing", facts.data_quality_flags)

    def test_complete_true_then_false_fails_closed_as_conflict(self):
        rows = (
            self._pump(chain_time=100, observed_at=100, complete=True, evidence_key="true"),
            self._pump(chain_time=110, observed_at=110, complete=False, evidence_key="false"),
        )
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=120, pump_curve_observations=rows
        )
        self.assertIsNone(facts.pump_curve_complete)
        self.assertIn("pump_curve_complete_regression_conflict", facts.data_quality_flags)

    def test_pumpswap_activity_never_proves_migration(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A",
            as_of=150,
            pumpswap_pool_observations=(self._swap(pool_index=0),),
        )
        self.assertTrue(facts.pumpswap_activity_observed)
        self.assertFalse(facts.canonical_migration_proven)
        self.assertEqual(facts.lifecycle_label, "PUMPSWAP_ACTIVE_UNPROVEN_LINEAGE")
        self.assertIn("pumpswap_lineage_unproven", facts.data_quality_flags)

    def test_explicit_canonical_migration_proves_lineage(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A",
            as_of=160,
            pumpswap_pool_observations=(self._swap(),),
            migration_evidence=(self._migration(),),
        )
        self.assertTrue(facts.canonical_migration_proven)
        self.assertEqual(facts.lifecycle_label, "PUMPSWAP_MIGRATED_CANONICAL")
        self.assertEqual(facts.migration_pool, "POOL_A")
        self.assertEqual(facts.migration_evidence_kind, "pump_migrate_instruction")

    def test_nonzero_migration_pool_index_does_not_prove_canonical_migration(self):
        evidence = self._migration(pool_index=1, evidence_key="migration-noncanonical")
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=160, migration_evidence=(evidence,)
        )
        self.assertFalse(facts.canonical_migration_proven)
        self.assertIn("migration_evidence_noncanonical_pool_index", facts.data_quality_flags)

    def test_effective_pumpswap_quote_reserves_require_virtual_reserve(self):
        with_virtual = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=150, pumpswap_pool_observations=(self._swap(),)
        )
        self.assertEqual(with_virtual.pumpswap_effective_quote_reserves, 305)
        without_virtual = build_market_protocol_facts_v0(
            token_mint="MINT_A",
            as_of=150,
            pumpswap_pool_observations=(
                self._swap(virtual_quote_reserves=None, evidence_key="swap-no-virtual"),
            ),
        )
        self.assertIsNone(without_virtual.pumpswap_effective_quote_reserves)
        self.assertIn("pumpswap_virtual_quote_reserves_missing", without_virtual.data_quality_flags)

    def test_signed_virtual_quote_reserve_is_allowed_when_effective_is_nonnegative(self):
        row = self._swap(pool_quote_token_reserves=300, virtual_quote_reserves=-20)
        self.assertEqual(row.effective_quote_reserves, 280)
        with self.assertRaises(ValueError):
            self._swap(pool_quote_token_reserves=10, virtual_quote_reserves=-20)

    def test_provenance_is_deterministic_and_causal_only(self):
        rows = (
            self._pump(evidence_key="z"),
            self._pump(chain_time=101, observed_at=101, evidence_key="a"),
            self._pump(chain_time=102, observed_at=999, evidence_key="future"),
        )
        facts = build_market_protocol_facts_v0(
            token_mint="MINT_A", as_of=200, pump_curve_observations=rows
        )
        self.assertEqual(facts.provenance_keys, ("a", "z"))

    def test_output_has_no_score_confidence_or_recommendation_surface(self):
        facts = build_market_protocol_facts_v0(token_mint="MINT_A", as_of=100)
        forbidden = {"score", "confidence", "recommendation", "take", "skip"}
        self.assertTrue(forbidden.isdisjoint(facts.__dataclass_fields__))

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            self._pump(chain_time=-1)
        with self.assertRaises(ValueError):
            self._pump(virtual_token_reserves=-1)
        with self.assertRaises(ValueError):
            self._migration(evidence_kind="someone_said_it_migrated")
        with self.assertRaises(ValueError):
            build_market_protocol_facts_v0(token_mint="", as_of=1)


if __name__ == "__main__":
    unittest.main()
