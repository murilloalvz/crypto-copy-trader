from __future__ import annotations

from types import SimpleNamespace
import unittest

from participant_quality_native_memory_v0 import (
    MEMORY_HORIZON_SECONDS,
    MEMORY_RUN_COUNT,
    _median_of_wallet_medians,
)


class ParticipantQualityNativeMemoryV0Tests(unittest.TestCase):
    def test_memory_contract_is_frozen(self):
        self.assertEqual(MEMORY_RUN_COUNT, 4)
        self.assertEqual(MEMORY_HORIZON_SECONDS, 900)

    def test_feature_is_median_of_wallet_medians(self):
        rows = [
            SimpleNamespace(
                wallet_address="A",
                executable_quote_return_pct=10.0,
            ),
            SimpleNamespace(
                wallet_address="A",
                executable_quote_return_pct=20.0,
            ),
            SimpleNamespace(
                wallet_address="B",
                executable_quote_return_pct=-20.0,
            ),
            SimpleNamespace(
                wallet_address="B",
                executable_quote_return_pct=-10.0,
            ),
        ]
        self.assertEqual(
            _median_of_wallet_medians(rows),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
