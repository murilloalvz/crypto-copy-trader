from __future__ import annotations

from types import SimpleNamespace
import unittest

from benchmarks.launch_burst_sniper_v1.runtime_enrichment import (
    ENRICHMENT_VERSION,
    envelope_with_sniper_wallet_v1,
    feature_snapshot_with_sniper_v1,
)
from benchmarks.launch_burst_shadow_v0.run import AdaptedEnvelope
from src.carbon_matched_unit_adapter import ADAPTED


def _row(*, event_key: str, side: str, amount: int, wallet: str, tx: str, wall_ns: int):
    return AdaptedEnvelope(
        token_mint="Mint111",
        venue="pump",
        side=side,
        chain_time=100,
        observed_wall_ns=wall_ns,
        event_key=event_key,
        market_surface_key="pump:Mint111",
        quote_asset_key="SOL",
        quote_amount_raw=amount,
        quote_reserve_raw=1000,
        reserve_kind="virtual_quote",
        wallet_key=wallet,
        transaction_key=tx,
    )


class LaunchBurstSniperRuntimeEnrichmentV1Tests(unittest.TestCase):
    def test_canonical_pump_wallet_field_is_recovered(self):
        observation = SimpleNamespace(
            token_mint="Mint111",
            venue="pump",
            side="buy",
            chain_time=100,
            evidence_key="event-1",
            market_surface_key="pump:Mint111",
            quote_asset_key="SOL",
            quote_amount_raw=50,
            quote_reserve_raw=1000,
            reserve_kind="virtual_quote",
        )
        result = SimpleNamespace(status=ADAPTED, observation=observation)
        envelope = envelope_with_sniper_wallet_v1(
            result,
            {"wallet": "WalletA", "signature": "TxA"},
            1_000_000_000,
        )
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope.wallet_key, "WalletA")
        self.assertEqual(envelope.transaction_key, "TxA")

    def test_feature_snapshot_measures_wallet_distribution_causally(self):
        rows = [
            _row(event_key="e1", side="buy", amount=50, wallet="A", tx="t1", wall_ns=1_100_000_000),
            _row(event_key="e2", side="buy", amount=10, wallet="A", tx="t2", wall_ns=1_200_000_000),
            _row(event_key="e3", side="buy", amount=40, wallet="B", tx="t3", wall_ns=1_300_000_000),
            _row(event_key="e4", side="buy", amount=20, wallet="B", tx="t4", wall_ns=1_400_000_000),
            _row(event_key="e5", side="buy", amount=30, wallet="C", tx="t5", wall_ns=1_500_000_000),
        ]
        features = feature_snapshot_with_sniper_v1(rows, anchor_wall_ns=1_000_000_000)
        self.assertEqual(features["sniper_feature_enrichment_version"], ENRICHMENT_VERSION)
        self.assertEqual(features["event_count"], 5)
        self.assertEqual(features["unique_wallet_count"], 3)
        self.assertEqual(features["unique_buy_wallet_count"], 3)
        self.assertEqual(features["wallet_identity_coverage_pct"], 100.0)
        self.assertAlmostEqual(features["repeat_wallet_event_share_pct"], 40.0)
        self.assertAlmostEqual(features["top_wallet_event_share_pct"], 40.0)
        self.assertAlmostEqual(features["top_wallet_gross_flow_share_pct"], 40.0)
        self.assertAlmostEqual(features["wallet_gross_flow_coverage_pct"], 100.0)
        self.assertAlmostEqual(features["directional_flow_efficiency"], 1.0)
        self.assertEqual(features["unique_transaction_count"], 5)
        self.assertAlmostEqual(features["transaction_identity_coverage_pct"], 100.0)

    def test_directional_efficiency_penalizes_two_way_churn(self):
        rows = [
            _row(event_key="e1", side="buy", amount=100, wallet="A", tx="t1", wall_ns=1_100_000_000),
            _row(event_key="e2", side="sell", amount=80, wallet="B", tx="t2", wall_ns=1_200_000_000),
        ]
        features = feature_snapshot_with_sniper_v1(rows, anchor_wall_ns=1_000_000_000)
        self.assertAlmostEqual(features["signed_flow_over_event_reserve"], 0.02)
        self.assertAlmostEqual(features["gross_turnover_over_event_reserve"], 0.18)
        self.assertAlmostEqual(features["directional_flow_efficiency"], 1.0 / 9.0)


if __name__ == "__main__":
    unittest.main()
