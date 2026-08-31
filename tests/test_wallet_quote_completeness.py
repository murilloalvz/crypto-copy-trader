import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_completeness import summarize_quote_attempt_completeness
from src.wallet_quote_watch import (
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletQuoteCompletenessTests(unittest.TestCase):
    def test_missing_unattempted_probe_stays_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "completeness.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                event = load_forward_buys_after(0)[0]
                probes = schedule_buy_quotes([event], delays_seconds=[0, 15, 30])
                for probe in probes[:2]:
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at + 1,
                        status="error",
                        error=RuntimeError("test"),
                    )

                summary = summarize_quote_attempt_completeness(
                    [event],
                    delays_seconds=[0, 15, 30],
                )

        self.assertEqual(summary.expected_attempt_count, 3)
        self.assertEqual(summary.attempted_expected_count, 2)
        self.assertEqual(summary.missing_attempt_count, 1)
        self.assertEqual(summary.complete_event_count, 0)
        self.assertEqual(summary.incomplete_event_count, 1)
        by_delay = {item.delay_seconds: item for item in summary.delays}
        self.assertEqual(by_delay[30].missing_count, 1)
        self.assertEqual(by_delay[30].attempt_coverage_pct, 0.0)

    def test_complete_event_requires_every_frozen_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "complete.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                event = load_forward_buys_after(0)[0]
                for probe in schedule_buy_quotes([event], delays_seconds=[0, 15]):
                    record_quote_attempt(
                        probe,
                        requested_at=probe.target_at,
                        completed_at=probe.target_at,
                        status="error",
                        error=RuntimeError("provider"),
                    )

                summary = summarize_quote_attempt_completeness(
                    [event], delays_seconds=[0, 15]
                )

        self.assertEqual(summary.complete_event_count, 1)
        self.assertEqual(summary.complete_event_share_pct, 100.0)
        self.assertEqual(summary.missing_attempt_count, 0)

    def test_unexpected_delay_is_reported_not_counted_as_expected_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unexpected.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("A", "T", "buy", 100, 110),
                    observation_key="buy-a",
                )
                event = load_forward_buys_after(0)[0]
                extra = schedule_buy_quotes([event], delays_seconds=[99])[0]
                record_quote_attempt(
                    extra,
                    requested_at=extra.target_at,
                    completed_at=extra.target_at,
                    status="error",
                    error=RuntimeError("extra"),
                )

                summary = summarize_quote_attempt_completeness(
                    [event], delays_seconds=[0, 15]
                )

        self.assertEqual(summary.unexpected_attempt_count, 1)
        self.assertEqual(summary.attempted_expected_count, 0)
        self.assertEqual(summary.missing_attempt_count, 2)

    def test_empty_event_set_has_zero_coverage_without_fake_completeness(self):
        summary = summarize_quote_attempt_completeness([], delays_seconds=[0, 15])

        self.assertEqual(summary.expected_attempt_count, 0)
        self.assertEqual(summary.complete_event_count, 0)
        self.assertEqual(summary.complete_event_share_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
