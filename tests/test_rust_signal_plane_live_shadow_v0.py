from __future__ import annotations

import base64
from dataclasses import asdict, replace as _dataclass_replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import database
from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    AsyncPumpSwapIdentityPlane,
    _add_identity,
    _build_signal_record,
    _identity_source_for_evidence,
    _latency_summary_ns,
    _raw_ingress_prefilter,
    _raw_price_path_fields_from_row,
    _target_inputs_from_notification,
)
from benchmarks.carbon_decoder_parity_v1.parity import (
    PUMP_PROGRAM_ID,
    PUMP_TRADE_EVENT_DISCRIMINATOR,
    PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
    PUMPSWAP_PROGRAM_ID,
)
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import ADAPTED, adapt_carbon_pump_trade_v0
from src.market_observation_batch_v0 import (
    MarketTradeWriteV0,
    record_market_observations_batch_v0,
)
from src.market_observation_store import load_market_trades
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation
from benchmarks.market_first_live_discovery_v0.contracts import (
    identities_available_before_v0,
)


class RustSignalPlaneLiveShadowV0Tests(unittest.TestCase):
    def _notification(self, *, program_id: str, payload: bytes) -> dict:
        encoded = base64.b64encode(payload).decode("ascii")
        return {
            "err": None,
            "signature": "SIG",
            "slot": 1,
            "logs": [
                f"Program {program_id} invoke [1]",
                f"Program data: {encoded}",
                f"Program {program_id} success",
            ],
        }

    def test_prefilter_retains_pump_target_consumer_would_decode(self):
        normalized = self._notification(
            program_id=PUMP_PROGRAM_ID,
            payload=PUMP_TRADE_EVENT_DISCRIMINATOR + b"fixture",
        )
        items, _manifests, _stack_errors = _target_inputs_from_notification(
            normalized=normalized,
            received_wall_ns=10,
            seen_event_keys=set(),
        )
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(_raw_ingress_prefilter(normalized), "target_candidate")

    def test_prefilter_retains_pumpswap_target_consumer_would_decode(self):
        normalized = self._notification(
            program_id=PUMPSWAP_PROGRAM_ID,
            payload=PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"fixture",
        )
        items, _manifests, _stack_errors = _target_inputs_from_notification(
            normalized=normalized,
            received_wall_ns=10,
            seen_event_keys=set(),
        )
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(_raw_ingress_prefilter(normalized), "target_candidate")

    def test_prefilter_rejects_failed_transaction_even_with_target_logs(self):
        normalized = self._notification(
            program_id=PUMPSWAP_PROGRAM_ID,
            payload=PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"fixture",
        )
        normalized["err"] = {"InstructionError": [0, "Custom"]}
        items, _manifests, _stack_errors = _target_inputs_from_notification(
            normalized=normalized,
            received_wall_ns=10,
            seen_event_keys=set(),
        )
        self.assertEqual(items, [])
        self.assertEqual(_raw_ingress_prefilter(normalized), "failed_tx")

    def test_prefilter_rejects_logs_without_contextual_target(self):
        normalized = {
            "err": None,
            "signature": "SIG",
            "slot": 1,
            "logs": ["Program 11111111111111111111111111111111 success"],
        }
        items, _manifests, _stack_errors = _target_inputs_from_notification(
            normalized=normalized,
            received_wall_ns=10,
            seen_event_keys=set(),
        )
        self.assertEqual(items, [])
        self.assertEqual(_raw_ingress_prefilter(normalized), "no_target")

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
        # _build_signal_record's payload is a deliberately curated field
        # projection (parity-sensitive wire shape toward the Rust side), not
        # an automatic mirror of every MarketTradeObservation field. `slot`
        # (docs/bundle-bot-detection-v0-plumbing-scope-2026-10-07.md) and the
        # F1b price-path fields (docs/sig-fast-live-engine-wiring-v0-2026-10-09.md)
        # are intentionally not part of this shape -- the Rust trigger kernel
        # never needs them -- excluded here rather than silently asserting
        # they're absent.
        expected = asdict(observation)
        for field_name in (
            "slot",
            "base_amount_raw",
            "quote_amount_raw",
            "base_reserves_raw",
            "quote_reserves_raw",
        ):
            expected.pop(field_name, None)
        self.assertEqual(row["observation"], expected)
        self.assertEqual(row["sequence"], 7)
        self.assertEqual(row["kind"], "trade")

    def test_raw_price_path_fields_extracted_for_pump_trade(self):
        row = {
            "sol_amount_raw": 2_000_000_000,
            "token_amount_raw": 50_000_000,
            "virtual_quote_reserves_raw": 30_000_000_000,
        }
        fields = _raw_price_path_fields_from_row(row, event_type="pump_trade")
        self.assertEqual(
            fields,
            {
                "base_amount_raw": 50_000_000,
                "quote_amount_raw": 2_000_000_000,
                "base_reserves_raw": None,
                "quote_reserves_raw": 30_000_000_000,
            },
        )

    def test_raw_price_path_fields_extracted_for_pumpswap(self):
        row = {
            "base_amount_raw": 100,
            "quote_amount_raw": 700,
            "pool_base_token_reserves_raw": 500,
            "pool_quote_token_reserves_raw": 600,
        }
        for event_type in ("pumpswap_buy", "pumpswap_sell"):
            fields = _raw_price_path_fields_from_row(row, event_type=event_type)
            self.assertEqual(
                fields,
                {
                    "base_amount_raw": 100,
                    "quote_amount_raw": 700,
                    "base_reserves_raw": 500,
                    "quote_reserves_raw": 600,
                },
            )

    def test_raw_price_path_fields_unknown_event_type_is_empty(self):
        self.assertEqual(
            _raw_price_path_fields_from_row({"anything": 1}, event_type="pump_create"),
            {},
        )
        self.assertEqual(
            _raw_price_path_fields_from_row({"anything": 1}, event_type=None),
            {},
        )

    def test_live_adapter_chain_threads_price_path_fields_into_persisted_observation(self):
        """End-to-end: a synthetic Carbon-decoded pump_trade row, through the exact
        same adapter chain + field-threading live_shadow.py uses, persisted through
        the exact batch writer persist_signal_plane_research_batch actually calls
        (record_market_observations_batch_v0) -- confirms reserves really reach the
        database, not just the in-memory observation object."""

        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "sig-1:0:pump_trade",
            "signature": "sig-1",
            "slot": 999,
            "log_index": 0,
            "program_id": PUMP_PROGRAM_ID,
            "event_type": "pump_trade",
            "mint": "MINT",
            "side": "buy",
            "wallet": "WALLET",
            "timestamp": 1_000,
            "sol_amount_raw": 2_000_000_000,
            "token_amount_raw": 50_000_000,
            "quote_mint": "So11111111111111111111111111111111111111112",
            "quote_amount_raw": 2_000_000_000,
            "virtual_quote_reserves_raw": 30_000_000_000,
            "real_quote_reserves_raw": 29_000_000_000,
            "mayhem_mode": False,
        }

        matched = adapt_carbon_pump_trade_v0(row, observed_at=1_005)
        self.assertEqual(matched.status, ADAPTED)
        market_trade = adapt_carbon_matched_unit_to_market_trade_v0(row, matched)
        self.assertEqual(market_trade.status, ADAPTED)
        observation = market_trade.observation
        self.assertIsNotNone(observation)

        # Same injection the live loop performs (manifest["slot"], then the new fields).
        observation = _dataclass_replace(observation, slot=999)
        extra_fields = _raw_price_path_fields_from_row(row, event_type="pump_trade")
        observation = _dataclass_replace(observation, **extra_fields)

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "live_shadow_smoke.db"
            with patch.object(database, "settings", _dataclass_replace(database.settings, database_path=db_path)):
                result = record_market_observations_batch_v0(
                    (MarketTradeWriteV0("RUN", row["event_key"], "carbon_live_shadow_smoke", observation),)
                )
                self.assertEqual(result.inserted, 1)
                rows = load_market_trades(acquisition_run_key="RUN", token_mint="MINT")

        self.assertEqual(len(rows), 1)
        persisted = rows[0].observation
        self.assertEqual(persisted.slot, 999)
        self.assertEqual(persisted.base_amount_raw, 50_000_000)
        self.assertEqual(persisted.quote_amount_raw, 2_000_000_000)
        self.assertIsNone(persisted.base_reserves_raw)
        self.assertEqual(persisted.quote_reserves_raw, 30_000_000_000)

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
