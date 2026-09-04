from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import jupiter_provider_attempt_diagnostic as diagnostic


def _attempt(*, status: str, details=None, error_type=None, error_message=None, episode="ep-1"):
    return SimpleNamespace(
        episode_key=episode,
        status=status,
        details=details or {},
        error_type=error_type,
        error_message=error_message,
    )


class JupiterProviderAttemptDiagnosticTests(unittest.TestCase):
    def test_no_sample_is_explicit(self):
        with patch.object(diagnostic, "list_provider_attempts", return_value=()):
            output = io.StringIO()
            with redirect_stdout(output):
                code = diagnostic.diagnose_run("run")
        self.assertEqual(code, 2)
        self.assertIn("INCONCLUSIVE_NO_SAMPLE", output.getvalue())

    def test_groups_provider_reason_without_new_provider_io(self):
        attempts = (
            _attempt(
                status="UNAVAILABLE",
                details={
                    "provider_error_code": 42,
                    "provider_error_message": "insufficient account state",
                    "assembled_transaction_present": False,
                    "route_id": "route-a",
                    "router": "iris",
                },
                episode="ep-a",
            ),
            _attempt(
                status="UNAVAILABLE",
                details={
                    "provider_error_code": 42,
                    "provider_error_message": "insufficient account state",
                    "assembled_transaction_present": False,
                    "route_id": "route-b",
                    "router": "iris",
                },
                episode="ep-b",
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                code = diagnostic.diagnose_run("run")
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("count=2 source=provider code=42 message=insufficient account state", text)
        self.assertIn("classification=FAIL_ALL_UNAVAILABLE", text)
        self.assertIn("attempts_with_route_id=2", text)

    def test_unavailable_without_provider_reason_is_not_invented(self):
        attempts = (
            _attempt(
                status="UNAVAILABLE",
                details={"assembled_transaction_present": False},
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                diagnostic.diagnose_run("run")
        self.assertIn(
            "source=assembly code=none message=assembled transaction absent without provider error",
            output.getvalue(),
        )

    def test_available_attempt_classifies_pass(self):
        attempts = (
            _attempt(
                status="AVAILABLE",
                details={
                    "assembled_transaction_present": True,
                    "route_id": "route",
                    "router": "iris",
                },
            ),
        )
        with patch.object(diagnostic, "list_provider_attempts", return_value=attempts):
            output = io.StringIO()
            with redirect_stdout(output):
                diagnostic.diagnose_run("run")
        text = output.getvalue()
        self.assertIn("assembled_transactions=1", text)
        self.assertIn("classification=PASS_HAS_EXECUTABLE", text)


if __name__ == "__main__":
    unittest.main()
