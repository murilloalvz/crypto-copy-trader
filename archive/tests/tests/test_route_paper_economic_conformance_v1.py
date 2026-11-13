from __future__ import annotations

import asyncio
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from benchmarks.launch_burst_control_taker_sim_v0 import (
    route_paper_economic_conformance_v1 as conformance,
)


class RoutePaperEconomicConformanceV1Tests(unittest.TestCase):
    def test_conformant_wrapper_activates_fix_and_attests_report(self):
        observed = {}

        async def fake_raw_runner(**kwargs):
            del kwargs
            observed.update(conformance.assert_price_impact_semantics_active())
            return {"classification": "PASS_TEST", "guardrails": {}}

        with patch.object(
            conformance,
            "_historical_run_sim_v4",
            side_effect=fake_raw_runner,
        ):
            report = asyncio.run(conformance.run_sim_v4_conformant())

        self.assertEqual(
            observed["conformance_version"],
            conformance.CONFORMANCE_VERSION,
        )
        self.assertTrue(
            report["guardrails"]["price_impact_semantics_fix_applied"]
        )
        self.assertFalse(
            report["guardrails"]["raw_historical_runner_called_without_fix"]
        )
        self.assertEqual(
            report["route_paper_economic_conformance"][
                "price_impact_semantics_fix_version"
            ],
            conformance.FIX_VERSION,
        )

    def test_new_economic_wrappers_cannot_call_raw_runner_without_fix(self):
        repo_root = Path(__file__).resolve().parents[1]
        benchmarks_root = repo_root / "benchmarks"

        allowed_historical = {
            (
                benchmarks_root
                / "launch_burst_control_taker_sim_v0"
                / "run_v4_smart_ladder_25.py"
            ).resolve(): "historical base runner preserved for reproducibility",
            (
                benchmarks_root
                / "early_buyer_churn_prospective_v1"
                / "run_live.py"
            ).resolve(): (
                "closed one-shot prospective wrapper preserved to reproduce the "
                "already-closed INSUFFICIENT_SAMPLE_NO_EXTENSION artifact"
            ),
            (
                benchmarks_root
                / "holder_ownership_structure_v0"
                / "run_live.py"
            ).resolve(): (
                "closed historical Holder Ownership Structure V0 wrapper; "
                "not authorized for new acquisition"
            ),
            (
                benchmarks_root
                / "holder_ownership_native_v1"
                / "run_live.py"
            ).resolve(): (
                "closed historical Holder Ownership Native V1 wrapper; "
                "not authorized for new acquisition"
            ),
            (
                benchmarks_root
                / "holder_ownership_rpc_v2"
                / "run_live.py"
            ).resolve(): (
                "closed historical Holder Ownership RPC V2 wrapper; "
                "not authorized for new acquisition"
            ),
        }

        violations = []
        raw_call = re.compile(r"(?<![A-Za-z0-9_])run_sim_v4\s*\(")

        for path in sorted(benchmarks_root.rglob("*.py")):
            resolved = path.resolve()
            if resolved in allowed_historical:
                continue
            text = path.read_text(encoding="utf-8")
            if not raw_call.search(text):
                continue

            has_fix_context = "patched_price_impact_semantics" in text
            uses_conformant_runner = "run_sim_v4_conformant" in text
            if not (has_fix_context or uses_conformant_runner):
                violations.append(str(path.relative_to(repo_root)))

        self.assertEqual(
            violations,
            [],
            "new economic wrappers call raw run_sim_v4 without corrected "
            "Swap V2 priceImpact semantics: " + ", ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
