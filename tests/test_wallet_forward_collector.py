import unittest
from unittest.mock import Mock, patch

from src.wallet_forward_collector import capture_new_wallet_actions


class WalletForwardCollectorTests(unittest.TestCase):
    def test_records_only_transactions_not_in_bootstrap_signature_set(self):
        txs = [
            {
                "signature": "known",
                "block_time": 100,
                "status": "success",
                "kind": "swap",
                "dex": "Jupiter v6",
                "token_mint": "TOKEN-A",
                "token_change": 10,
            },
            {
                "signature": "new-buy",
                "block_time": 200,
                "status": "success",
                "kind": "swap",
                "dex": "PumpSwap",
                "token_mint": "TOKEN-B",
                "token_change": 5,
            },
        ]
        recorder = Mock(return_value=True)

        with (
            patch("src.wallet_forward_collector.rows", return_value=txs),
            patch(
                "src.wallet_forward_collector.record_wallet_forward_observation",
                recorder,
            ),
        ):
            result = capture_new_wallet_actions(
                "wallet",
                known_signatures={"known"},
                observed_at=250,
            )

        self.assertEqual(result.new_transaction_count, 1)
        self.assertEqual(result.recorded_action_count, 1)
        self.assertEqual(result.ignored_new_transaction_count, 0)
        observation = recorder.call_args.args[0]
        self.assertEqual(observation.side, "buy")
        self.assertEqual(observation.chain_time, 200)
        self.assertEqual(observation.observed_at, 250)
        self.assertEqual(result.known_signatures, frozenset({"known", "new-buy"}))

    def test_ignores_non_swap_or_unusable_new_rows(self):
        txs = [
            {
                "signature": "failed",
                "block_time": 200,
                "status": "failed",
                "kind": "swap",
                "dex": "PumpSwap",
                "token_mint": "TOKEN",
                "token_change": 5,
            },
            {
                "signature": "activity",
                "block_time": 201,
                "status": "success",
                "kind": "dex_activity",
                "dex": "PumpSwap",
                "token_mint": "TOKEN",
                "token_change": 5,
            },
        ]
        recorder = Mock(return_value=True)

        with (
            patch("src.wallet_forward_collector.rows", return_value=txs),
            patch(
                "src.wallet_forward_collector.record_wallet_forward_observation",
                recorder,
            ),
        ):
            result = capture_new_wallet_actions(
                "wallet",
                known_signatures=set(),
                observed_at=250,
            )

        self.assertEqual(result.recorded_action_count, 0)
        self.assertEqual(result.ignored_new_transaction_count, 2)
        recorder.assert_not_called()

    def test_sell_side_is_derived_from_negative_token_delta(self):
        txs = [
            {
                "signature": "sell",
                "block_time": 200,
                "status": "success",
                "kind": "swap",
                "dex": "Jupiter v6",
                "token_mint": "TOKEN",
                "token_change": -7,
            }
        ]
        recorder = Mock(return_value=True)

        with (
            patch("src.wallet_forward_collector.rows", return_value=txs),
            patch(
                "src.wallet_forward_collector.record_wallet_forward_observation",
                recorder,
            ),
        ):
            capture_new_wallet_actions(
                "wallet",
                known_signatures=set(),
                observed_at=250,
            )

        self.assertEqual(recorder.call_args.args[0].side, "sell")


if __name__ == "__main__":
    unittest.main()
