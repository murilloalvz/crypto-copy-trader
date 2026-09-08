import unittest

from src.market_opportunity_radar import MarketTradeObservation
from src.temporal_flow_structure_research import build_temporal_flow_structure_window


def _trade(
    *,
    chain_time: int,
    observed_at: int | None = None,
    side: str = "buy",
    token: str = "TOKEN",
    wallet: str = "W",
) -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint=token,
        side=side,
        chain_time=chain_time,
        observed_at=chain_time if observed_at is None else observed_at,
        wallet_address=wallet,
        transaction_key=f"{token}-{side}-{chain_time}-{wallet}",
    )


class TemporalFlowStructureResearchTests(unittest.TestCase):
    def test_persistent_activity_spans_all_subwindows(self):
        result = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=105,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=[
                _trade(chain_time=45),
                _trade(chain_time=60),
                _trade(chain_time=75),
                _trade(chain_time=90),
            ],
        )
        self.assertEqual(result.subwindow_event_counts, (1, 1, 1, 1))
        self.assertEqual(result.active_subwindow_count, 4)
        self.assertEqual(result.active_subwindow_share_pct, 100.0)
        self.assertEqual(result.max_subwindow_event_share_pct, 25.0)
        self.assertAlmostEqual(result.temporal_event_hhi or 0.0, 0.25)
        self.assertEqual(result.early_half_event_count, 2)
        self.assertEqual(result.late_half_event_count, 2)
        self.assertEqual(result.late_event_share_pct, 50.0)
        self.assertEqual(result.late_to_early_event_ratio, 1.0)

    def test_single_burst_has_high_temporal_concentration(self):
        result = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=100,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=[
                _trade(chain_time=91, wallet="A"),
                _trade(chain_time=92, wallet="B"),
                _trade(chain_time=93, wallet="C"),
                _trade(chain_time=94, wallet="D"),
            ],
        )
        self.assertEqual(result.subwindow_event_counts, (0, 0, 0, 4))
        self.assertEqual(result.active_subwindow_count, 1)
        self.assertEqual(result.max_subwindow_event_share_pct, 100.0)
        self.assertAlmostEqual(result.temporal_event_hhi or 0.0, 1.0)
        self.assertEqual(result.late_event_share_pct, 100.0)
        self.assertIsNone(result.late_to_early_event_ratio)
        self.assertIn("all_market_events_in_single_subwindow", result.data_quality_flags)
        self.assertIn(
            "late_to_early_ratio_unavailable_zero_early_events",
            result.data_quality_flags,
        )

    def test_market_anchor_excludes_post_t0_events_even_if_known_by_decision(self):
        result = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=110,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=[
                _trade(chain_time=90, observed_at=95),
                _trade(chain_time=105, observed_at=106),
            ],
        )
        self.assertEqual(result.market_event_count, 1)

    def test_unknown_by_decision_event_is_excluded(self):
        result = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=105,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=[
                _trade(chain_time=90, observed_at=106),
                _trade(chain_time=95, observed_at=100),
            ],
        )
        self.assertEqual(result.market_event_count, 1)

    def test_buy_and_sell_subwindows_are_kept_separate(self):
        result = build_temporal_flow_structure_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            knowledge_as_of=100,
            lookback_seconds=60,
            subwindow_seconds=15,
            observations=[
                _trade(chain_time=50, side="buy"),
                _trade(chain_time=70, side="sell"),
                _trade(chain_time=95, side="buy"),
            ],
        )
        self.assertEqual(result.buy_event_count, 2)
        self.assertEqual(result.sell_event_count, 1)
        self.assertEqual(sum(result.subwindow_buy_counts), 2)
        self.assertEqual(sum(result.subwindow_sell_counts), 1)
        self.assertEqual(result.buy_active_subwindow_count, 2)

    def test_invalid_subwindow_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "divisible"):
            build_temporal_flow_structure_window(
                token_mint="TOKEN",
                market_anchor_time=100,
                knowledge_as_of=100,
                lookback_seconds=60,
                subwindow_seconds=16,
                observations=[],
            )

    def test_anchor_after_knowledge_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "market_anchor_time"):
            build_temporal_flow_structure_window(
                token_mint="TOKEN",
                market_anchor_time=101,
                knowledge_as_of=100,
                lookback_seconds=60,
                subwindow_seconds=15,
                observations=[],
            )


if __name__ == "__main__":
    unittest.main()
