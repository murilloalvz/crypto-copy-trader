import unittest

from benchmarks.robinhood_sequencer_shadow_v0.reconcile import (
    reconcile_pons_intents_to_rpc_events_v0,
    resolve_chain_tx_hash_v0,
    resolve_pons_intent_v0,
)
from src.robinhood_nitro_feed_v0 import NitroSignedTxIntentV0


TX_HASH = "0x" + "ab" * 32


class FakeKeccakRpc:
    def __init__(self):
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method != "web3_sha3":
            raise AssertionError(method)
        self.last_raw = params[0]
        return TX_HASH


def intent(*, to=None, selector="0x12345678", observed=1_000_000_000):
    return NitroSignedTxIntentV0(
        sequence_number=123,
        batch_path=(0,),
        tx_envelope_type="legacy",
        tx_type_byte=None,
        to=to or ("0x" + "11" * 20),
        value_raw=7,
        calldata_raw=bytes.fromhex(selector[2:]),
        calldata_selector=selector,
        raw_tx=bytes.fromhex("c101"),
        raw_tx_sha256="ff" * 32,
        l1_timestamp=100,
        feed_block_hash="0x" + "22" * 32,
        observed_at_ns=observed,
    )


class RobinhoodSequencerReconcileV0Tests(unittest.TestCase):
    def test_hash_resolution_uses_raw_signed_tx_and_keeps_feed_clock(self):
        rpc = FakeKeccakRpc()
        source = intent(observed=5_000_000_000)
        row = resolve_chain_tx_hash_v0(rpc, source)
        self.assertEqual(row["chain_tx_hash"], TX_HASH)
        self.assertEqual(rpc.calls[0], ("web3_sha3", ["0xc101"]))
        self.assertEqual(row["feed_observed_at_ns"], 5_000_000_000)
        self.assertGreaterEqual(row["hash_resolved_at_ns"], row["hash_resolution_started_at_ns"])
        self.assertFalse(row["execution_confirmed"])
        self.assertFalse(row["economic_outcomes_opened"])

    def test_resolve_pons_buy_intent_combines_classification_and_canonical_hash(self):
        rpc = FakeKeccakRpc()
        curve = "0x" + "11" * 20
        row = resolve_pons_intent_v0(
            rpc,
            intent(to=curve, selector="0x12345678"),
            factory_address="0x" + "99" * 20,
            known_curve_addresses=(curve,),
            buy_selector="0x12345678",
            sell_selector="0x90abcdef",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["intent_kind"], "PONS_CURVE_BUY_INTENT")
        self.assertEqual(row["target"], curve)
        self.assertEqual(row["chain_tx_hash"], TX_HASH)

    def test_exact_buy_execution_match_measures_feed_to_rpc_delta(self):
        resolved = [{
            "sequence_number": 1,
            "batch_path": [],
            "chain_tx_hash": TX_HASH,
            "intent_kind": "PONS_CURVE_BUY_INTENT",
            "target": "0x" + "11" * 20,
            "feed_observed_at_ns": 1_000_000_000,
        }]
        events = [{
            "kind": "trade",
            "side": "BUY",
            "curve": "0x" + "11" * 20,
            "transaction_hash": TX_HASH,
            "observed_at_ns": 1_250_000_000,
        }]
        report = reconcile_pons_intents_to_rpc_events_v0(resolved, events)
        self.assertEqual(report["tx_hash_match_count"], 1)
        self.assertEqual(report["semantic_match_count"], 1)
        self.assertEqual(report["rows"][0]["status"], "MATCHED_EXECUTED_PONS_EVENT")
        self.assertEqual(report["rows"][0]["feed_to_rpc_observation_delta_ms"], 250.0)
        self.assertEqual(report["matched_feed_to_rpc_delta_ms"]["p50"], 250.0)
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["trade_returns_computed"])

    def test_no_tracked_event_is_unknown_not_failed_trade(self):
        resolved = [{
            "sequence_number": 1,
            "batch_path": [],
            "chain_tx_hash": TX_HASH,
            "intent_kind": "PONS_CURVE_BUY_INTENT",
            "target": "0x" + "11" * 20,
            "feed_observed_at_ns": 1_000_000_000,
        }]
        report = reconcile_pons_intents_to_rpc_events_v0(resolved, [])
        self.assertEqual(report["unresolved_count"], 1)
        self.assertEqual(report["rows"][0]["status"], "NO_TRACKED_RPC_EVENT_OBSERVED")
        self.assertFalse(report["rows"][0]["tx_hash_matched"])
        self.assertIsNone(report["rows"][0]["feed_to_rpc_observation_delta_ms"])

    def test_hash_match_with_wrong_semantics_is_not_exact_event_parity(self):
        resolved = [{
            "sequence_number": 1,
            "batch_path": [],
            "chain_tx_hash": TX_HASH,
            "intent_kind": "PONS_CURVE_BUY_INTENT",
            "target": "0x" + "11" * 20,
            "feed_observed_at_ns": 1_000_000_000,
        }]
        events = [{
            "kind": "trade",
            "side": "SELL",
            "curve": "0x" + "11" * 20,
            "transaction_hash": TX_HASH,
            "observed_at_ns": 1_100_000_000,
        }]
        report = reconcile_pons_intents_to_rpc_events_v0(resolved, events)
        self.assertEqual(report["tx_hash_match_count"], 1)
        self.assertEqual(report["semantic_match_count"], 0)
        self.assertEqual(
            report["rows"][0]["status"],
            "TX_HASH_MATCH_SEMANTIC_EVENT_NOT_MATCHED",
        )
        self.assertEqual(report["matched_feed_to_rpc_delta_ms"]["n"], 0)

    def test_negative_delta_is_preserved_for_backfill_diagnostics(self):
        resolved = [{
            "sequence_number": 1,
            "batch_path": [],
            "chain_tx_hash": TX_HASH,
            "intent_kind": "PONS_CURVE_SELL_INTENT",
            "target": "0x" + "11" * 20,
            "feed_observed_at_ns": 2_000_000_000,
        }]
        events = [{
            "kind": "trade",
            "side": "SELL",
            "curve": "0x" + "11" * 20,
            "transaction_hash": TX_HASH,
            "observed_at_ns": 1_500_000_000,
        }]
        report = reconcile_pons_intents_to_rpc_events_v0(resolved, events)
        self.assertEqual(report["rows"][0]["feed_to_rpc_observation_delta_ms"], -500.0)


if __name__ == "__main__":
    unittest.main()
