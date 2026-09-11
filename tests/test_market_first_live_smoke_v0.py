import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.collect import COVERAGE_CLASSIFICATION
from benchmarks.market_first_live_smoke_v0.run import (
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    SMOKE_DURATION_SECONDS,
    _build_identity,
    _canonical_rows_in_receive_order,
    _coverage_artifact,
    _observed_at_from_wall_ns,
    _parser,
    _prepare_t0_for_episode,
    classify_operational_smoke,
)
from src import database
from src.market_episode_research_snapshot_store import (
    load_market_episode_research_snapshot_record_v0,
)
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import MARKET_OPPORTUNITY_RADAR_VERSION, MarketTradeObservation
from src.opportunity_forward_outcome_store import (
    complete_opportunity_forward_outcome,
    load_opportunity_forward_outcomes,
)


class MarketFirstLiveSmokeV0Tests(unittest.TestCase):
    def _passing_report(self) -> dict[str, object]:
        identity = _build_identity(started_at=2_000)
        return {
            "identity": identity,
            "acquisition": {
                "valid_operational_shadow": True,
                "stop_reason": "duration_elapsed",
            },
            "reducer": {"valid_for_carbon_decode": True},
            "decoder": {"footer_accounting_valid": True},
            "pipeline": {
                "market_trade_adapted_events": 1,
                "kernel_trade_events_ingested": 1,
                "kernel_triggers_emitted": 0,
                "first_trigger_episodes": 0,
                "t0_snapshots_persisted": 0,
                "persistence_errors": [],
                "t0_errors": [],
                "semantic_errors": [],
            },
            "coverage": _coverage_artifact(
                acquisition_run_key=str(identity["acquisition_run_key"])
            ),
            "clean_shutdown": True,
            "economic_edge_evaluated": False,
        }

    def test_identity_is_unique_fixed_300s_smoke_and_separate_from_discovery(self):
        first = _build_identity(started_at=1_000)
        second = _build_identity(started_at=1_000)

        self.assertEqual(SMOKE_DURATION_SECONDS, 300)
        self.assertEqual(first["mode"], "smoke")
        self.assertEqual(first["duration_seconds"], 300)
        self.assertFalse(first["discovery_registry_used"])
        self.assertFalse(first["economic_edge_evaluated"])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["acquisition_run_key"], first["run_id"])
        self.assertTrue(str(first["cohort_id"]).startswith(str(first["run_id"])))
        self.assertNotIn("duration-seconds", _parser()._option_string_actions)

    def test_standard_wss_coverage_artifact_never_claims_scientific_continuity(self):
        coverage = _coverage_artifact(acquisition_run_key="smoke-run")

        self.assertEqual(coverage["coverage_classification"], COVERAGE_CLASSIFICATION)
        self.assertFalse(coverage["chain_complete_coverage_claimed"])
        self.assertFalse(coverage["scientific_continuous_coverage_persisted"])
        self.assertEqual(coverage["scientific_coverage_interval_count"], 0)

    def test_zero_triggers_can_still_pass_operational_smoke(self):
        report = self._passing_report()

        self.assertEqual(report["pipeline"]["kernel_triggers_emitted"], 0)
        self.assertEqual(report["pipeline"]["t0_snapshots_persisted"], 0)
        self.assertEqual(classify_operational_smoke(report), PASS_CLASSIFICATION)

    def test_fake_scientific_coverage_fails_closed(self):
        report = self._passing_report()
        report["coverage"]["chain_complete_coverage_claimed"] = True
        report["coverage"]["scientific_continuous_coverage_persisted"] = True
        report["coverage"]["scientific_coverage_interval_count"] = 1

        self.assertEqual(classify_operational_smoke(report), FAIL_CLASSIFICATION)

    def test_fatal_stage_error_fails_closed(self):
        report = self._passing_report()
        report["fatal_error"] = "RuntimeError:boom"

        self.assertEqual(classify_operational_smoke(report), FAIL_CLASSIFICATION)

    def test_kernel_path_must_be_exercised_but_episode_count_is_not_a_gate(self):
        report = self._passing_report()
        report["pipeline"]["market_trade_adapted_events"] = 0
        report["pipeline"]["kernel_trade_events_ingested"] = 0

        self.assertEqual(classify_operational_smoke(report), FAIL_CLASSIFICATION)

    def test_first_received_wall_clock_restores_causal_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            carbon = root / "carbon.jsonl"
            manifest = root / "manifest.jsonl"
            carbon.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"type": "carbon_canonical_event", "status": "decoded", "event_key": "z"},
                        {"type": "carbon_canonical_event", "status": "decoded", "event_key": "a"},
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {"event_key": "z", "first_received_wall_ns": 1_000_000_000},
                        {"event_key": "a", "first_received_wall_ns": 2_000_000_000},
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            ordered, errors = _canonical_rows_in_receive_order(
                carbon_output_path=carbon,
                target_manifest_path=manifest,
            )

        self.assertEqual(errors, [])
        self.assertEqual([row[0]["event_key"] for row in ordered], ["z", "a"])
        self.assertEqual(_observed_at_from_wall_ns(2_999_999_999), 2)

    def test_t0_is_immutable_and_future_outcomes_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market-first-live-smoke.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run_key = "market-first-live-smoke-test-run"
                mint = "SMOKE_MINT"
                for index, chain_time in enumerate((940, 960, 980, 995), start=1):
                    record_market_trade(
                        acquisition_run_key=run_key,
                        event_key=f"trade-{index}",
                        source_provider="test",
                        observation=MarketTradeObservation(
                            token_mint=mint,
                            side="buy" if index % 2 else "sell",
                            chain_time=chain_time,
                            observed_at=1_900 + index,
                            wallet_address=f"wallet-{index}",
                            notional_usd=None,
                            price_usd=None,
                            venue="pump",
                            transaction_key=f"sig-{index}",
                        ),
                    )

                episode = assign_market_opportunity_trigger(
                    acquisition_run_key=run_key,
                    trigger_key="first-live-trigger",
                    token_mint=mint,
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=1_000,
                    observed_at=2_000,
                    method_version=MARKET_OPPORTUNITY_RADAR_VERSION,
                    venue="pump",
                )
                preparation = _prepare_t0_for_episode(
                    acquisition_run_key=run_key,
                    episode=episode,
                )
                before = load_market_episode_research_snapshot_record_v0(
                    acquisition_run_key=run_key,
                    episode_key=episode.episode_key,
                    snapshot_method_version=preparation.snapshot.method_version,
                )
                outcomes = load_opportunity_forward_outcomes(
                    acquisition_run_key=run_key,
                    episode_key=episode.episode_key,
                )

                self.assertIsNotNone(before)
                self.assertEqual(preparation.snapshot.decision_as_of, 2_000)
                self.assertEqual(preparation.snapshot.market_intelligence.chain_as_of, 1_000)
                self.assertIsNone(preparation.snapshot.pump_creation_mode.mayhem_mode)
                self.assertEqual(preparation.snapshot.market_intelligence.execution.quote_count, 0)
                self.assertTrue(
                    "pump_create_v2_mode_not_observed"
                    in preparation.snapshot.pump_creation_mode.data_quality_flags
                )
                self.assertEqual([item.horizon_seconds for item in outcomes], [300, 900, 3600])
                self.assertTrue(all(item.status == "PENDING" for item in outcomes))

                complete_opportunity_forward_outcome(
                    outcome_key=outcomes[0].outcome_key,
                    status="UNAVAILABLE",
                    observed_at=outcomes[0].target_at,
                )
                after = load_market_episode_research_snapshot_record_v0(
                    acquisition_run_key=run_key,
                    episode_key=episode.episode_key,
                    snapshot_method_version=preparation.snapshot.method_version,
                )
                completed = load_opportunity_forward_outcomes(
                    acquisition_run_key=run_key,
                    episode_key=episode.episode_key,
                )

        self.assertIsNotNone(after)
        self.assertEqual(before.payload_json, after.payload_json)
        self.assertEqual(before.payload_sha256, after.payload_sha256)
        self.assertEqual(completed[0].status, "UNAVAILABLE")
        self.assertEqual([item.status for item in completed[1:]], ["PENDING", "PENDING"])


if __name__ == "__main__":
    unittest.main()
