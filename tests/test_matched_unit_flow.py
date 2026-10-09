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

    def _build(
        self,
        *,
        observations=(),
        as_of=105,
        chain_as_of=105,
        windows_seconds=(10,),
        token_mint="MINT_A",
    ):
        return build_matched_unit_flow_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            observations=observations,
            windows_seconds=windows_seconds,
        )

    def test_same_unit_pressure_is_dimensionless_and_directional(self):
        rows = (
            self._obs(evidence_key="a", chain_time=100, observed_at=101, quote_amount_raw=10, quote_reserve_raw=100),
            self._obs(evidence_key="b", chain_time=101, observed_at=102, quote_amount_raw=20, quote_reserve_raw=200),
            self._obs(evidence_key="c", chain_time=102, observed_at=103, side="sell", quote_amount_raw=5, quote_reserve_raw=100),
        )
        facts = self._build(observations=rows)
        self.assertEqual(facts.method_version, MATCHED_UNIT_FLOW_VERSION)
        self.assertEqual(facts.chain_as_of, 105)
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
        self.assertAlmostEqual(window.cumulative_signed_event_reserve_fraction_pct, 15.0)
        self.assertAlmostEqual(window.cumulative_gross_event_reserve_fraction_pct, 25.0)
        self.assertIn(
            "event_reported_quote_reserve_changed_within_window",
            window.data_quality_flags,
        )
        self.assertIn("cross_clock_latency_not_calibrated", facts.data_quality_flags)

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
        facts = self._build(observations=rows)
        self.assertEqual(len(facts.surface_windows), 3)
        keys = {
            (item.venue, item.market_surface_key, item.quote_asset_key, item.reserve_kind)
            for item in facts.surface_windows
        }
        self.assertEqual(len(keys), 3)

    def test_dual_clock_gate_hides_future_delivery_and_stale_market_time(self):
        rows = (
            self._obs(evidence_key="visible", chain_time=100, observed_at=101),
            self._obs(evidence_key="future", chain_time=101, observed_at=106),
            self._obs(evidence_key="stale", chain_time=90, observed_at=100),
        )
        facts = self._build(observations=rows)
        self.assertEqual(facts.surface_windows[0].provenance_keys, ("visible",))
        self.assertEqual(facts.provenance_keys, ("stale", "visible"))

    def test_chain_clock_ahead_of_local_clock_is_valid_with_separate_anchor(self):
        row = self._obs(chain_time=106, observed_at=105, evidence_key="ahead")
        facts = self._build(observations=(row,), chain_as_of=106)
        self.assertEqual(facts.surface_windows[0].provenance_keys, ("ahead",))
        self.assertIn(
            "chain_clock_ahead_of_local_observation_clock_observed",
            facts.data_quality_flags,
        )

    def test_chain_anchor_is_required_for_visible_observations(self):
        with self.assertRaisesRegex(ValueError, "chain_as_of is required"):
            build_matched_unit_flow_facts_v0(
                token_mint="MINT_A",
                as_of=105,
                observations=(self._obs(),),
                windows_seconds=(10,),
            )

    def test_wrong_token_is_ignored(self):
        facts = self._build(
            observations=(self._obs(token_mint="MINT_B"),), chain_as_of=None
        )
        self.assertFalse(facts.available)
        self.assertEqual(facts.surface_windows, ())
        self.assertIn("matched_unit_flow_unavailable", facts.data_quality_flags)

    def test_identical_duplicate_evidence_is_idempotent(self):
        row = self._obs(evidence_key="same")
        facts = self._build(observations=(row, row))
        self.assertEqual(facts.surface_windows[0].event_count, 1)
        self.assertEqual(facts.provenance_keys, ("same",))

    def test_conflicting_evidence_visible_at_t0_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "conflicting matched-unit evidence"):
            self._build(
                observations=(
                    self._obs(evidence_key="same", quote_amount_raw=10),
                    self._obs(evidence_key="same", quote_amount_raw=11),
                )
            )

    def test_conflict_arriving_after_t0_does_not_retroactively_change_snapshot(self):
        facts = self._build(
            observations=(
                self._obs(evidence_key="same", quote_amount_raw=10, observed_at=101),
                self._obs(evidence_key="same", quote_amount_raw=11, observed_at=106),
            )
        )
        self.assertEqual(facts.surface_windows[0].signed_quote_amount_raw, 10)

    def test_invalid_reserve_or_amount_fails(self):
        for field in ("quote_amount_raw", "quote_reserve_raw"):
            for value in (0, True, 1.5, "10"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self._build(observations=(self._obs(**{field: value}),))

    def test_invalid_clock_and_window_types_fail(self):
        for field, value in (
            ("chain_time", 100.5),
            ("observed_at", "101"),
            ("chain_time", True),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self._build(observations=(self._obs(**{field: value}),))
        for as_of in (105.0, "105", True):
            with self.subTest(as_of=as_of):
                with self.assertRaises(ValueError):
                    self._build(as_of=as_of, observations=(self._obs(),))
        for chain_as_of in (105.0, "105", True, -1):
            with self.subTest(chain_as_of=chain_as_of):
                with self.assertRaises(ValueError):
                    self._build(chain_as_of=chain_as_of, observations=(self._obs(),))
        for windows in ((10.0,), (True,), ("10",)):
            with self.subTest(windows=windows):
                with self.assertRaises(ValueError):
                    self._build(observations=(self._obs(),), windows_seconds=windows)

    def test_output_has_no_score_confidence_recommendation_or_action(self):
        facts = self._build(observations=(self._obs(),))
        forbidden = {"score", "confidence", "recommendation", "take", "skip", "action"}
        self.assertTrue(forbidden.isdisjoint(facts.__dataclass_fields__))
        self.assertTrue(forbidden.isdisjoint(facts.surface_windows[0].__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
