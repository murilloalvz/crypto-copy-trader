from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


CONTRACT_PATH = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
BASE_FIXTURE_PATH = (
    Path("benchmarks")
    / "launch_burst_prospective_route_live_v4"
    / "funded_taker_fixture_v0.frozen.json"
)
SYNTHETIC_TAKER = "SyntheticTakerPublicKeyForOfflineFixtureTestV0"


def _fixture_for_taker(tmp_path: Path, taker: str = SYNTHETIC_TAKER) -> Path:
    fixture = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["taker_public_key_sha256"] = hashlib.sha256(taker.encode("utf-8")).hexdigest()
    fixture["fixture_hash_sha256"] = ft._sha256_payload(
        {key: value for key, value in fixture.items() if key != "fixture_hash_sha256"}
    )
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _funded_balances(**_: object) -> dict[str, int]:
    return {"input_amount_raw": 25_000_000, "sol_lamports": 10_000_000}


def _assembled_probe(**kwargs: object) -> dict[str, object]:
    return {
        "router": "test-router",
        "mode": "manual",
        "transaction_present": True,
        "error_code": None,
        "error_message": None,
        "in_amount_raw": "25000000",
        "out_amount_raw": "123456",
        "in_usd_value": 25.0,
        "out_usd_value": 24.9,
        "swap_usd_value": 25.0,
        "price_impact_pct_points": 0.1,
        "observed_at": 1,
        "output_mint_for_test": str(kwargs["output_mint"]),
    }


class FundedTakerPreflightV0Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_gate(
        self,
        *,
        taker: str = SYNTHETIC_TAKER,
        balance_reader=_funded_balances,
        assembly_probe=_assembled_probe,
    ) -> dict:
        return ft.run_preflight(
            fixture_path=_fixture_for_taker(self.tmp_path),
            contract_path=CONTRACT_PATH,
            rpc_url="https://example.invalid/rpc",
            jupiter_api_key="test-secret-api-key",
            taker_public_key=taker,
            balance_reader=balance_reader,
            assembly_probe=assembly_probe,
        )

    def test_pass_requires_frozen_taker_funding_and_both_assembly_probes(self) -> None:
        report = self.run_gate()
        self.assertEqual(report["classification"], ft.PASS)
        self.assertTrue(report["gates"]["taker_identity_matches_frozen_fixture"])
        self.assertTrue(report["gates"]["minimum_input_balance_met"])
        self.assertTrue(report["gates"]["minimum_sol_balance_met"])
        self.assertTrue(report["gates"]["known_liquid_control_transaction_assembled"])
        self.assertTrue(report["gates"]["representative_burst_transaction_assembled"])
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["provider_execute_called"])

    def test_wrong_taker_fails_before_balance_or_provider_calls(self) -> None:
        calls = {"balance": 0, "probe": 0}

        def balance_reader(**_: object) -> dict[str, int]:
            calls["balance"] += 1
            return _funded_balances()

        def probe(**kwargs: object) -> dict[str, object]:
            calls["probe"] += 1
            return _assembled_probe(**kwargs)

        report = self.run_gate(
            taker="DifferentSyntheticTaker",
            balance_reader=balance_reader,
            assembly_probe=probe,
        )
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(report["gates"]["taker_identity_matches_frozen_fixture"])
        self.assertEqual(calls, {"balance": 0, "probe": 0})

    def test_insufficient_usdc_fails_closed_before_jupiter_probe(self) -> None:
        calls = {"probe": 0}

        def balances(**_: object) -> dict[str, int]:
            return {"input_amount_raw": 24_999_999, "sol_lamports": 10_000_000}

        def probe(**kwargs: object) -> dict[str, object]:
            calls["probe"] += 1
            return _assembled_probe(**kwargs)

        report = self.run_gate(balance_reader=balances, assembly_probe=probe)
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(report["gates"]["minimum_input_balance_met"])
        self.assertTrue(report["gates"]["minimum_sol_balance_met"])
        self.assertEqual(report["probes"]["known_liquid_control"]["status"], "NOT_RUN_BALANCE_GATE")
        self.assertEqual(report["probes"]["representative_burst"]["status"], "NOT_RUN_BALANCE_GATE")
        self.assertEqual(calls["probe"], 0)

    def test_insufficient_sol_fails_closed_before_jupiter_probe(self) -> None:
        calls = {"probe": 0}

        def balances(**_: object) -> dict[str, int]:
            return {"input_amount_raw": 25_000_000, "sol_lamports": 9_999_999}

        def probe(**kwargs: object) -> dict[str, object]:
            calls["probe"] += 1
            return _assembled_probe(**kwargs)

        report = self.run_gate(balance_reader=balances, assembly_probe=probe)
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertTrue(report["gates"]["minimum_input_balance_met"])
        self.assertFalse(report["gates"]["minimum_sol_balance_met"])
        self.assertEqual(calls["probe"], 0)

    def test_known_liquid_control_without_assembled_transaction_fails(self) -> None:
        def probe(**kwargs: object) -> dict[str, object]:
            result = _assembled_probe(**kwargs)
            if kwargs["output_mint"] == "So11111111111111111111111111111111111111112":
                result["transaction_present"] = False
                result["error_code"] = 1
                result["error_message"] = "Insufficient funds"
            return result

        report = self.run_gate(assembly_probe=probe)
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertFalse(report["gates"]["known_liquid_control_transaction_assembled"])
        self.assertTrue(report["gates"]["representative_burst_transaction_assembled"])

    def test_representative_burst_without_assembled_transaction_fails(self) -> None:
        def probe(**kwargs: object) -> dict[str, object]:
            result = _assembled_probe(**kwargs)
            if kwargs["output_mint"] != "So11111111111111111111111111111111111111112":
                result["transaction_present"] = False
                result["error_code"] = 1
                result["error_message"] = "Insufficient funds"
            return result

        report = self.run_gate(assembly_probe=probe)
        self.assertEqual(report["classification"], ft.FAIL)
        self.assertTrue(report["gates"]["known_liquid_control_transaction_assembled"])
        self.assertFalse(report["gates"]["representative_burst_transaction_assembled"])

    def test_report_never_contains_serialized_transaction_or_api_secret(self) -> None:
        report = self.run_gate()
        encoded = json.dumps(report, sort_keys=True)
        self.assertNotIn("test-secret-api-key", encoded)
        self.assertNotIn('"transaction"', encoded)
        self.assertIn("provider_execute_called", report)
        self.assertFalse(report["provider_execute_called"])

    def test_actual_frozen_fixture_matches_unchanged_route_contract(self) -> None:
        fixture = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        gates = ft._validate_fixture(fixture, contract)
        self.assertTrue(all(gates.values()))
        self.assertEqual(
            contract["contract_hash_sha256"],
            "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d",
        )


if __name__ == "__main__":
    unittest.main()
