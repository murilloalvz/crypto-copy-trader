import unittest

from src.services import _consume_fifo


class LedgerTests(unittest.TestCase):
    def test_fifo_consumes_oldest_lot_first(self):
        lots = [[2.0, 10.0], [3.0, 20.0]]
        quantity, cost = _consume_fifo(lots, 4.0)

        self.assertEqual(quantity, 4.0)
        self.assertEqual(cost, 60.0)
        self.assertEqual(lots, [[1.0, 20.0]])
