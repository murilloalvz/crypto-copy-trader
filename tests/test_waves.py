import unittest

from src.discovery.models import WalletTier
from src.waves import (
    ConvergencePolicy,
    WalletTradeSignal,
    detect_wallet_convergence,
)

NOW_MS = 1_800_000_000_000


def trade(wallet, token="TOKEN", *, seconds_ago=30, side="buy", tier=WalletTier.APPROVED):
    return WalletTradeSignal(
        wallet=wallet,
        token=token,
        occurred_at_ms=NOW_MS - seconds_ago * 1_000,
        side=side,
        tier=tier,
        candidate_score=85,
        copyability_score=70,
        amount_usd=25,
    )


class WaveConvergenceTests(unittest.TestCase):
    def test_approved_and_observed_wallet_create_candidate_together(self):
        events = [
            trade("wallet-a", tier=WalletTier.APPROVED),
            trade("wallet-b", tier=WalletTier.OBSERVE),
        ]

        result = detect_wallet_convergence(events, now_ms=NOW_MS)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].unique_wallets, 2)
        self.assertEqual(result[0].approved_wallets, 1)
        self.assertEqual(result[0].observed_wallets, 1)
        self.assertEqual(result[0].signal_weight, 1.5)

    def test_single_wallet_never_creates_wave_candidate(self):
        events = [trade("wallet-a"), trade("wallet-a", seconds_ago=10)]

        self.assertEqual(detect_wallet_convergence(events, now_ms=NOW_MS), ())

    def test_three_observed_wallets_can_form_collective_signal(self):
        events = [
            trade("wallet-a", tier=WalletTier.OBSERVE),
            trade("wallet-b", tier=WalletTier.OBSERVE),
            trade("wallet-c", tier=WalletTier.OBSERVE),
        ]

        result = detect_wallet_convergence(events, now_ms=NOW_MS)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].signal_weight, 1.5)

    def test_sell_rejected_wallet_and_expired_buy_do_not_count(self):
        events = [
            trade("wallet-a", side="sell"),
            trade("wallet-b", tier=WalletTier.REJECTED),
            trade("wallet-c", seconds_ago=301),
            trade("wallet-d"),
        ]

        self.assertEqual(detect_wallet_convergence(events, now_ms=NOW_MS), ())

    def test_policy_cannot_allow_one_wallet(self):
        with self.assertRaisesRegex(ValueError, "pelo menos 2"):
            detect_wallet_convergence(
                [trade("wallet-a")],
                now_ms=NOW_MS,
                policy=ConvergencePolicy(min_unique_wallets=1),
            )


if __name__ == "__main__":
    unittest.main()
