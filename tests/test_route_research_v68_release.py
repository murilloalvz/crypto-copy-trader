from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import route_research_forward_cohort_v43 as v43
import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import route_research_v68_release as release
import unified_market_route_research_smoke_tailfix_v9 as tailfix_v9
from src import database


class V68ReleaseReadinessTests(unittest.TestCase):
    def test_release_parser_changes_only_writer_batch_defaults(self):
        base = release._parser_defaults(v43.build_parser())
        tuned = release._parser_defaults(
            release._release_v43_parser_factory(v43.build_parser)()
        )
        changed = {
            key: (base.get(key), tuned.get(key))
            for key in sorted(set(base) | set(tuned))
            if base.get(key) != tuned.get(key)
        }
        self.assertEqual(
            changed,
            {
                "pumpswap_writer_batch_size": (
                    32,
                    release.V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE,
                )
            },
        )
        self.assertEqual(
            tuned["pumpswap_writer_batch_max_wait_ms"],
            release.V68_RELEASE_PUMPSWAP_WRITER_BATCH_MAX_WAIT_MS,
        )

    def test_release_preserves_frozen_economic_contract(self):
        self.assertEqual(
            release._economic_contract(),
            release._EXPECTED_V68_ECONOMIC_CONTRACT,
        )

    def test_residue_audit_scans_every_table_with_acquisition_run_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v68-release-residue.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with database.connection() as conn:
                    conn.execute(
                        "CREATE TABLE old_observations(id INTEGER PRIMARY KEY, acquisition_run_key TEXT NOT NULL)"
                    )
                    conn.execute(
                        "CREATE TABLE unrelated(id INTEGER PRIMARY KEY, value TEXT)"
                    )
                    conn.execute(
                        "INSERT INTO old_observations(acquisition_run_key) VALUES (?)",
                        ("fresh-base-A",),
                    )
                    conn.execute(
                        "INSERT INTO old_observations(acquisition_run_key) VALUES (?)",
                        ("some-other-run",),
                    )

                residue = release._run_key_residue_counts(
                    ("fresh-base-A", "fresh-base-B")
                )

        self.assertEqual(residue["fresh-base-A"], {"old_observations": 1})
        self.assertEqual(residue["fresh-base-B"], {})
        self.assertIn("fresh-base-A[old_observations:1]", release._format_residue(residue))

    def test_release_main_installs_v9_and_batch64_then_restores(self):
        original_v68_main = v68.main
        original_build_parser = v43.build_parser
        original_smoke = v68.v54.run_smoke_v54
        original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
        original_argv = list(sys.argv)
        observed = {}

        def fake_v68_main() -> int:
            observed["smoke"] = v68.v54.run_smoke_v54
            observed["profile"] = v68.V68_VALIDATED_SYSTEMS_PROFILE
            observed["defaults"] = release._parser_defaults(v43.build_parser())
            observed["argv"] = list(sys.argv)
            return 0

        try:
            v68.main = fake_v68_main
            with patch.object(release, "print_readiness", return_value=True), patch.object(
                release, "print_provider_health", return_value=True
            ):
                sys.argv = ["route_research_v68_release.py", "--run-key", "unit-release"]
                result = release.main()
        finally:
            v68.main = original_v68_main
            sys.argv = original_argv

        self.assertEqual(result, 0)
        self.assertIs(observed["smoke"], tailfix_v9.run_smoke_tailfix_v9)
        self.assertEqual(observed["profile"], release.V68_RELEASE_SYSTEMS_PROFILE)
        self.assertEqual(
            observed["defaults"]["pumpswap_writer_batch_size"],
            release.V68_RELEASE_PUMPSWAP_WRITER_BATCH_SIZE,
        )
        self.assertEqual(observed["defaults"]["pumpswap_workers"], 256)
        self.assertEqual(observed["defaults"]["pumpswap_prepare_submitters"], 64)
        self.assertEqual(observed["defaults"]["pumpswap_prepare_executor_workers"], 32)
        self.assertIn("unit-release", observed["argv"])
        self.assertIs(v43.build_parser, original_build_parser)
        self.assertIs(v68.v54.run_smoke_v54, original_smoke)
        self.assertEqual(v68.V68_VALIDATED_SYSTEMS_PROFILE, original_profile)

    def test_release_restores_globals_when_v68_raises(self):
        original_v68_main = v68.main
        original_build_parser = v43.build_parser
        original_smoke = v68.v54.run_smoke_v54
        original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
        original_argv = list(sys.argv)

        def boom() -> int:
            raise RuntimeError("boom")

        try:
            v68.main = boom
            with patch.object(release, "print_readiness", return_value=True), patch.object(
                release, "print_provider_health", return_value=True
            ):
                sys.argv = ["route_research_v68_release.py", "--run-key", "unit-release"]
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    release.main()
        finally:
            v68.main = original_v68_main
            sys.argv = original_argv

        self.assertIs(v43.build_parser, original_build_parser)
        self.assertIs(v68.v54.run_smoke_v54, original_smoke)
        self.assertEqual(v68.V68_VALIDATED_SYSTEMS_PROFILE, original_profile)

    def test_provider_health_failure_prevents_v68_main(self):
        original_argv = list(sys.argv)
        try:
            with patch.object(release, "print_readiness", return_value=True), patch.object(
                release, "print_provider_health", return_value=False
            ), patch.object(
                v68, "main", side_effect=AssertionError("must not run")
            ):
                sys.argv = [
                    "route_research_v68_release.py",
                    "--run-key",
                    "unit-release",
                ]
                self.assertEqual(release.main(), 2)
        finally:
            sys.argv = original_argv

    def test_preflight_only_never_calls_v68_main(self):
        original_argv = list(sys.argv)
        try:
            with patch.object(release, "print_readiness", return_value=True), patch.object(
                release, "print_provider_health", return_value=True
            ), patch.object(
                v68, "main", side_effect=AssertionError("must not run")
            ):
                sys.argv = [
                    "route_research_v68_release.py",
                    "--run-key",
                    "unit-release",
                    "--preflight-only",
                ]
                self.assertEqual(release.main(), 0)
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    unittest.main()
