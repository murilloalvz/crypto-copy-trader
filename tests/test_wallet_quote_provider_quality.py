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
from src.wallet_quote_provider_quality import summarize_wallet_quote_provider_quality
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletQuoteProviderQualityTests(unittest.TestCase):
    def test_expected_grid_reports_provider_metadata_by_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                event = load_forward_buys_after(0)[0]
                probes = schedule_buy_quotes([event], delays_seconds=[0, 15])
                impacts = [-0.1, 0.2]
                for probe, impact in zip(probes, impacts):
                    record_causal_quote(
                        CausalQuoteObservation(
                            token_mint="T",
                            side="buy",
                            market_time=probe.target_at,
                            observed_at=probe.target_at,
                            price_usd=1.0,
                            source="jupiter_swap_v2_order:metis",
                            executable=False,
                            provider_router="metis",
                            provider_slippage_bps=50,
                            provider_price_impact_pct_points=impact,
                            provider_swap_usd_value=25.0,
                        ),
                        quote_key=probe.quote_key,
                    )
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at,
                        status="success",
                        quote_key=probe.quote_key,
                    )

                summary = summarize_wallet_quote_provider_quality(
                    [event], delays_seconds=[0, 15]
                )

        self.assertEqual(summary.expected_quote_count, 2)
        self.assertEqual(summary.successful_quote_count, 2)
        self.assertEqual(summary.metadata_count, 2)
        self.assertEqual(summary.metadata_coverage_pct, 100.0)
        by_delay = {item.delay_seconds: item for item in summary.delays}
        self.assertAlmostEqual(by_delay[0].median_price_impact_pct_points, -0.1)
        self.assertAlmostEqual(by_delay[15].p95_abs_price_impact_pct_points, 0.2)
        self.assertEqual(by_delay[15].median_slippage_bps, 50)
        self.assertEqual(by_delay[15].routers, (("metis", 1),))

    def test_legacy_success_quote_is_counted_but_metadata_remains_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                event = load_forward_buys_after(0)[0]
                probe = schedule_buy_quotes([event], delays_seconds=[0])[0]
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=110,
                        observed_at=110,
                        price_usd=1.0,
                        source="legacy",
                        executable=False,
                    ),
                    quote_key=probe.quote_key,
                )
                record_quote_attempt(
                    probe,
                    requested_at=110,
                    completed_at=110,
                    status="success",
                    quote_key=probe.quote_key,
                )

                summary = summarize_wallet_quote_provider_quality(
                    [event], delays_seconds=[0]
                )

        self.assertEqual(summary.successful_quote_count, 1)
        self.assertEqual(summary.metadata_count, 0)
        self.assertEqual(summary.metadata_coverage_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
