from __future__ import annotations

import unittest

import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import route_research_prospective_flow60_buy_share_holdout_v68_tailfix_v9 as wrapper


class V68TailfixV9WrapperTests(unittest.TestCase):
    def test_wrapper_installs_v9_path_and_restores_globals(self):
        original_smoke = v68.v54.run_smoke_v54
        original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
        original_main = v68.main
        observed = {}

        def fake_main():
            observed["smoke"] = v68.v54.run_smoke_v54
            observed["profile"] = v68.V68_VALIDATED_SYSTEMS_PROFILE
            return 0

        v68.main = fake_main
        try:
            result = wrapper.main()
        finally:
            v68.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["smoke"], wrapper.tailfix_v9.run_smoke_tailfix_v9)
        self.assertEqual(observed["profile"], wrapper.TAILFIX_V9_SYSTEMS_PROFILE)
        self.assertIs(v68.v54.run_smoke_v54, original_smoke)
        self.assertEqual(v68.V68_VALIDATED_SYSTEMS_PROFILE, original_profile)

    def test_wrapper_restores_globals_on_exception(self):
        original_smoke = v68.v54.run_smoke_v54
        original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
        original_main = v68.main

        def fake_main():
            raise RuntimeError("boom")

        v68.main = fake_main
        try:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                wrapper.main()
        finally:
            v68.main = original_main

        self.assertIs(v68.v54.run_smoke_v54, original_smoke)
        self.assertEqual(v68.V68_VALIDATED_SYSTEMS_PROFILE, original_profile)

    def test_wrapper_does_not_modify_frozen_v68_economic_constants(self):
        before = (
            v68.V68_FEATURE_NAME,
            v68.V68_LOW_MAX,
            v68.V68_MID_MAX,
            v68.V68_FAVORABLE_GROUP,
            v68.V68_OPPOSITE_GROUP,
            v68.V68_PRIMARY_HORIZON_SECONDS,
            v68.V68_MIN_GROUP_SUPPORT_PER_SUBCOHORT,
        )
        self.assertEqual(
            before,
            (
                "flow60_buy_share_pct",
                57.1429,
                65.7143,
                "LOW",
                "HIGH",
                900,
                5,
            ),
        )


if __name__ == "__main__":
    unittest.main()
