import unittest
from types import SimpleNamespace

from unified_market_latency_smoke_v25 import _prepared_has_trigger


class UnifiedMarketLatencyV25Tests(unittest.TestCase):
    def test_no_trigger_prepared_work_does_not_require_serial_commit(self):
        prepared = SimpleNamespace(
            tokens=(
                SimpleNamespace(trigger=None),
                SimpleNamespace(trigger=None),
            )
        )
        self.assertFalse(_prepared_has_trigger(prepared))

    def test_any_trigger_requires_serial_commit(self):
        prepared = SimpleNamespace(
            tokens=(
                SimpleNamespace(trigger=None),
                SimpleNamespace(trigger=object()),
            )
        )
        self.assertTrue(_prepared_has_trigger(prepared))

    def test_empty_prepared_work_does_not_require_serial_commit(self):
        self.assertFalse(_prepared_has_trigger(SimpleNamespace(tokens=())))


if __name__ == "__main__":
    unittest.main()
