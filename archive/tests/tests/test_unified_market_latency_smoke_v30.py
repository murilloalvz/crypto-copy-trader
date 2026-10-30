import unittest

from unified_market_latency_smoke_v30 import (
    MIN_DEFAULT_IO_WORKERS,
    MIN_PUMP_PREPARE_WORKERS,
    MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
    MIN_PUMPSWAP_PREPARE_SUBMITTERS,
    MIN_PUMPSWAP_WORKERS,
    validate_capacity_profile,
)


class UnifiedMarketLatencySmokeV30Tests(unittest.TestCase):
    def test_measured_profile_is_accepted(self):
        validate_capacity_profile(
            pumpswap_workers=MIN_PUMPSWAP_WORKERS,
            pump_prepare_workers=MIN_PUMP_PREPARE_WORKERS,
            pumpswap_prepare_submitters=MIN_PUMPSWAP_PREPARE_SUBMITTERS,
            pumpswap_prepare_executor_workers=MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
            default_io_workers=MIN_DEFAULT_IO_WORKERS,
        )

    def test_underprovisioned_dimension_is_rejected(self):
        dimensions = {
            "pumpswap_workers": MIN_PUMPSWAP_WORKERS,
            "pump_prepare_workers": MIN_PUMP_PREPARE_WORKERS,
            "pumpswap_prepare_submitters": MIN_PUMPSWAP_PREPARE_SUBMITTERS,
            "pumpswap_prepare_executor_workers": MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
            "default_io_workers": MIN_DEFAULT_IO_WORKERS,
        }
        for name, minimum in tuple(dimensions.items()):
            with self.subTest(name=name):
                values = dict(dimensions)
                values[name] = minimum - 1
                with self.assertRaises(ValueError):
                    validate_capacity_profile(**values)

    def test_submitters_cannot_be_below_executor_workers(self):
        with self.assertRaises(ValueError):
            validate_capacity_profile(
                pumpswap_workers=MIN_PUMPSWAP_WORKERS,
                pump_prepare_workers=MIN_PUMP_PREPARE_WORKERS,
                pumpswap_prepare_submitters=64,
                pumpswap_prepare_executor_workers=65,
                default_io_workers=MIN_DEFAULT_IO_WORKERS,
            )


if __name__ == "__main__":
    unittest.main()
