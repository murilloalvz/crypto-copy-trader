import unittest

from src.wallet_strategy_lab import build_wallet_strategy_fingerprint
from src.wallet_strategy_readiness import (
    assess_wallet_strategy_readiness,
    summarize_wallet_strategy_readiness,
)


def _swap(token: str, at: int, change: float) -> dict:
    return {
        "kind": "swap",
        "status": "success",
        "token_mint": token,
        "token_change": change,
        "block_time": at,
        "dex": "PumpSwap",
    }


def _ready_fingerprint(address: str):
    swaps = []
    for index in range(12):
        buy_at = index * 2 * 86_400
        swaps.extend(
            [
                _swap(f"T{index}", buy_at, 100),
                _swap(f"T{index}", buy_at + 12 * 3_600, -100),
            ]
        )
    return build_wallet_strategy_fingerprint(address, swaps)


class WalletStrategyReadinessTests(unittest.TestCase):
    def test_ready_fingerprint_moves_to_forward_and_causal_review(self):
        result = assess_wallet_strategy_readiness(_ready_fingerprint("ready"))

        self.assertTrue(result.evidence_ready)
        self.assertEqual(result.stage, "DESCRIPTIVE_READY")
        self.assertEqual(result.blockers, ())
        self.assertIn("FORWARD_WATCH", result.next_actions)
        self.assertIn("CAUSAL_CONTEXT_REVIEW", result.next_actions)

    def test_low_roundtrip_sample_requests_sequence_backfill(self):
        swaps = []
        for index in range(12):
            buy_at = index * 86_400
            swaps.append(_swap(f"T{index}", buy_at, 100))
            if index < 4:
                swaps.append(_swap(f"T{index}", buy_at + 3_600, -100))
        fingerprint = build_wallet_strategy_fingerprint("sequence-gap", swaps)

        result = assess_wallet_strategy_readiness(fingerprint)

        self.assertFalse(result.evidence_ready)
        self.assertIn("roundtrip_coverage_below_50", result.blockers)
        self.assertIn("SELECTIVE_BACKFILL_SEQUENCE", result.next_actions)
        self.assertIn("FORWARD_WATCH_OBSERVABILITY", result.next_actions)

    def test_narrow_bursty_wallet_is_not_promoted_by_many_swaps(self):
        swaps = []
        for token_index in range(5):
            token = f"T{token_index}"
            base = token_index * 500
            for buy_index in range(6):
                swaps.append(_swap(token, base + buy_index * 10, 10))
            swaps.append(_swap(token, base + 120, -60))
        fingerprint = build_wallet_strategy_fingerprint("bursty", swaps)

        result = assess_wallet_strategy_readiness(fingerprint)

        self.assertGreaterEqual(fingerprint.swap_count, 20)
        self.assertFalse(result.evidence_ready)
        self.assertIn("token_sample_below_10", result.blockers)
        self.assertIn("SELECTIVE_BACKFILL_BREADTH", result.next_actions)
        self.assertIn("FORWARD_WATCH_OBSERVABILITY", result.next_actions)

    def test_summary_counts_blockers_and_actions(self):
        ready = assess_wallet_strategy_readiness(_ready_fingerprint("ready"))
        empty = assess_wallet_strategy_readiness(
            build_wallet_strategy_fingerprint("empty", [])
        )

        summary = summarize_wallet_strategy_readiness([ready, empty])

        self.assertEqual(summary.wallet_count, 2)
        self.assertEqual(summary.evidence_ready_count, 1)
        self.assertEqual(summary.stages["DESCRIPTIVE_READY"], 1)
        self.assertGreater(summary.blockers["sample_grade_insufficient"], 0)
        self.assertEqual(summary.next_actions["FORWARD_WATCH"], 1)


if __name__ == "__main__":
    unittest.main()
