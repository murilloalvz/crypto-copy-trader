import math
import unittest

from src.causal_quotes import CausalQuoteObservation
from src.market_first_exit_geometry_v58 import (
    MarketFirstExitPathPointV58,
    available_path_point_from_quotes_v58,
    build_market_first_exit_geometry_v58,
    route_only_return_from_quotes_v58,
)


def _quote(
    *,
    side: str,
    observed_at: int,
    price_usd: float,
    executable: bool = False,
    token_mint: str = "TOKEN",
    input_mint: str | None = None,
    output_mint: str | None = None,
    input_amount_raw: str | None = None,
    output_amount_raw: str | None = None,
) -> CausalQuoteObservation:
    return CausalQuoteObservation(
        token_mint=token_mint,
        side=side,
        market_time=observed_at,
        observed_at=observed_at,
        price_usd=price_usd,
        source="test_route_only",
        executable=executable,
        input_mint=input_mint,
        output_mint=output_mint,
        input_amount_raw=input_amount_raw,
        output_amount_raw=output_amount_raw,
    )


class MarketFirstExitGeometryV58Tests(unittest.TestCase):
    def test_geometry_measures_excursions_and_giveback_without_policy(self):
        geometry = build_market_first_exit_geometry_v58(
            decision_as_of=100,
            points=[
                MarketFirstExitPathPointV58("p1", 110, "AVAILABLE", 5.0, "q1"),
                MarketFirstExitPathPointV58("p2", 120, "AVAILABLE", 40.0, "q2"),
                MarketFirstExitPathPointV58("p3", 130, "AVAILABLE", -10.0, "q3"),
                MarketFirstExitPathPointV58("p4", 150, "AVAILABLE", 20.0, "q4"),
            ],
        )
        self.assertEqual(geometry.classification, "COMPLETE_ROUTE_PATH")
        self.assertEqual(geometry.coverage_pct, 100.0)
        self.assertEqual(geometry.mfe_pct, 40.0)
        self.assertEqual(geometry.mae_pct, -10.0)
        self.assertEqual(geometry.time_to_mfe_seconds, 20)
        self.assertEqual(geometry.time_to_mae_seconds, 30)
        self.assertEqual(geometry.last_observed_return_pct, 20.0)
        self.assertEqual(geometry.peak_to_last_giveback_pct_points, 20.0)
        self.assertEqual(geometry.last_observed_mfe_capture_pct, 50.0)
        self.assertEqual(geometry.max_available_gap_seconds, 20)

    def test_missing_route_stays_missing_and_reduces_coverage(self):
        geometry = build_market_first_exit_geometry_v58(
            decision_as_of=100,
            points=[
                MarketFirstExitPathPointV58("p1", 110, "AVAILABLE", 10.0, "q1"),
                MarketFirstExitPathPointV58("p2", 120, "UNAVAILABLE"),
                MarketFirstExitPathPointV58("p3", 130, "PROVIDER_ERROR", error_type="Timeout"),
                MarketFirstExitPathPointV58("p4", 140, "AVAILABLE", 5.0, "q4"),
            ],
        )
        self.assertEqual(geometry.classification, "PARTIAL_ROUTE_PATH")
        self.assertEqual(geometry.available_points, 2)
        self.assertEqual(geometry.unavailable_or_error_points, 2)
        self.assertEqual(geometry.coverage_pct, 50.0)
        self.assertEqual(geometry.mfe_pct, 10.0)
        self.assertEqual(geometry.mae_pct, 0.0)
        self.assertEqual(geometry.max_available_gap_seconds, 30)

    def test_no_available_route_does_not_create_fake_zero_return_path(self):
        geometry = build_market_first_exit_geometry_v58(
            decision_as_of=100,
            points=[
                MarketFirstExitPathPointV58("p1", 110, "UNAVAILABLE"),
                MarketFirstExitPathPointV58("p2", 120, "PROVIDER_ERROR", error_type="x"),
            ],
        )
        self.assertEqual(geometry.classification, "NO_AVAILABLE_ROUTE_PATH")
        self.assertIsNone(geometry.mfe_pct)
        self.assertIsNone(geometry.mae_pct)
        self.assertIsNone(geometry.last_observed_return_pct)

    def test_all_negative_path_keeps_entry_zero_as_mfe(self):
        geometry = build_market_first_exit_geometry_v58(
            decision_as_of=100,
            points=[
                MarketFirstExitPathPointV58("p1", 110, "AVAILABLE", -4.0, "q1"),
                MarketFirstExitPathPointV58("p2", 120, "AVAILABLE", -12.0, "q2"),
            ],
        )
        self.assertEqual(geometry.mfe_pct, 0.0)
        self.assertEqual(geometry.time_to_mfe_seconds, 0)
        self.assertEqual(geometry.mae_pct, -12.0)
        self.assertEqual(geometry.time_to_mae_seconds, 20)
        self.assertIsNone(geometry.last_observed_mfe_capture_pct)

    def test_duplicate_second_is_rejected_as_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "duplicate observed_at"):
            build_market_first_exit_geometry_v58(
                decision_as_of=100,
                points=[
                    MarketFirstExitPathPointV58("p1", 110, "AVAILABLE", 1.0, "q1"),
                    MarketFirstExitPathPointV58("p2", 110, "AVAILABLE", 2.0, "q2"),
                ],
            )

    def test_missing_point_cannot_synthesize_return(self):
        with self.assertRaisesRegex(ValueError, "cannot synthesize return_pct"):
            build_market_first_exit_geometry_v58(
                decision_as_of=100,
                points=[MarketFirstExitPathPointV58("p1", 110, "UNAVAILABLE", 0.0)],
            )

    def test_quote_return_requires_exact_raw_buy_output_on_sell(self):
        entry = _quote(
            side="buy",
            observed_at=100,
            price_usd=1.0,
            output_mint="TOKEN",
            output_amount_raw="123",
        )
        exit_quote = _quote(
            side="sell",
            observed_at=110,
            price_usd=1.2,
            input_mint="TOKEN",
            input_amount_raw="124",
        )
        with self.assertRaisesRegex(ValueError, "exact raw BUY token output"):
            route_only_return_from_quotes_v58(
                entry_quote=entry,
                exit_quote=exit_quote,
                decision_as_of=100,
            )

    def test_quote_return_and_available_point_follow_route_only_lineage(self):
        entry = _quote(
            side="buy",
            observed_at=99,
            price_usd=2.0,
            output_mint="TOKEN",
            output_amount_raw="123",
        )
        exit_quote = _quote(
            side="sell",
            observed_at=120,
            price_usd=3.0,
            input_mint="TOKEN",
            input_amount_raw="123",
        )
        value = route_only_return_from_quotes_v58(
            entry_quote=entry,
            exit_quote=exit_quote,
            decision_as_of=100,
        )
        self.assertTrue(math.isclose(value, 50.0))
        point = available_path_point_from_quotes_v58(
            observation_key="obs",
            quote_key="exit-quote",
            entry_quote=entry,
            exit_quote=exit_quote,
            decision_as_of=100,
        )
        self.assertEqual(point.status, "AVAILABLE")
        self.assertEqual(point.observed_at, 120)
        self.assertTrue(math.isclose(float(point.return_pct), 50.0))

    def test_executable_quote_is_rejected(self):
        entry = _quote(side="buy", observed_at=99, price_usd=1.0)
        exit_quote = _quote(
            side="sell",
            observed_at=120,
            price_usd=1.1,
            executable=True,
            input_mint="TOKEN",
            output_mint="USDC",
        )
        with self.assertRaisesRegex(ValueError, "non-executable"):
            route_only_return_from_quotes_v58(
                entry_quote=entry,
                exit_quote=exit_quote,
                decision_as_of=100,
            )

    def test_post_decision_clock_is_strict(self):
        with self.assertRaisesRegex(ValueError, "strictly after"):
            build_market_first_exit_geometry_v58(
                decision_as_of=100,
                points=[MarketFirstExitPathPointV58("p1", 100, "AVAILABLE", 1.0, "q1")],
            )


if __name__ == "__main__":
    unittest.main()
