import unittest

from benchmarks.market_regime_detector_v0.causal_intensity import (
    MarketCoverageInterval,
    build_causal_intensity_series_v0,
)
from src.market_opportunity_radar import MarketTradeObservation


class CausalMarketIntensityV0Tests(unittest.TestCase):
    def _trade(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            side="buy",
            chain_time=101,
            observed_at=102,
            wallet_address="W1",
            notional_usd=10.0,
            price_usd=1.0,
            venue="pump",
            transaction_key="TX1",
        )
        values.update(overrides)
        return MarketTradeObservation(**values)

    def _coverage(self, **overrides):
        values = dict(
            start_chain_time=100,
            end_chain_time=105,
            available_at=105,
            source="synthetic_stream",
            token_mint="MINT_A",
            evidence_key="cov-100-105",
        )
        values.update(overrides)
        return MarketCoverageInterval(**values)

    def test_uncovered_empty_bins_are_missing_not_zero(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=104,
            start_chain_time=100,
            end_chain_time=105,
            trades=(self._trade(),),
            coverage=(),
        )
        self.assertEqual(series.observed_bin_count, 0)
        self.assertEqual(series.missing_bin_count, 5)
        self.assertTrue(all(row.status == "MISSING" for row in series.bins))
        self.assertTrue(all(row.event_count is None for row in series.bins))

    def test_covered_empty_bins_are_observed_zero(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=105,
            start_chain_time=100,
            end_chain_time=105,
            trades=(self._trade(),),
            coverage=(self._coverage(),),
        )
        self.assertEqual(series.observed_bin_count, 5)
        self.assertEqual(series.missing_bin_count, 0)
        counts = [row.event_count for row in series.bins]
        self.assertEqual(counts, [0, 1, 0, 0, 0])
        self.assertEqual(series.observed_coverage_pct, 100.0)

    def test_future_coverage_assertion_is_not_available(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=105,
            start_chain_time=100,
            end_chain_time=105,
            trades=(self._trade(),),
            coverage=(self._coverage(available_at=106),),
        )
        self.assertEqual(series.observed_bin_count, 0)
        self.assertEqual(series.missing_bin_count, 5)

    def test_future_observed_trade_is_invisible_even_in_covered_bin(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=105,
            start_chain_time=100,
            end_chain_time=105,
            trades=(self._trade(observed_at=106),),
            coverage=(self._coverage(),),
        )
        self.assertEqual([row.event_count for row in series.bins], [0, 0, 0, 0, 0])

    def test_exact_mint_isolation_applies_to_trades_and_coverage(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=105,
            start_chain_time=100,
            end_chain_time=105,
            trades=(self._trade(token_mint="MINT_B"),),
            coverage=(self._coverage(token_mint="MINT_B"),),
        )
        self.assertEqual(series.observed_bin_count, 0)
        self.assertEqual(series.missing_bin_count, 5)

    def test_adjacent_intervals_can_jointly_cover_a_wider_bin(self):
        coverage = (
            self._coverage(
                start_chain_time=100,
                end_chain_time=102,
                available_at=104,
                evidence_key="a",
            ),
            self._coverage(
                start_chain_time=102,
                end_chain_time=104,
                available_at=104,
                evidence_key="b",
            ),
        )
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=104,
            start_chain_time=100,
            end_chain_time=104,
            trades=(),
            coverage=coverage,
            bin_seconds=4,
        )
        self.assertEqual(series.bins[0].status, "OBSERVED")
        self.assertEqual(series.bins[0].event_count, 0)
        self.assertEqual(series.bins[0].coverage_evidence_keys, ("a", "b"))

    def test_partial_bin_coverage_stays_missing(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=104,
            start_chain_time=100,
            end_chain_time=104,
            trades=(),
            coverage=(
                self._coverage(
                    start_chain_time=100,
                    end_chain_time=103,
                    available_at=104,
                ),
            ),
            bin_seconds=4,
        )
        self.assertEqual(series.bins[0].status, "MISSING")
        self.assertIsNone(series.bins[0].event_count)

    def test_global_coverage_interval_is_allowed(self):
        series = build_causal_intensity_series_v0(
            token_mint="MINT_A",
            as_of=105,
            start_chain_time=100,
            end_chain_time=105,
            coverage=(self._coverage(token_mint=None),),
        )
        self.assertEqual(series.observed_bin_count, 5)


if __name__ == "__main__":
    unittest.main()
