from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import hazard_provider_attempt_diagnostic as diagnostic


def _attempt(*, status: str, error_type=None, error_message=None, details=None, episode="ep-1"):
    return SimpleNamespace(
        episode_key=episode,
        status=status,
        error_type=error_type,
        error_message=error_message,
        details=details or {},
    )


class HazardProviderAttemptDiagnosticTests(unittest.TestCase):
    def test_no_sample_is_explicit(self):
        with patch.object(diagnostic, "list_provider_attempts", return_value=()):
            output = io.StringIO()
            with redirect_stdout(output):
                code = diagnostic.diagnose_run("run")
        self.assertEqual(code, 2)
        self.assertIn("INCONCLUSIVE_NO_SAMPLE", output.getvalue())

    def test_groups_all_rate_limit_failures_from_persisted_errors(self):
        attempts = (
            _attempt(
                status="PROVIDER_ERROR",
                error_type="SolanaTrackerRateLimitError",
                error_message="Limite do Solana Tracker atingido após novas tentativas.",
                episode="ep-a",
            ),
            _attempt(
                status="PROVIDER_ERROR",
                error_type="SolanaTrackerError",
                error_message="Solana Tracker HTTP 429: too many requests",
                episode="ep-b",
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                code = diagnostic.diagnose_run("run")
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("reason_categories={'RATE_LIMIT': 2}", text)
        self.assertIn("classification=FAIL_ALL_PROVIDER_ERROR_RATE_LIMIT", text)

    def test_auth_and_network_are_not_collapsed(self):
        attempts = (
            _attempt(
                status="PROVIDER_ERROR",
                error_type="SolanaTrackerAuthenticationError",
                error_message="Solana Tracker recusou a API key (HTTP 403): forbidden",
                episode="ep-a",
            ),
            _attempt(
                status="PROVIDER_ERROR",
                error_type="SolanaTrackerError",
                error_message="connection reset by peer 10054",
                episode="ep-b",
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                diagnostic.diagnose_run("run")
        text = output.getvalue()
        self.assertIn("'AUTH': 1", text)
        self.assertIn("'NETWORK': 1", text)
        self.assertIn("classification=FAIL_ALL_PROVIDER_ERROR_MIXED_CAUSES", text)

    def test_available_attempt_classifies_pass(self):
        attempts = (
            _attempt(
                status="AVAILABLE",
                details={"observed_at": 123, "risk_score": 4.0},
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                diagnostic.diagnose_run("run")
        text = output.getvalue()
        self.assertIn("available_with_observation=1", text)
        self.assertIn("classification=PASS_HAS_AVAILABLE_HAZARD", text)


if __name__ == "__main__":
    unittest.main()
