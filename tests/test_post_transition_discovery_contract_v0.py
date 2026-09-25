from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.post_transition_reacceleration_v0.discovery_contract import (
    DEFAULT_CONTRACT,
    load_and_validate_contract,
)
from benchmarks.post_transition_reacceleration_v0.research_readiness import (
    DECISION_DELAY_SECONDS,
)


class PostTransitionDiscoveryContractV0Tests(unittest.TestCase):
    def test_frozen_contract_validates_exact_discovery_semantics(self):
        contract = load_and_validate_contract()
        self.assertEqual(
            contract["cohort"]["decision_delay_seconds_from_transition_observed"],
            30,
        )
        self.assertEqual(DECISION_DELAY_SECONDS, 30)
        self.assertEqual(contract["selection"]["selector_predicates"], [])
        self.assertFalse(
            contract["selection"]["structural_reacceleration_candidate_is_selector"]
        )
        self.assertEqual(
            contract["labels"]["primary"]["horizon_seconds_from_entry"],
            60,
        )
        self.assertEqual(
            contract["labels"]["exploratory"]["horizon_seconds_from_entry"],
            300,
        )
        self.assertFalse(
            contract["scientific_guardrails"]["live_money_authorized"]
        )

    def test_contract_rejects_same_sample_selector_mutation(self):
        payload = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        payload["selection"]["selector_predicates"] = [
            {
                "feature": "structural_reacceleration_candidate",
                "op": "==",
                "value": True,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutated.json"
            path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "frozen discovery label contract mismatch",
            ):
                load_and_validate_contract(path)

    def test_contract_rejects_primary_horizon_swap(self):
        payload = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        payload["labels"]["primary"]["horizon_seconds_from_entry"] = 300
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mutated.json"
            path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "frozen discovery label contract mismatch",
            ):
                load_and_validate_contract(path)


if __name__ == "__main__":
    unittest.main()
