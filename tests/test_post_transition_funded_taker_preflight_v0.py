from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.post_transition_reacceleration_v0 import funded_taker_preflight as ft


BASE_FIXTURE = (
    Path("benchmarks")
    / "post_transition_reacceleration_v0"
    / "funded_taker_fixture_v0.frozen.json"
)
TAKER = "SyntheticPostTransitionTakerV0"


def _fixture_for_taker(tmp_path: Path) -> Path:
    fixture = json.loads(BASE_FIXTURE.read_text(encoding="utf-8"))
    fixture["taker_public_key_sha256"] = hashlib.sha256(
        TAKER.encode("utf-8")
    ).hexdigest()
    unhashed = {
        key: value
        for key, value in fixture.items()
        if key != "fixture_hash_sha256"
    }
    fixture["fixture_hash_sha256"] = ft._sha256_payload(unhashed)
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(fixture, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _balances(*, input_raw=25_000_000, sol=10_000_000):
    def reader(**_: object) -> dict[str, int]:
        return {
            "input_amount_raw": input_raw,
            "sol_lamports": sol,
        }
    return reader


def _probe(*, tx=True, error_code=None):
    def probe(**_: object) -> dict[str, object]:
        return {
            "router": "metis",
            "mode": "manual",
            "transaction_present": tx,
            "error_code": error_code,
            "error_message": None if error_code in {None, 0} else "test-error",
            "in_amount_raw": "25000000",
            "out_amount_raw": "123",
            "in_usd_value": 25.0,
            "out_usd_value": 24.9,
            "swap_usd_value": 25.0,
            "price_impact_pct_points": 0.1,
            "observed_at": 1,
        }
    return probe


class PostTransitionFundedTakerPreflightV0Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_gate(self, *, balance_reader=None, assembly_probe=None, taker=TAKER):
        return ft.run_preflight(
            fixture_path=_fixture_for_taker(self.tmp),
            rpc_url="https://example.invalid/rpc",
            jupiter_api_key="test-secret",
            taker_public_key=taker,
            balance_reader=balance_reader or _balances(),
            assembly_probe=assembly_probe or _probe(),
        )

    def test_pass_requires_frozen_identity_balances_and_control_assembly(self):
        report = self.run_gate()
        self.assertEqual(report["classification"], ft.PASS)
        self.assertTrue(
            report["gates"]["taker_identity_matches_frozen_fixture"]
        )
        self.assertTrue(report["gates"]["minimum_input_balance_met"])
        self.assertTrue(report["gates"]["minimum_sol_balance_met"])
        self.assertTrue(report["gates"]["control_transaction_assembled"])
        self.assertEqual(report["cohort_tokens_queried"], 0)
        self.assertFalse(report["fresh_economic_outcomes_opened"])
        self.assertFalse(report["transaction_submitted"])
        self.assertFalse(report["provider_execute_called"])

    def test_zero_funding_fails_before_provider_probe(self):
        calls = {"probe": 0}
        def probe(**_: object):
            calls["probe"] += 1
            return _probe()()
        report = self.run_gate(
            balance_reader=_balances(input_raw=0, sol=0),
            assembly_probe=probe,
        )
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(report["gates"]["minimum_input_balance_met"])
        self.assertFalse(report["gates"]["minimum_sol_balance_met"])
        self.assertEqual(report["probe"]["status"], "NOT_RUN_BALANCE_GATE")
        self.assertEqual(calls["probe"], 0)

    def test_exact_floors_are_accepted(self):
        report = self.run_gate(
            balance_reader=_balances(
                input_raw=25_000_000,
                sol=10_000_000,
            )
        )
        self.assertEqual(report["classification"], ft.PASS)

    def test_missing_assembled_transaction_fails(self):
        report = self.run_gate(assembly_probe=_probe(tx=False, error_code=2))
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(report["gates"]["control_transaction_assembled"])

    def test_wrong_taker_fails_before_balance_or_provider_calls(self):
        calls = {"balance": 0, "probe": 0}
        def balances(**_: object):
            calls["balance"] += 1
            return {"input_amount_raw": 25_000_000, "sol_lamports": 10_000_000}
        def probe(**_: object):
            calls["probe"] += 1
            return _probe()()
        report = self.run_gate(
            taker="different-taker",
            balance_reader=balances,
            assembly_probe=probe,
        )
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(
            report["gates"]["taker_identity_matches_frozen_fixture"]
        )
        self.assertEqual(calls, {"balance": 0, "probe": 0})

    def test_fixture_is_bound_to_current_collector_contract(self):
        fixture = json.loads(BASE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["economic_collector_contract_hash_sha256"],
            "902d388c6d1435c7a47cc552a93f8c9f7e1df5ca0c89ff8f2b5cc1bd90998e15",
        )
        self.assertEqual(fixture["minimum_input_amount_raw"], 25_000_000)
        self.assertEqual(fixture["minimum_sol_lamports"], 10_000_000)
        self.assertFalse(fixture["cohort_token_probe_before_fresh_run"])


if __name__ == "__main__":
    unittest.main()
