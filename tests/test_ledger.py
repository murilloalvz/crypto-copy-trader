from src.services import _consume_fifo


def test_fifo_consumes_oldest_lot_first():
    lots = [[2.0, 10.0], [3.0, 20.0]]
    quantity, cost = _consume_fifo(lots, 4.0)
    assert quantity == 4.0
    assert cost == 60.0
    assert lots == [[1.0, 20.0]]

