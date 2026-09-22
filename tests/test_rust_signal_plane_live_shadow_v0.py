from __future__ import annotations

from dataclasses import asdict
import unittest

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    AsyncPumpSwapIdentityPlane,
    _add_identity,
    _build_signal_record,
    _identity_source_for_evidence,
    _latency_summary_ns,
    _target_inputs_from_notification,
)
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation
from benchmarks.market_first_live_discovery_v0.contracts import (
    identities_available_before_v0,
)


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

    def test_identity_source_attribution_uses_exact_evidence_key(self):
        identities = (
            PumpSwapPoolIdentityObservation(
                pool="POOL",
                base_mint="BASE",
                quote_mint="QUOTE",
                observed_wall_ns=10,
                observed_slot=1,
                evidence_key="bootstrap",
                source="bootstrap_rpc",
            ),
            PumpSwapPoolIdentityObservation(
                pool="POOL",
                base_mint="BASE",
                quote_mint="QUOTE",
                observed_wall_ns=20,
                observed_slot=2,
                evidence_key="live-create",
                source="carbon_pumpswap_create_pool_event_v0",
            ),
        )
        self.assertEqual(
            _identity_source_for_evidence(identities, "live-create"),
            "carbon_pumpswap_create_pool_event_v0",
        )
        self.assertIsNone(
            _identity_source_for_evidence(identities, "missing")
        )

    def test_async_identity_plane_enqueue_is_deduplicated_without_rpc(self):
        plane = AsyncPumpSwapIdentityPlane(
            identities_by_pool={},
            rpc_url="https://example.invalid",
            queue_size=2,
        )
        self.assertTrue(plane.enqueue("POOL_A"))
        self.assertFalse(plane.enqueue("POOL_A"))
        self.assertEqual(plane.counters["enqueued"], 1)
        self.assertEqual(plane.counters["deduplicated"], 1)

    def test_async_identity_never_backfills_earlier_event(self):
        identity = PumpSwapPoolIdentityObservation(
            pool="POOL",
            base_mint="BASE",
            quote_mint="QUOTE",
            observed_wall_ns=200,
            observed_slot=2,
            evidence_key="async",
            source="async_solana_getMultipleAccounts_v0",
        )
        before = identities_available_before_v0(
            (identity,),
            pool="POOL",
            event_wall_ns=199,
        )
        after = identities_available_before_v0(
            (identity,),
            pool="POOL",
            event_wall_ns=200,
        )
        self.assertEqual(before, ())
        self.assertEqual(after, (identity,))

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
