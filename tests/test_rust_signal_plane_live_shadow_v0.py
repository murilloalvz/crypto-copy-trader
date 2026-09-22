from __future__ import annotations

from dataclasses import asdict
import unittest

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    _add_identity,
    _build_signal_record,
    _latency_summary_ns,
    _target_inputs_from_notification,
)
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


class RustSignalPlaneLiveShadowV0Tests(unittest.TestCase):
    def test_latency_summary_uses_milliseconds(self):
        summary = _latency_summary_ns(
            [1_000_000, 2_000_000, 3_000_000, 4_000_000]
        )
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["max_ms"], 4.0)
        self.assertGreaterEqual(summary["p95_ms"], 3.0)

    def test_identity_bucket_is_deduplicated_and_ordered(self):
        buckets = {}
        later = PumpSwapPoolIdentityObservation(
            pool="POOL",
            base_mint="BASE",
            quote_mint="QUOTE",
            observed_wall_ns=20,
            observed_slot=2,
            evidence_key="later",
            source="test",
        )
        earlier = PumpSwapPoolIdentityObservation(
            pool="POOL",
            base_mint="BASE",
            quote_mint="QUOTE",
            observed_wall_ns=10,
            observed_slot=1,
            evidence_key="earlier",
            source="test",
        )
        _add_identity(buckets, later)
        _add_identity(buckets, earlier)
        _add_identity(buckets, earlier)
        self.assertEqual(
            [item.evidence_key for item in buckets["POOL"]],
            ["earlier", "later"],
        )

    def test_signal_record_preserves_exact_observation(self):
        observation = MarketTradeObservation(
            token_mint="MINT",
            side="buy",
            chain_time=10,
            observed_at=11,
            wallet_address="W",
            notional_usd=None,
            price_usd=None,
            venue="pump",
            transaction_key="TX",
        )
        row = _build_signal_record(
            sequence=7,
            kind="trade",
            observation=observation,
            source_received_wall_ns=12_000_000_000,
            canonical_ready_wall_ns=12_100_000_000,
        )
        self.assertEqual(row["observation"], asdict(observation))
        self.assertEqual(row["sequence"], 7)
        self.assertEqual(row["kind"], "trade")

    def test_failed_transaction_does_not_reach_decoder(self):
        items, manifests, stack_errors = _target_inputs_from_notification(
            normalized={
                "err": {"InstructionError": [0, "Custom"]},
                "signature": "SIG",
                "slot": 1,
                "logs": [],
            },
            received_wall_ns=10,
            seen_event_keys=set(),
        )
        self.assertEqual(items, [])
        self.assertEqual(manifests, {})
        self.assertEqual(stack_errors, 0)


if __name__ == "__main__":
    unittest.main()
