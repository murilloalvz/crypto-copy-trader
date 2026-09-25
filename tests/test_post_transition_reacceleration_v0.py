from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.post_transition_reacceleration_v0.offline_replay import (
    PASS,
    build_state_from_fixture,
    run_fixture,
)
from src import database
from src.market_observation_store import (
    load_known_market_lifecycle,
    record_market_lifecycle,
)
from src.market_opportunity_radar import MarketLifecycleObservation
from src.post_transition_reacceleration_v0 import (
    PostTransitionResearchState,
)
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_stream import (
    PumpSwapCreatePoolEvent,
    PumpSwapTradeEvent,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "benchmarks"
    / "post_transition_reacceleration_v0"
    / "fixture.synthetic.json"
)


def _fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _event_from_row(row: dict) -> PumpSwapTradeEvent:
    return PumpSwapTradeEvent(
        side=str(row["side"]),
        pool=str(row["pool"]),
        user=str(row["user"]),
        timestamp=int(row["timestamp"]),
        base_amount_raw=int(row["base_amount_raw"]),
        quote_amount_raw=int(row["quote_amount_raw"]),
    )


class PostTransitionReaccelerationV0Tests(unittest.TestCase):
    def test_synthetic_fixture_reaches_structural_reacceleration_without_economics(self):
        report = run_fixture(FIXTURE)
        self.assertEqual(report["classification"], PASS)
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["provider_calls_used"])
        self.assertTrue(report["pump_origin_confirmed"])
        self.assertTrue(report["structural_candidate_seen"])
        final = report["final_snapshot"]
        self.assertTrue(final["pullback_observed"])
        self.assertTrue(final["structural_reacceleration_candidate"])
        self.assertAlmostEqual(
            final["running_trough_return_from_reference_pct"],
            -16.0,
            places=9,
        )
        self.assertAlmostEqual(
            final["current_return_from_reference_pct"],
            -4.0,
            places=9,
        )
        self.assertGreater(
            final["dynamics"]["signed_reference_flow_rate_delta_per_s"],
            0.0,
        )
        self.assertFalse(final["provider_quote_used"])
        self.assertFalse(final["future_outcome_used"])
        self.assertFalse(final["future_extrema_used"])

    def test_future_events_do_not_change_past_snapshot(self):
        payload = _fixture_payload()
        early_payload = dict(payload)
        early_payload["trades"] = payload["trades"][:3]

        early_state = build_state_from_fixture(early_payload)
        full_state = build_state_from_fixture(payload)

        expected = asdict(early_state.snapshot(as_of_observed_at=1008))
        replayed = asdict(full_state.snapshot(as_of_observed_at=1008))
        self.assertEqual(replayed, expected)
        self.assertEqual(replayed["trade_count_available"], 3)
        self.assertFalse(replayed["structural_reacceleration_candidate"])

    def test_same_second_future_arrival_cannot_leak_into_earlier_snapshot(self):
        create = PumpSwapCreatePoolEvent(
            pool="POOL",
            creator="CREATOR",
            base_mint="TOKEN",
            quote_mint=WSOL_MINT,
            base_mint_decimals=6,
            quote_mint_decimals=9,
            timestamp=1000,
        )
        state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=1001,
        )
        first = PumpSwapTradeEvent(
            side="buy",
            pool="POOL",
            user="wallet-a",
            timestamp=1002,
            base_amount_raw=100_000_000,
            quote_amount_raw=1_000_000_000,
        )
        second = PumpSwapTradeEvent(
            side="sell",
            pool="POOL",
            user="wallet-b",
            timestamp=1002,
            base_amount_raw=100_000_000,
            quote_amount_raw=800_000_000,
        )
        state.ingest_trade(
            first,
            observed_at=1002,
            event_key="e1",
            transaction_key="tx1",
            arrival_index=0,
        )
        before = asdict(
            state.snapshot(
                as_of_observed_at=1002,
                max_arrival_index=0,
            )
        )
        state.ingest_trade(
            second,
            observed_at=1002,
            event_key="e2",
            transaction_key="tx2",
            arrival_index=1,
        )
        replayed = asdict(
            state.snapshot(
                as_of_observed_at=1002,
                max_arrival_index=0,
            )
        )
        after = state.snapshot(
            as_of_observed_at=1002,
            max_arrival_index=1,
        )
        self.assertEqual(before, replayed)
        self.assertEqual(before["trade_count_available"], 1)
        self.assertEqual(after.trade_count_available, 2)
        self.assertAlmostEqual(
            after.running_trough_return_from_reference_pct or 0.0,
            -20.0,
            places=9,
        )

    def test_replay_order_is_deterministic_by_causal_availability(self):
        payload = _fixture_payload()
        canonical = build_state_from_fixture(payload)

        transition = payload["transition"]
        birth = payload["pump_birth"]
        create = PumpSwapCreatePoolEvent(
            pool=transition["pool"],
            creator=transition["creator"],
            base_mint=transition["base_mint"],
            quote_mint=transition["quote_mint"],
            base_mint_decimals=transition["base_mint_decimals"],
            quote_mint_decimals=transition["quote_mint_decimals"],
            timestamp=transition["timestamp"],
        )
        reversed_state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=transition["observed_at"],
            pump_birth_market_started_at=birth["market_started_at"],
            pump_birth_observed_at=birth["observed_at"],
        )
        for row in reversed(payload["trades"]):
            reversed_state.ingest_trade(
                _event_from_row(row),
                observed_at=row["observed_at"],
                event_key=row["event_key"],
                transaction_key=row["transaction_key"],
                arrival_index=row["arrival_index"],
            )

        self.assertEqual(
            asdict(canonical.snapshot(as_of_observed_at=1020)),
            asdict(reversed_state.snapshot(as_of_observed_at=1020)),
        )

    def test_reversed_pool_orientation_normalizes_token_price_and_side(self):
        create = PumpSwapCreatePoolEvent(
            pool="POOL",
            creator="CREATOR",
            base_mint=WSOL_MINT,
            quote_mint="TOKEN",
            base_mint_decimals=9,
            quote_mint_decimals=6,
            timestamp=1000,
        )
        state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=1001,
        )
        state.ingest_trade(
            PumpSwapTradeEvent(
                side="buy",
                pool="POOL",
                user="wallet",
                timestamp=1002,
                base_amount_raw=1_000_000_000,
                quote_amount_raw=100_000_000,
            ),
            observed_at=1002,
            event_key="e1",
            transaction_key="tx1",
        )
        snap = state.snapshot(as_of_observed_at=1002)
        self.assertFalse(state.identity.opportunity_is_base)
        self.assertEqual(state.identity.opportunity_mint, "TOKEN")
        self.assertAlmostEqual(snap.reference_price or 0.0, 0.01, places=12)
        rows = state._available_rows(1002)
        self.assertEqual(rows[0].normalized_side, "sell")

    def test_conflicting_duplicate_event_fails_closed(self):
        payload = _fixture_payload()
        transition = payload["transition"]
        create = PumpSwapCreatePoolEvent(
            pool=transition["pool"],
            creator=transition["creator"],
            base_mint=transition["base_mint"],
            quote_mint=transition["quote_mint"],
            base_mint_decimals=transition["base_mint_decimals"],
            quote_mint_decimals=transition["quote_mint_decimals"],
            timestamp=transition["timestamp"],
        )
        state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=transition["observed_at"],
        )
        row = payload["trades"][0]
        event = _event_from_row(row)
        self.assertTrue(
            state.ingest_trade(
                event,
                observed_at=row["observed_at"],
                event_key="same",
                transaction_key="tx",
            )
        )
        self.assertFalse(
            state.ingest_trade(
                event,
                observed_at=row["observed_at"],
                event_key="same",
                transaction_key="tx",
            )
        )
        changed = PumpSwapTradeEvent(
            side=event.side,
            pool=event.pool,
            user=event.user,
            timestamp=event.timestamp,
            base_amount_raw=event.base_amount_raw,
            quote_amount_raw=event.quote_amount_raw + 1,
        )
        with self.assertRaisesRegex(ValueError, "conflicting replay"):
            state.ingest_trade(
                changed,
                observed_at=row["observed_at"],
                event_key="same",
                transaction_key="tx",
            )

    def test_partial_pump_birth_lineage_is_rejected(self):
        create = PumpSwapCreatePoolEvent(
            pool="POOL",
            creator="CREATOR",
            base_mint="TOKEN",
            quote_mint=WSOL_MINT,
            base_mint_decimals=6,
            quote_mint_decimals=9,
            timestamp=1000,
        )
        with self.assertRaisesRegex(ValueError, "requires both"):
            PostTransitionResearchState.from_create_event(
                create,
                observed_at=1001,
                pump_birth_market_started_at=900,
                pump_birth_observed_at=None,
            )

    def test_trade_before_transition_or_wrong_pool_is_rejected(self):
        create = PumpSwapCreatePoolEvent(
            pool="POOL",
            creator="CREATOR",
            base_mint="TOKEN",
            quote_mint=WSOL_MINT,
            base_mint_decimals=6,
            quote_mint_decimals=9,
            timestamp=1000,
        )
        state = PostTransitionResearchState.from_create_event(
            create,
            observed_at=1001,
        )
        with self.assertRaisesRegex(ValueError, "precedes transition"):
            state.ingest_trade(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="POOL",
                    user="wallet",
                    timestamp=999,
                    base_amount_raw=1_000_000,
                    quote_amount_raw=1_000_000,
                ),
                observed_at=1002,
                event_key="old",
                transaction_key="tx-old",
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            state.ingest_trade(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="OTHER",
                    user="wallet",
                    timestamp=1002,
                    base_amount_raw=1_000_000,
                    quote_amount_raw=1_000_000,
                ),
                observed_at=1002,
                event_key="other",
                transaction_key="tx-other",
            )

    def test_historical_pump_birth_lookup_is_causal_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.db"
            with patch.object(
                database,
                "settings",
                SimpleNamespace(database_path=path),
            ):
                record_market_lifecycle(
                    acquisition_run_key="old-a",
                    event_key="pump-create-a",
                    source_provider="pump",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=100,
                        observed_at=105,
                        venue="pump_bonding_curve",
                    ),
                )
                record_market_lifecycle(
                    acquisition_run_key="old-b",
                    event_key="pump-create-b",
                    source_provider="pump-replay",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=100,
                        observed_at=110,
                        venue="pump_bonding_curve",
                    ),
                )
                known = load_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=150,
                    venue="pump_bonding_curve",
                )
                self.assertIsNotNone(known)
                assert known is not None
                self.assertEqual(known.observation.market_started_at, 100)
                self.assertEqual(known.observation.observed_at, 105)

                record_market_lifecycle(
                    acquisition_run_key="future-conflict",
                    event_key="pump-create-conflict",
                    source_provider="bad",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=101,
                        observed_at=200,
                        venue="pump_bonding_curve",
                    ),
                )
                still_known = load_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=150,
                    venue="pump_bonding_curve",
                )
                self.assertIsNotNone(still_known)
                ambiguous = load_known_market_lifecycle(
                    token_mint="TOKEN",
                    as_of=250,
                    venue="pump_bonding_curve",
                )
                self.assertIsNone(ambiguous)


if __name__ == "__main__":
    unittest.main()
