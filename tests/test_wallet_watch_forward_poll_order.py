import unittest

from wallet_watch_forward import _rotated_poll_order


class WalletWatchForwardPollOrderTests(unittest.TestCase):
    def test_three_wallet_order_rotates_each_cycle(self):
        addresses = ["A", "B", "C"]

        self.assertEqual(_rotated_poll_order(addresses, 1), ["A", "B", "C"])
        self.assertEqual(_rotated_poll_order(addresses, 2), ["B", "C", "A"])
        self.assertEqual(_rotated_poll_order(addresses, 3), ["C", "A", "B"])
        self.assertEqual(_rotated_poll_order(addresses, 4), ["A", "B", "C"])

    def test_rotation_does_not_mutate_original_cohort(self):
        addresses = ["A", "B", "C"]
        result = _rotated_poll_order(addresses, 2)

        self.assertEqual(addresses, ["A", "B", "C"])
        self.assertEqual(result, ["B", "C", "A"])

    def test_empty_cohort_is_stable_and_cycle_must_be_positive(self):
        self.assertEqual(_rotated_poll_order([], 1), [])
        with self.assertRaises(ValueError):
            _rotated_poll_order(["A"], 0)


if __name__ == "__main__":
    unittest.main()
