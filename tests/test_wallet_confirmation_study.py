import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection, initialize_database
from src.wallet_confirmation_placebo import ConfirmationPolicy, WalletCohort
from src.wallet_confirmation_study import (
    ConfirmationStudySpec,
    activate_confirmation_study,
    close_confirmation_study,
    load_confirmation_study,
    register_confirmation_study,
)


def spec(**changes) -> ConfirmationStudySpec:
    item = ConfirmationStudySpec(
        study_key="study-v1",
        frozen_at=1_000,
        preperiod_cutoff=900,
        starts_at=1_100,
        ends_at=2_000,
        target=WalletCohort("target", ("A", "B"), "target"),
        placebos=(
            WalletCohort("placebo_1", ("C", "D"), "placebo"),
            WalletCohort("placebo_2", ("E", "F"), "placebo"),
        ),
        policy=ConfirmationPolicy(window_seconds=300, min_unique_buy_wallets=2),
        horizons_minutes=(5, 15, 60),
        notes="pre-registered before outcomes",
    )
    return replace(item, **changes)


class ConfirmationStudyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(
            database,
            "settings",
            SimpleNamespace(database_path=Path(self.directory.name) / "study.db"),
        )
        self.patch.start()
        initialize_database()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def test_register_is_idempotent_but_frozen_spec_is_immutable(self):
        first = register_confirmation_study(spec())
        second = register_confirmation_study(spec())

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.status, "FROZEN")
        with self.assertRaises(ValueError):
            register_confirmation_study(spec(notes="changed after freeze"))

    def test_registry_persists_queryable_cohort_membership(self):
        register_confirmation_study(spec())

        stored = load_confirmation_study("study-v1")
        with connection() as conn:
            rows = conn.execute(
                """SELECT cohort_name, cohort_role, wallet_address
                FROM wallet_confirmation_study_cohorts
                ORDER BY cohort_name, wallet_address"""
            ).fetchall()

        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "FROZEN")
        self.assertEqual(stored.spec.target.addresses, ("A", "B"))
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["cohort_role"], "placebo")

    def test_study_cannot_start_before_frozen_boundary(self):
        register_confirmation_study(spec())

        with self.assertRaises(ValueError):
            activate_confirmation_study("study-v1", now=1_099)
        self.assertTrue(activate_confirmation_study("study-v1", now=1_100))
        self.assertFalse(activate_confirmation_study("study-v1", now=1_101))
        self.assertEqual(load_confirmation_study("study-v1").status, "ACTIVE")

    def test_active_study_can_close_but_not_reopen(self):
        register_confirmation_study(spec())
        activate_confirmation_study("study-v1", now=1_100)

        self.assertTrue(close_confirmation_study("study-v1", now=1_500))
        self.assertFalse(close_confirmation_study("study-v1", now=1_600))
        stored = load_confirmation_study("study-v1")
        self.assertEqual(stored.status, "CLOSED")
        self.assertEqual(stored.closed_at, 1_500)
        with self.assertRaises(ValueError):
            activate_confirmation_study("study-v1", now=1_700)

    def test_invalid_timing_and_confirmation_threshold_fail_closed(self):
        with self.assertRaises(ValueError):
            spec(preperiod_cutoff=1_001)
        with self.assertRaises(ValueError):
            spec(frozen_at=1_101)
        with self.assertRaises(ValueError):
            spec(ends_at=1_100)
        with self.assertRaises(ValueError):
            spec(
                policy=ConfirmationPolicy(
                    window_seconds=300,
                    min_unique_buy_wallets=3,
                )
            )

    def test_cohorts_are_validated_before_any_study_is_persisted(self):
        with self.assertRaises(ValueError):
            spec(
                placebos=(
                    WalletCohort("overlap", ("B", "C"), "placebo"),
                )
            )
        with connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wallet_confirmation_studies'"
            ).fetchall()
        # Validation happens while creating the spec, before registration touches the registry.
        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
