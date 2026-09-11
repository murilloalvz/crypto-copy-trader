from __future__ import annotations

import unittest

from benchmarks.pumpswap_identity_bootstrap_v0.bootstrap import (
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    RPC_BATCH_SIZE,
    WARMUP_SECONDS,
    _account_inputs_from_rpc_result,
    _chunks,
    classify_bootstrap,
)
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


class PumpSwapIdentityBootstrapV0Tests(unittest.TestCase):
    def test_operational_warmup_is_fixed_and_rpc_batches_respect_protocol_limit(self) -> None:
        self.assertEqual(WARMUP_SECONDS, 60)
        self.assertEqual(RPC_BATCH_SIZE, 100)
        values = tuple(f"pool-{index}" for index in range(205))
        batches = tuple(_chunks(values))
        self.assertEqual(tuple(map(len, batches)), (100, 100, 5))
        self.assertEqual(tuple(item for batch in batches for item in batch), values)

    def test_rpc_response_preserves_context_slot_and_local_receive_clock(self) -> None:
        rows, counters = _account_inputs_from_rpc_result(
            pools=("pool-a", "pool-b"),
            payload={
                "result": {
                    "context": {"slot": 1234},
                    "value": [
                        {
                            "owner": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
                            "data": ["AQID", "base64"],
                        },
                        None,
                    ],
                }
            },
            observed_wall_ns=9_000_000_123,
        )
        self.assertEqual(counters["requested"], 2)
        self.assertEqual(counters["account_present"], 1)
        self.assertEqual(counters["account_missing"], 1)
        self.assertEqual(counters["invalid_account_shape"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool"], "pool-a")
        self.assertEqual(rows[0]["observed_slot"], 1234)
        self.assertEqual(rows[0]["observed_wall_ns"], 9_000_000_123)
        self.assertEqual(rows[0]["data_base64"], "AQID")

    def test_rpc_response_fails_closed_on_cardinality_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "cardinality"):
            _account_inputs_from_rpc_result(
                pools=("pool-a", "pool-b"),
                payload={"result": {"context": {"slot": 1}, "value": [None]}},
                observed_wall_ns=1,
            )

    def test_identity_observation_never_backfills_an_earlier_trade(self) -> None:
        identity = PumpSwapPoolIdentityObservation(
            pool="pool-a",
            base_mint="base-a",
            quote_mint="quote-a",
            observed_wall_ns=2_000,
            observed_slot=99,
            evidence_key="rpc:99:pool-a",
            source="test",
        )
        self.assertFalse(identity.is_available_by_wall_ns(1_999))
        self.assertTrue(identity.is_available_by_wall_ns(2_000))
        self.assertTrue(identity.is_available_by_wall_ns(2_001))

    def test_bootstrap_pass_requires_every_operational_gate(self) -> None:
        self.assertEqual(
            classify_bootstrap({"gates": {"one": True, "two": True}}),
            PASS_CLASSIFICATION,
        )
        self.assertEqual(
            classify_bootstrap({"gates": {"one": True, "two": False}}),
            FAIL_CLASSIFICATION,
        )
        self.assertEqual(classify_bootstrap({"gates": {}}), FAIL_CLASSIFICATION)


if __name__ == "__main__":
    unittest.main()
