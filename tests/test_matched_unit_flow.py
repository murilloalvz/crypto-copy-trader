import unittest

from src.matched_unit_flow import (
    MATCHED_UNIT_FLOW_VERSION,
    MatchedUnitFlowObservation,
    build_matched_unit_flow_facts_v0,
)


class MatchedUnitFlowFactsV0Tests(unittest.TestCase):
    def _obs(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            side="buy",
            chain_time=100,
            observed_at=101,
            venue="pump",
            market_surface_key="pump:MINT_A",
            quote_asset_key="So11111111111111111111111111111111111111112",
            quote_amount_raw=10,
            quote_reserve_raw=100,
            reserve_kind="pump_virtual_quote",
            evidence_key="tx:0",
        )
        values.update(overrides)
        return MatchedUnitFlowObservation(**values)

    def test_same_unit_pressure_is_dimensionless_and_directional(self):
        rows = (
            self._obs(evidence_key="a", chain_time=100, quote_amount_raw=10, quote_reserve_raw=100),
            self._obs(evidence_key="b", chain_time=101, quote_amount_raw=20, quote_reserve_raw=200),
            self._obs(evidence_key="c", chain_time=102, side="sell", quote_amount_raw=5, quote_reserve_raw=100),
        )
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A", as_of=105, observations=rows, windows_seconds=(10,)
        )
        self.assertEqual(facts.method_version, MATCHED_UNIT_FLOW_VERSION)
        self.assertTrue(facts.available)
        self.assertEqual(len(facts.surface_windows), 1)
        window = facts.surface_windows[0]
        self.assertEqual(window.event_count, 3)
        self.assertEqual(window.buy_count, 2)
        self.assertEqual(window.sell_count, 1)
        self.assertEqual(window.signed_quote_amount_raw, 25)
        self.assertEqual(window.gross_quote_amount_raw, 35)
        self.assertAlmostEqual(window.signed_quote_over_first_reserve_pct, 25.0)
        self.assertAlmostEqual(window.gross_quote_turnover_over_first_reserve_pct, 35.0)
        # +10/100 +20/200 -5/100 = +0.15
        self.assertAlmostEqual(window.cumulative_signed_event_reserve_fraction_pct, 15.0)
        self.assertAlmostEqual(window.cumulative_gross_event_reserve_fraction_pct, 25.0)
        self.assertIn(
            "event_reported_quote_reserve_changed_within_window",
            window.data_quality_flags,
        )

    def test_surfaces_and_quote_assets_are_never_blended(self):
        rows = (
            self._obs(evidence_key="pump"),
            self._obs(
                evidence_key="pool-a",
                venue="pumpswap",
                market_surface_key="pumpswap:POOL_A",
                reserve_kind="pumpswap_pool_quote",
            ),
            self._obs(
                evidence_key="pool-b",
                venue="pumpswap",
                market_surface_key="pumpswap:POOL_B",
                quote_asset_key="USDC_MINT",
                reserve_kind="pumpswap_pool_quote",
            ),
        )
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A", as_of=105, observations=rows, windows_seconds=(10,)
        )
        self.assertEqual(len(facts.surface_windows), 3)
        keys = {
            (
                item.venue,
                item.market_surface_key,
                item.quote_asset_key,
                item.reserve_kind,
            )
            for item in facts.surface_windows
        }
        self.assertEqual(len(keys), 3)

    def test_dual_clock_gate_hides_future_delivery_and_stale_market_time(self):
        rows = (
            self._obs(evidence_key="visible", chain_time=100, observed_at=101),
            self._obs(evidence_key="future", chain_time=101, observed_at=106),
            self._obs(evidence_key="stale", chain_time=90, observed_at=100),
        )
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A", as_of=105, observations=rows, windows_seconds=(10,)
        )
        self.assertEqual(facts.surface_windows[0].provenance_keys, ("visible",))
        # Eligible provenance retains causally known stale history, while the window does not.
        self.assertEqual(facts.provenance_keys, ("stale", "visible"))

    def test_wrong_token_is_ignored(self):
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A",
            as_of=105,
            observations=(self._obs(token_mint="MINT_B"),),
            windows_seconds=(10,),
        )
        self.assertFalse(facts.available)
        self.assertEqual(facts.surface_windows, ())
        self.assertIn("matched_unit_flow_unavailable", facts.data_quality_flags)

    def test_identical_duplicate_evidence_is_idempotent(self):
        row = self._obs(evidence_key="same")
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A",
            as_of=105,
            observations=(row, row),
            windows_seconds=(10,),
        )
        self.assertEqual(facts.surface_windows[0].event_count, 1)
        self.assertEqual(facts.provenance_keys, ("same",))

    def test_conflicting_evidence_visible_at_t0_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "conflicting matched-unit evidence"):
            build_matched_unit_flow_facts_v0(
                token_mint="MINT_A",
                as_of=105,
                observations=(
                    self._obs(evidence_key="same", quote_amount_raw=10),
                    self._obs(evidence_key="same", quote_amount_raw=11),
                ),
                windows_seconds=(10,),
            )

    def test_conflict_arriving_after_t0_does_not_retroactively_change_snapshot(self):
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A",
            as_of=105,
            observations=(
                self._obs(evidence_key="same", quote_amount_raw=10, observed_at=101),
                self._obs(evidence_key="same", quote_amount_raw=11, observed_at=106),
            ),
            windows_seconds=(10,),
        )
        self.assertEqual(facts.surface_windows[0].signed_quote_amount_raw, 10)

    def test_invalid_reserve_or_amount_fails(self):
        for field in ("quote_amount_raw", "quote_reserve_raw"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build_matched_unit_flow_facts_v0(
                        token_mint="MINT_A",
                        as_of=105,
                        observations=(self._obs(**{field: 0}),),
                        windows_seconds=(10,),
                    )

    def test_output_has_no_score_confidence_recommendation_or_action(self):
        facts = build_matched_unit_flow_facts_v0(
            token_mint="MINT_A",
            as_of=105,
            observations=(self._obs(),),
            windows_seconds=(10,),
        )
        forbidden = {"score", "confidence", "recommendation", "take", "skip", "action"}
        self.assertTrue(forbidden.isdisjoint(facts.__dataclass_fields__))
        self.assertTrue(
            forbidden.isdisjoint(facts.surface_windows[0].__dataclass_fields__)
        )


if __name__ == "__main__":
    unittest.main()
