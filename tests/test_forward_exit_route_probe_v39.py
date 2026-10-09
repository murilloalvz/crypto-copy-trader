from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import forward_exit_route_probe_v39 as runner


class ForwardExitRouteProbeV39Tests(unittest.TestCase):
    def test_no_due_outcomes_is_inconclusive_without_constructing_provider_probe(self):
        output = io.StringIO()
        argv = ["forward_exit_route_probe_v39.py", "--run-key", "run"]
        with patch("sys.argv", argv), patch(
            "forward_exit_route_probe_v39.time.time", return_value=2000
        ), patch(
            "forward_exit_route_probe_v39.load_due_opportunity_forward_outcomes",
            return_value=(),
        ), patch(
            "forward_exit_route_probe_v39.JupiterForwardExitRouteProbe"
        ) as probe_cls, redirect_stdout(output):
            code = runner.main()

        self.assertEqual(code, 0)
        probe_cls.assert_not_called()
        self.assertIn("classification=INCONCLUSIVE_NO_DUE_OFFICIAL_FORWARD_OUTCOMES", output.getvalue())
        self.assertIn("no official outcome completion", output.getvalue())


if __name__ == "__main__":
    unittest.main()
