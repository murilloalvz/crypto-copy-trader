from __future__ import annotations

import unittest

from src.sqlite_write_admission import (
    RESOLUTION_PRIORITY,
    reset_sqlite_write_admission_metrics,
    sqlite_write_admission,
    sqlite_write_admission_snapshot,
)
from unified_market_route_research_smoke_tailfix_v3 import (
    _begin_resolution_admission_accounting_v3,
    _validate_resolution_admission_accounting_v3,
)


class TailfixV3ResolutionAccountingTests(unittest.TestCase):
    def setUp(self):
        reset_sqlite_write_admission_metrics()

    def tearDown(self):
        reset_sqlite_write_admission_metrics()

    def test_v68_sequential_subcohort_reset_starts_new_accounting_epoch(self):
        # Subcohort A leaves one acquisition in the shared diagnostic counter.
        with sqlite_write_admission(RESOLUTION_PRIORITY):
            pass
        previous_subcohort = sqlite_write_admission_snapshot()
        self.assertEqual(previous_subcohort.resolution_acquisitions, 1)

        # Subcohort B starts a new V3 accounting epoch. This models V28's nested reset without
        # sleeping or changing admission behavior.
        run_before = _begin_resolution_admission_accounting_v3()
        self.assertEqual(run_before.resolution_acquisitions, 0)
        with sqlite_write_admission(RESOLUTION_PRIORITY):
            pass
        run_after = sqlite_write_admission_snapshot()

        _validate_resolution_admission_accounting_v3(
            before_resolution_acquisitions=run_before.resolution_acquisitions,
            after_resolution_acquisitions=run_after.resolution_acquisitions,
            mapping_sync_admitted=1,
            mapping_sync_inflight=0,
        )
        self.assertEqual(run_after.resolution_acquisitions, 1)

    def test_old_cross_epoch_delta_is_rejected_with_live_values(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"local_admitted=1 .*global_observed_delta=-2 .*population=durable_pool_mapping_resolution_admissions",
        ):
            _validate_resolution_admission_accounting_v3(
                before_resolution_acquisitions=3,
                after_resolution_acquisitions=1,
                mapping_sync_admitted=1,
                mapping_sync_inflight=0,
            )

    def test_inflight_tolerance_is_preserved(self):
        _validate_resolution_admission_accounting_v3(
            before_resolution_acquisitions=0,
            after_resolution_acquisitions=2,
            mapping_sync_admitted=1,
            mapping_sync_inflight=1,
        )


if __name__ == "__main__":
    unittest.main()
