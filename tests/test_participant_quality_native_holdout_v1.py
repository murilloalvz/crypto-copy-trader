from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import participant_quality_native_holdout_v1 as holdout


def _rows(
    cohort: str,
    *,
    favorable: bool,
) -> list[dict]:
    rows = []
    for index in range(10):
        high_feature = -50.0 + index
        low_feature = -80.0 - index
        if favorable:
            high_return = 10.0 + index
            low_return = -70.0 - (2.0 * index)
        else:
            high_return = -70.0 - (2.0 * index)
            low_return = 10.0 + index
        rows.append(
            {
                "run_key": cohort,
                "episode_key": f"{cohort}-H-{index}",
                "feature_value": high_feature,
                "group": holdout.group_for_feature(high_feature),
                "outcome_900_return_pct": high_return,
            }
        )
        rows.append(
            {
                "run_key": cohort,
                "episode_key": f"{cohort}-L-{index}",
                "feature_value": low_feature,
                "group": holdout.group_for_feature(low_feature),
                "outcome_900_return_pct": low_return,
            }
        )
    return rows


class ParticipantQualityNativeHoldoutV1Tests(unittest.TestCase):
    def test_frozen_protocol_constants(self):
        self.assertEqual(
            holdout.VERSION,
            "participant_quality_native_holdout_v1_preregistered",
        )
        self.assertEqual(holdout.HOLDOUT_RUN_COUNT, 2)
        self.assertEqual(holdout.PRIMARY_HORIZON_SECONDS, 900)
        self.assertEqual(holdout.FAVORABLE_GROUP, "HIGH")
        self.assertEqual(
            holdout.FROZEN_CUTOFF,
            -65.65233776856643,
        )
        self.assertEqual(
            holdout.CATASTROPHIC_RETURN_PCT,
            -80.0,
        )

    def test_group_rule_is_strict_high_and_inclusive_low(self):
        self.assertEqual(
            holdout.group_for_feature(
                holdout.FROZEN_CUTOFF + 0.000001
            ),
            "HIGH",
        )
        self.assertEqual(
            holdout.group_for_feature(
                holdout.FROZEN_CUTOFF
            ),
            "LOW",
        )
        self.assertIsNone(holdout.group_for_feature(None))

    def test_synthetic_favorable_holdout_keeps_candidate(self):
        report = holdout.evaluate_rows(
            {
                "H1": _rows("H1", favorable=True),
                "H2": _rows("H2", favorable=True),
            }
        )
        self.assertEqual(
            report["classification"],
            (
                "KEEP_NATIVE_PARTICIPANT_QUALITY_"
                "SELECTION_EDGE_CANDIDATE"
            ),
        )
        self.assertTrue(all(report["support_checks"].values()))
        self.assertTrue(all(report["effect_checks"].values()))

    def test_synthetic_reversed_holdout_kills_candidate(self):
        report = holdout.evaluate_rows(
            {
                "H1": _rows("H1", favorable=False),
                "H2": _rows("H2", favorable=False),
            }
        )
        self.assertEqual(
            report["classification"],
            (
                "KILL_NATIVE_PARTICIPANT_QUALITY_"
                "SELECTION_EDGE_CANDIDATE"
            ),
        )
        self.assertTrue(all(report["support_checks"].values()))
        self.assertFalse(all(report["effect_checks"].values()))

    def test_insufficient_support_is_inconclusive(self):
        report = holdout.evaluate_rows(
            {
                "H1": _rows("H1", favorable=True)[:6],
                "H2": _rows("H2", favorable=True)[:6],
            }
        )
        self.assertEqual(
            report["classification"],
            (
                "INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_"
                "HOLDOUT_SUPPORT"
            ),
        )

    def test_memory_report_validation_freezes_lineage(self):
        payload = {
            "version": holdout.MEMORY_VERSION,
            "classification": (
                holdout.MEMORY_REPORT_CLASSIFICATION
            ),
            "run_keys": list(holdout.MEMORY_RUN_KEYS),
            "coverage_audit": {
                "outcome_blind_median_cutoff": (
                    holdout.FROZEN_CUTOFF
                ),
                "favorable_direction": "HIGH",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            validated = holdout._validate_memory_report(path)
        self.assertEqual(
            tuple(validated["run_keys"]),
            holdout.MEMORY_RUN_KEYS,
        )


if __name__ == "__main__":
    unittest.main()
