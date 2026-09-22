from __future__ import annotations

import unittest

from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketMovementFeatures,
    MarketMovementTrigger,
    MarketTradeObservation,
)
from src.signal_plane_episode_bridge_v0 import (
    SIGNAL_PLANE_EPISODE_BRIDGE_VERSION,
    build_signal_plane_episode_assignment,
)


def _features(token_mint: str, *, as_of: int, chain_as_of: int) -> MarketMovementFeatures:
    return MarketMovementFeatures(
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
        fast_window_seconds=30,
        baseline_horizon_seconds=300,
        fast_event_count=6,
        baseline_event_count=3,
        fast_buy_count=5,
        fast_sell_count=1,
        fast_unique_wallet_count=5,
        fast_unique_transaction_count=6,
        wallet_identity_coverage_pct=100.0,
        transaction_identity_coverage_pct=100.0,
        notional_coverage_pct=100.0,
        price_coverage_pct=100.0,
        fast_event_rate_per_second=0.2,
        baseline_event_rate_per_second=3 / 270,
        activity_acceleration_ratio=18.0,
        signed_notional_imbalance_pct=50.0,
        count_imbalance_pct=66.6666666667,
        direction="upward_pressure",
        first_price_usd=1.0,
        last_price_usd=1.1,
        fast_return_pct=10.0,
        median_observation_lag_seconds=None,
        max_observation_lag_seconds=None,
        venues=("pump",),
        market_age_seconds=20,
        data_quality_flags=(),
    )


def _trigger(
    token_mint: str = "TOKEN",
    *,
    as_of: int = 120,
    method_version: str = MARKET_OPPORTUNITY_RADAR_VERSION,
) -> MarketMovementTrigger:
    return MarketMovementTrigger(
        token_mint=token_mint,
        as_of=as_of,
        method_version=method_version,
        trigger_kind="fresh_market_burst",
        direction="upward_pressure",
        features=_features(token_mint, as_of=as_of, chain_as_of=119),
    )


class SignalPlaneEpisodeBridgeV0Tests(unittest.TestCase):
    def test_version_is_frozen(self):
        self.assertEqual(
            SIGNAL_PLANE_EPISODE_BRIDGE_VERSION,
            "signal_plane_episode_bridge_v0",
        )

    def test_pump_preserves_historical_trigger_identity(self):
        assignment = build_signal_plane_episode_assignment(
            trigger=_trigger(),
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=119,
                observed_at=120,
                wallet_address="wallet",
                notional_usd=10.0,
                price_usd=1.1,
                venue="pump",
                transaction_key="pump-signature",
            ),
        )
        self.assertEqual(
            assignment.trigger_key,
            "market-radar:pump:pump-signature:TOKEN",
        )
        self.assertEqual(assignment.venue, "pump_bonding_curve")
        self.assertEqual(assignment.chain_time, 119)
        self.assertEqual(assignment.observed_at, 120)

    def test_pumpswap_preserves_historical_trigger_identity(self):
        assignment = build_signal_plane_episode_assignment(
            trigger=_trigger(),
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=119,
                observed_at=120,
                wallet_address="wallet",
                notional_usd=10.0,
                price_usd=1.1,
                venue="pumpswap",
                transaction_key="pumpswap-signature",
            ),
        )
        self.assertEqual(
            assignment.trigger_key,
            "market-radar:pumpswap-v3:pumpswap-signature:TOKEN",
        )
        self.assertEqual(assignment.venue, "pump_swap")

    def test_trigger_token_must_match_observation(self):
        with self.assertRaisesRegex(ValueError, "token_mint"):
            build_signal_plane_episode_assignment(
                trigger=_trigger("OTHER"),
                observation=MarketTradeObservation(
                    token_mint="TOKEN",
                    side="buy",
                    chain_time=119,
                    observed_at=120,
                    venue="pump",
                    transaction_key="signature",
                ),
            )

    def test_trigger_clock_must_match_observation_availability(self):
        with self.assertRaisesRegex(ValueError, "as_of"):
            build_signal_plane_episode_assignment(
                trigger=_trigger(as_of=121),
                observation=MarketTradeObservation(
                    token_mint="TOKEN",
                    side="buy",
                    chain_time=119,
                    observed_at=120,
                    venue="pump",
                    transaction_key="signature",
                ),
            )

    def test_transaction_identity_is_required(self):
        with self.assertRaisesRegex(ValueError, "transaction_key"):
            build_signal_plane_episode_assignment(
                trigger=_trigger(),
                observation=MarketTradeObservation(
                    token_mint="TOKEN",
                    side="buy",
                    chain_time=119,
                    observed_at=120,
                    venue="pump",
                    transaction_key=None,
                ),
            )

    def test_radar_version_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "method_version"):
            build_signal_plane_episode_assignment(
                trigger=_trigger(method_version="unexpected-radar"),
                observation=MarketTradeObservation(
                    token_mint="TOKEN",
                    side="buy",
                    chain_time=119,
                    observed_at=120,
                    venue="pump",
                    transaction_key="signature",
                ),
            )


if __name__ == "__main__":
    unittest.main()
