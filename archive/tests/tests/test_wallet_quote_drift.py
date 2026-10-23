import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_drift import (
    WalletQuotePathPoint,
    build_wallet_quote_drift_observations,
    load_successful_quote_path_points,
    summarize_wallet_quote_drift,
)
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


def point(
    key: str,
    *,
    delay: int,
    price: float,
    side: str = "buy",
    route: str | None = "r1",
) -> WalletQuotePathPoint:
    return WalletQuotePathPoint(
        source_event_key=key,
        wallet_address="W",
        token_mint="T",
        side=side,
        wallet_chain_time=90,
        wallet_observed_at=100,
        delay_seconds=delay,
        target_at=100 + delay,
        requested_at=101 + delay,
        completed_at=102 + delay,
        quote_observed_at=102 + delay,
        price_usd=price,
        executable=False,
        source="jupiter-test",
        route_id=route,
    )


class WalletQuoteDriftTests(unittest.TestCase):
    def test_buy_price_increase_is_adverse_and_sell_price_drop_is_adverse(self):
        buy_rows = build_wallet_quote_drift_observations(
            [point("buy", delay=0, price=1.0), point("buy", delay=30, price=1.1)]
        )
        sell_rows = build_wallet_quote_drift_observations(
            [
                point("sell", delay=0, price=1.0, side="sell"),
                point("sell", delay=30, price=0.9, side="sell"),
            ]
        )

        self.assertAlmostEqual(buy_rows[0].adverse_execution_drift_pct, 10.0)
        self.assertAlmostEqual(sell_rows[0].raw_price_change_pct, -10.0)
        self.assertAlmostEqual(sell_rows[0].adverse_execution_drift_pct, 10.0)

    def test_only_same_event_is_paired_and_missing_baseline_is_visible_by_absence(self):
        observations = build_wallet_quote_drift_observations(
            [
                point("a", delay=0, price=1.0),
                point("a", delay=60, price=1.2),
                point("b", delay=60, price=0.5),
            ]
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].source_event_key, "a")
        self.assertAlmostEqual(observations[0].adverse_execution_drift_pct, 20.0)

    def test_route_change_is_reported_only_when_both_routes_are_known(self):
        changed = build_wallet_quote_drift_observations(
            [point("a", delay=0, price=1.0, route="r1"), point("a", delay=15, price=1.0, route="r2")]
        )[0]
        unknown = build_wallet_quote_drift_observations(
            [point("b", delay=0, price=1.0, route=None), point("b", delay=15, price=1.0, route="r2")]
        )[0]

        self.assertTrue(changed.route_changed)
        self.assertIsNone(unknown.route_changed)

    def test_summary_reports_paired_coverage_and_adverse_distribution(self):
        points = [
            point("a", delay=0, price=1.0),
            point("a", delay=30, price=1.1),
            point("b", delay=0, price=2.0),
        ]
        observations = build_wallet_quote_drift_observations(points)
        summary = summarize_wallet_quote_drift(points, observations)

        self.assertEqual(summary.baseline_event_count, 2)
        self.assertEqual(len(summary.delays), 1)
        delay = summary.delays[0]
        self.assertEqual(delay.paired_count, 1)
        self.assertEqual(delay.paired_coverage_pct, 50.0)
        self.assertAlmostEqual(delay.median_adverse_drift_pct, 10.0)

    def test_database_loader_is_exact_event_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote-drift.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 90, 100),
                    observation_key="event-a",
                )
                event = load_forward_buys_after(0)[0]
                probes = schedule_buy_quotes([event], delays_seconds=[0, 30])
                for probe, price in zip(probes, (1.0, 1.05)):
                    record_causal_quote(
                        CausalQuoteObservation(
                            token_mint="T",
                            side="buy",
                            market_time=probe.target_at,
                            observed_at=probe.target_at + 1,
                            price_usd=price,
                            source="jupiter-test",
                            executable=False,
                            route_id="route",
                        ),
                        quote_key=probe.quote_key,
                    )
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at + 1,
                        status="success",
                        quote_key=probe.quote_key,
                    )

                loaded = load_successful_quote_path_points(source_event_keys=["event-a"])
                missing = load_successful_quote_path_points(source_event_keys=["other"])

        self.assertEqual([item.delay_seconds for item in loaded], [0, 30])
        self.assertEqual(missing, ())

    def test_invalid_mixed_token_in_one_event_is_rejected(self):
        rows = [point("a", delay=0, price=1.0), point("a", delay=30, price=1.1)]
        rows[1] = WalletQuotePathPoint(**{**rows[1].__dict__, "token_mint": "OTHER"})

        with self.assertRaises(ValueError):
            build_wallet_quote_drift_observations(rows)


if __name__ == "__main__":
    unittest.main()
