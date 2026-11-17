from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft
from benchmarks.launch_burst_prospective_route_live_v4 import no_funds_assembly_diagnostic as diag


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
TAKER = "SyntheticFrozenTakerForNoFundsDiagnostic"
PUBLIC_CONTROL = "SyntheticPublicFundedControlOwner"


def _fixture_for_taker(tmp_path: Path) -> Path:
    fixture = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["taker_public_key_sha256"] = hashlib.sha256(TAKER.encode("utf-8")).hexdigest()
    fixture["fixture_hash_sha256"] = ft._sha256_payload(
        {key: value for key, value in fixture.items() if key != "fixture_hash_sha256"}
    )
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _zero_balances(**_: object) -> dict[str, int]:
    return {"input_amount_raw": 0, "sol_lamports": 0}


def _rpc_factory(*, discover: bool = True):
    def rpc_call(_url: str, method: str, params: list[object]):
        if method == "getTokenLargestAccounts":
            if not discover:
                return {"value": []}
            return {"value": [{"address": "TokenAccount1", "amount": "50000000"}]}
        if method == "getAccountInfo":
            return {
                "value": {
                    "data": {
                        "parsed": {
                            "info": {"owner": PUBLIC_CONTROL}
                        }
                    }
                }
            }
        if method == "getBalance":
            return {"value": 20_000_000}
        raise AssertionError((method, params))
    return rpc_call


def _probe_factory(*, public_control_burst: bool = True):
    def probe(**kwargs: object) -> dict[str, object]:
        taker = str(kwargs["taker_public_key"])
        output_mint = str(kwargs["output_mint"])
        is_public = taker == PUBLIC_CONTROL
        is_control = output_mint == "So11111111111111111111111111111111111111112"
        tx_present = is_public and (is_control or public_control_burst)
        return {
            "router": "test-router",
            "mode": "manual",
            "transaction_present": tx_present,
            "error_code": None if tx_present else 1,
            "error_message": None if tx_present else "Insufficient funds",
            "in_amount_raw": "25000000",
            "out_amount_raw": "123456",
            "in_usd_value": 25.0,
            "out_usd_value": 24.9,
            "swap_usd_value": 25.0,
            "price_impact_pct_points": 0.1,
            "observed_at": 1,
        }
    return probe


class NoFundsAssemblyDiagnosticV0Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_diag(self, *, rpc_call=None, assembly_probe=None) -> dict:
        return diag.run_diagnostic(
            fixture_path=_fixture_for_taker(self.tmp_path),
            contract_path=CONTRACT_PATH,
            rpc_url="https://example.invalid/rpc",
            jupiter_api_key="test-secret-key",
            frozen_taker_public_key=TAKER,
            rpc_call=rpc_call or _rpc_factory(),
            balance_reader=_zero_balances,
            assembly_probe=assembly_probe or _probe_factory(),
        )

    def test_public_control_can_confirm_provider_assembly_while_frozen_taker_is_zero(self) -> None:
        report = self.run_diag()
        self.assertEqual(report["classification"], diag.PROVIDER_CONFIRMED)
        self.assertEqual(report["frozen_taker"]["balances"], {"input_amount_raw": 0, "sol_lamports": 0})
        self.assertFalse(report["frozen_taker"]["known_liquid_control"]["transaction_present"])
        self.assertFalse(report["frozen_taker"]["representative_burst"]["transaction_present"])
        self.assertTrue(report["public_funded_control"]["known_liquid_control"]["transaction_present"])
        self.assertTrue(report["public_funded_control"]["representative_burst"]["transaction_present"])
        self.assertFalse(report["official_funded_taker_gate_passed"])
        self.assertFalse(report["provider_execute_called"])
        self.assertFalse(report["economic_outcomes_opened"])

    def test_control_only_is_separate_from_representative_burst(self) -> None:
        report = self.run_diag(assembly_probe=_probe_factory(public_control_burst=False))
        self.assertEqual(report["classification"], diag.CONTROL_ONLY)
        self.assertTrue(report["public_funded_control"]["known_liquid_control"]["transaction_present"])
        self.assertFalse(report["public_funded_control"]["representative_burst"]["transaction_present"])
        self.assertFalse(report["official_funded_taker_gate_passed"])

    def test_no_public_control_does_not_promote_official_gate(self) -> None:
        report = self.run_diag(rpc_call=_rpc_factory(discover=False))
        self.assertEqual(report["classification"], diag.NOT_CONFIRMED)
        self.assertEqual(report["public_funded_control"]["status"], "DISCOVERY_ERROR")
        self.assertFalse(report["official_funded_taker_gate_passed"])

    def test_report_does_not_expose_public_control_address_or_secret(self) -> None:
        report = self.run_diag()
        encoded = json.dumps(report, sort_keys=True)
        self.assertNotIn(PUBLIC_CONTROL, encoded)
        self.assertNotIn("test-secret-key", encoded)
        self.assertNotIn('"transaction"', encoded)
        self.assertIn("owner_public_key_sha256", encoded)


if __name__ == "__main__":
    unittest.main()
