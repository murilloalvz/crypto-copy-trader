from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY as DEFAULT_SMART_POLICY,
)
from benchmarks.launch_burst_sniper_v1.preflight import (
    PASS,
    DEFAULT_SNIPER_POLICY,
    prepare_preflight_control,
    run_preflight,
)


PUBLIC_CONTROL = "PublicControl"
PUBLIC_CONTROL_SHA = hashlib.sha256(PUBLIC_CONTROL.encode("utf-8")).hexdigest()


class LaunchBurstSniperPreflightV1Tests(unittest.TestCase):
    def _discover(self, calls):
        def discover_control(*, fixture, rpc_url, helius_api_key):
            calls.append((fixture["fixture_hash_sha256"], rpc_url, helius_api_key))
            return PUBLIC_CONTROL, {
                "owner_public_key_sha256": PUBLIC_CONTROL_SHA,
                "token_account_amount_raw": 25_000_000,
                "sol_lamports": 20_000_000,
                "address_redacted": True,
            }
        return discover_control

    @staticmethod
    def _passing_probe(outputs):
        def assembly_probe(**kwargs):
            outputs.append(kwargs["output_mint"])
            return {
                "transaction_present": True,
                "error_code": None,
                "error_message": None,
            }
        return assembly_probe

    def test_read_only_preflight_passes_with_frozen_config_and_assembly(self):
        discovery_calls = []
        probe_outputs = []
        report = run_preflight(
            contract_path=Path(DEFAULT_CONTRACT),
            fixture_path=Path(DEFAULT_FIXTURE),
            smart_policy_path=Path(DEFAULT_SMART_POLICY),
            sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
            duration_seconds=900,
            helius_api_key="helius-test",
            jupiter_api_key="jupiter-test",
            rpc_url="https://rpc.invalid",
            discover_control=self._discover(discovery_calls),
            assembly_probe=self._passing_probe(probe_outputs),
        )

        self.assertEqual(report["classification"], PASS)
        self.assertTrue(report["gates"]["all_read_only_support_checks_pass"])
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["transaction_signed"])
        self.assertFalse(report["transaction_submitted"])
        self.assertEqual(discovery_calls[0][2], "helius-test")
        self.assertEqual(len(discovery_calls), 1)
        self.assertEqual(len(probe_outputs), 2)
        self.assertNotIn("owner_public_key", report["public_control"])

    def test_prepare_returns_exact_control_only_after_pass(self):
        report, control = prepare_preflight_control(
            contract_path=Path(DEFAULT_CONTRACT),
            fixture_path=Path(DEFAULT_FIXTURE),
            smart_policy_path=Path(DEFAULT_SMART_POLICY),
            sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
            duration_seconds=900,
            helius_api_key="helius-test",
            jupiter_api_key="jupiter-test",
            rpc_url="https://rpc.invalid",
            discover_control=self._discover([]),
            assembly_probe=self._passing_probe([]),
        )
        self.assertEqual(report["classification"], PASS)
        self.assertEqual(control, PUBLIC_CONTROL)
        self.assertEqual(report["public_control"]["owner_public_key_sha256"], PUBLIC_CONTROL_SHA)

    def test_missing_environment_fails_before_discovery(self):
        called = False

        def discover_control(**kwargs):
            nonlocal called
            called = True
            raise AssertionError(kwargs)

        report, control = prepare_preflight_control(
            contract_path=Path(DEFAULT_CONTRACT),
            fixture_path=Path(DEFAULT_FIXTURE),
            smart_policy_path=Path(DEFAULT_SMART_POLICY),
            sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
            duration_seconds=900,
            helius_api_key="",
            jupiter_api_key="jupiter-test",
            rpc_url="https://rpc.invalid",
            discover_control=discover_control,
        )
        self.assertNotEqual(report["classification"], PASS)
        self.assertFalse(report["gates"]["frozen_configuration_valid"])
        self.assertIsNone(control)
        self.assertFalse(called)

    def test_representative_burst_assembly_is_fail_closed_and_control_not_released(self):
        probe_count = 0

        def assembly_probe(**kwargs):
            nonlocal probe_count
            del kwargs
            probe_count += 1
            return {
                "transaction_present": probe_count == 1,
                "error_code": None if probe_count == 1 else 1,
                "error_message": None if probe_count == 1 else "no route",
            }

        report, control = prepare_preflight_control(
            contract_path=Path(DEFAULT_CONTRACT),
            fixture_path=Path(DEFAULT_FIXTURE),
            smart_policy_path=Path(DEFAULT_SMART_POLICY),
            sniper_policy_path=Path(DEFAULT_SNIPER_POLICY),
            duration_seconds=900,
            helius_api_key="helius-test",
            jupiter_api_key="jupiter-test",
            rpc_url="https://rpc.invalid",
            discover_control=self._discover([]),
            assembly_probe=assembly_probe,
        )
        self.assertNotEqual(report["classification"], PASS)
        self.assertTrue(report["gates"]["known_liquid_control_assembly"])
        self.assertFalse(report["gates"]["representative_burst_assembly"])
        self.assertFalse(report["gates"]["all_read_only_support_checks_pass"])
        self.assertIsNone(control)


if __name__ == "__main__":
    unittest.main()
