import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.robinhood_launch_burst_v0.audit import audit_run
from benchmarks.robinhood_launch_burst_v0.factory_discovery import (
    FACTORY_CANDIDATES_V0,
    discover_factory_v0,
)
from src.robinhood_pons_launch_burst_v0 import (
    PonsLaunchObservationV0,
    PonsTradeObservationV0,
    ZERO_ADDRESS,
    build_snapshot_v0,
)


class FakeRpc:
    def __init__(self, launch_counts=None, code_present=None):
        self.launch_counts = launch_counts or {}
        self.code_present = code_present or {}

    def block_number(self):
        return 10_000

    def call(self, method, params):
        if method == "eth_getCode":
            address = params[0].lower()
            return "0x60016000" if self.code_present.get(address, False) else "0x"
        if method == "eth_getLogs":
            query = params[0]
            address = query["address"].lower()
            count = self.launch_counts.get(address, 0)
            return [
                {"blockNumber": hex(9_900 + index)}
                for index in range(count)
            ]
        raise AssertionError(method)


class RobinhoodFactoryDiscoveryV0Tests(unittest.TestCase):
    def test_unique_recent_factory_is_selected(self):
        first, second = FACTORY_CANDIDATES_V0
        rpc = FakeRpc(
            launch_counts={first.address: 3, second.address: 0},
            code_present={first.address: True, second.address: True},
        )
        result = discover_factory_v0(
            rpc,
            token_launched_topic0="0x" + "aa" * 32,
            lookback_blocks=500,
        )
        self.assertEqual(result["classification"], "PASS_FACTORY_DISCOVERY_V0")
        self.assertEqual(result["selected_factory"], first.address)

    def test_multiple_recent_factories_hold_separate_strata(self):
        first, second = FACTORY_CANDIDATES_V0
        rpc = FakeRpc(
            launch_counts={first.address: 2, second.address: 1},
            code_present={first.address: True, second.address: True},
        )
        result = discover_factory_v0(
            rpc,
            token_launched_topic0="0x" + "aa" * 32,
            lookback_blocks=500,
        )
        self.assertEqual(result["classification"], "HOLD_MULTIPLE_ACTIVE_FACTORIES_V0")
        self.assertIsNone(result["selected_factory"])

    def test_override_requires_bytecode(self):
        address = "0x" + "12" * 20
        rpc = FakeRpc(code_present={address: False})
        result = discover_factory_v0(
            rpc,
            token_launched_topic0="0x" + "aa" * 32,
            override_address=address,
        )
        self.assertEqual(result["classification"], "FAIL_FACTORY_OVERRIDE_V0")


class RobinhoodCaptureAuditV0Tests(unittest.TestCase):
    def _launch(self):
        return PonsLaunchObservationV0(
            "0x" + "11" * 20,
            "0x" + "22" * 20,
            "0x" + "33" * 20,
            ZERO_ADDRESS,
            0,
            4_200_000_000_000_000_000,
            100,
            0,
            1,
            "0xlaunch",
            "0xblock100",
            1_000_000_000,
            1000,
        )

    def _trade(self, launch):
        return PonsTradeObservationV0(
            "BUY",
            launch.curve,
            "0x" + "44" * 20,
            "0x" + "44" * 20,
            1000,
            5000,
            20,
            10,
            101,
            0,
            2,
            "0xtrade",
            "0xblock101",
            1_200_000_000,
            1001,
        )

    def test_audit_replays_matured_snapshots_exactly(self):
        launch = self._launch()
        trade = self._trade(launch)
        snapshots = [
            build_snapshot_v0(
                launch=launch,
                trades=[trade],
                horizon_seconds=horizon,
                snapshot_observed_at_ns=launch.observed_at_ns + horizon * 1_000_000_000,
            ).to_dict()
            for horizon in (1, 5, 10, 30)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            report = {
                "feature_only": True,
                "economic_outcomes_opened": False,
                "selector_frozen": False,
                "transport_errors": [],
                "finished_wall_ns": launch.observed_at_ns + 31_000_000_000,
                "factory_discovery": {"classification": "PASS_FACTORY_DISCOVERY_V0"},
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            with (run_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": "launch", **launch.__dict__}) + "\n")
                handle.write(json.dumps({"kind": "trade", **trade.__dict__}) + "\n")
            with (run_dir / "snapshots.jsonl").open("w", encoding="utf-8") as handle:
                for snapshot in snapshots:
                    handle.write(json.dumps(snapshot) + "\n")
            result = audit_run(run_dir)
        self.assertEqual(result["classification"], "PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_AUDIT_V0")
        self.assertTrue(all(result["gates"].values()))
        self.assertEqual(result["replay_mismatches"], [])

    def test_audit_detects_block_hash_identity_conflict(self):
        launch = self._launch()
        duplicate = dict(launch.__dict__)
        duplicate["block_hash"] = "0xdifferent"
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            report = {
                "feature_only": True,
                "economic_outcomes_opened": False,
                "selector_frozen": False,
                "transport_errors": [],
                "finished_wall_ns": launch.observed_at_ns,
                "factory_discovery": {"classification": "PASS_FACTORY_DISCOVERY_V0"},
            }
            (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            with (run_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": "launch", **launch.__dict__}) + "\n")
                handle.write(json.dumps({"kind": "launch", **duplicate}) + "\n")
            (run_dir / "snapshots.jsonl").write_text("", encoding="utf-8")
            result = audit_run(run_dir)
        self.assertEqual(result["classification"], "FAIL_ROBINHOOD_LAUNCH_BURST_CAPTURE_AUDIT_V0")
        self.assertFalse(result["gates"]["block_hash_conflicts_zero"])


if __name__ == "__main__":
    unittest.main()
