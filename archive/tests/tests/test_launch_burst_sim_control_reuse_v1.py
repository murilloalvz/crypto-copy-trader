from __future__ import annotations

import hashlib
from unittest.mock import patch
import unittest

from benchmarks.launch_burst_control_taker_sim_v0 import run_v4_smart_ladder_25 as runner


CONTROL = "PublicControl"
CONTROL_SHA = hashlib.sha256(CONTROL.encode("utf-8")).hexdigest()


class LaunchBurstSimControlReuseV1Tests(unittest.TestCase):
    @staticmethod
    def fixture() -> dict:
        return {
            "minimum_input_amount_raw": 25_000_000,
            "minimum_sol_lamports": 10_000_000,
        }

    @staticmethod
    def metadata() -> dict:
        return {
            "owner_public_key_sha256": CONTROL_SHA,
            "token_account_amount_raw": 30_000_000,
            "sol_lamports": 20_000_000,
            "address_redacted": True,
        }

    def test_exact_preflight_override_is_reused_without_rediscovery(self):
        with patch.object(
            runner,
            "_discover_control_via_helius_holders",
            side_effect=AssertionError("must not rediscover"),
        ):
            control, meta = runner._resolve_sim_control(
                fixture=self.fixture(),
                rpc_url="rpc",
                helius_api_key="helius",
                control_taker_override=CONTROL,
                control_meta_override=self.metadata(),
            )
        self.assertEqual(control, CONTROL)
        self.assertEqual(meta["owner_public_key_sha256"], CONTROL_SHA)
        self.assertEqual(meta["control_resolution_mode"], "EXACT_PREFLIGHT_REUSE")

    def test_override_metadata_identity_mismatch_is_fail_closed(self):
        bad = self.metadata()
        bad["owner_public_key_sha256"] = "bad"
        with self.assertRaisesRegex(ValueError, "metadata does not match"):
            runner._resolve_sim_control(
                fixture=self.fixture(),
                rpc_url="rpc",
                helius_api_key="helius",
                control_taker_override=CONTROL,
                control_meta_override=bad,
            )

    def test_override_below_frozen_balance_floor_is_fail_closed(self):
        bad = self.metadata()
        bad["token_account_amount_raw"] = 1
        with self.assertRaisesRegex(ValueError, "USDC floor"):
            runner._resolve_sim_control(
                fixture=self.fixture(),
                rpc_url="rpc",
                helius_api_key="helius",
                control_taker_override=CONTROL,
                control_meta_override=bad,
            )

    def test_normal_mode_passes_explicit_helius_key_to_discovery(self):
        with patch.object(
            runner,
            "_discover_control_via_helius_holders",
            return_value=(CONTROL, self.metadata()),
        ) as discover:
            control, meta = runner._resolve_sim_control(
                fixture=self.fixture(),
                rpc_url="rpc",
                helius_api_key="helius-explicit",
                control_taker_override=None,
                control_meta_override=None,
            )
        self.assertEqual(control, CONTROL)
        self.assertEqual(meta["control_resolution_mode"], "DISCOVERED_AT_RUN_START")
        discover.assert_called_once_with(
            fixture=self.fixture(),
            rpc_url="rpc",
            helius_api_key="helius-explicit",
        )


if __name__ == "__main__":
    unittest.main()
