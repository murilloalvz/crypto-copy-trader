from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
)
from benchmarks.early_buyer_churn_prospective_v1.run import (
    _decision,
    run_confirmation,
)
from benchmarks.early_buyer_churn_prospective_v1.run_live import (
    _attest_route_input,
    _validate_parity_report,
    _validate_provider_preflight_artifact,
)
from benchmarks.early_buyer_churn_v0.run import FEATURE_ID


class EarlyBuyerChurnProspectiveConfirmationV1Tests(unittest.TestCase):
    def test_parity_report_must_be_exact_zero_mismatch(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        expected_runs = list(
            (protocol.get("instrumentation") or {}).get("parity_runs") or []
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parity.json"
            payload = {
                "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY",
                "exact_parity": True,
                "mismatch_count": 1,
                "compared_complete_episode_count": 2056,
                "protocol_hash_sha256": protocol["protocol_hash_sha256"],
                "feature_id": FEATURE_ID,
                "per_run": [
                    {
                        "run_id": run_id,
                        "all_guardrails_valid": True,
                        "mismatch_count": 0,
                    }
                    for run_id in expected_runs
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "has mismatches"):
                _validate_parity_report(
                    parity_report_path=path,
                    protocol=protocol,
                )


    def test_provider_preflight_artifact_rejects_helius_even_when_marked_pass(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        parity = {
            "protocol_hash_sha256": protocol["protocol_hash_sha256"],
            "exact_parity": True,
            "mismatch_count": 0,
        }
        payload = {
            "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT",
            "protocol_hash_sha256": protocol["protocol_hash_sha256"],
            "parity_attestation": parity,
            "gates": {"all": True},
            "selected_rpc": {
                "candidate_index": 0,
                "safe_host": "mainnet.helius-rpc.com",
                "fallback_used": False,
                "helius": False,
            },
            "market_ingest": {
                "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
                "source_provider": "solana_public_standard_wss",
                "endpoint_host": "api.mainnet.solana.com",
                "http_hydration_used": False,
            },
            "economic_outcomes_opened": False,
            "fresh_confirmation_consumed": False,
            "provider_execute_called": False,
            "private_key_used": False,
            "transaction_signed": False,
            "transaction_submitted": False,
            "helius_dependency_active": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selected Helius RPC"):
                _validate_provider_preflight_artifact(
                    provider_preflight_path=path,
                    protocol=protocol,
                    parity=parity,
                )


    def test_provider_preflight_artifact_returns_approved_control_hash(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        parity = {
            "protocol_hash_sha256": protocol["protocol_hash_sha256"],
            "exact_parity": True,
            "mismatch_count": 0,
        }
        control_hash = "a" * 64
        payload = {
            "classification": "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT",
            "protocol_hash_sha256": protocol["protocol_hash_sha256"],
            "parity_attestation": parity,
            "gates": {"all": True},
            "selected_rpc": {
                "candidate_index": 0,
                "safe_host": "solana-mainnet.g.alchemy.com",
                "fallback_used": False,
                "helius": False,
            },
            "control": {
                "owner_public_key_sha256": control_hash,
                "known_liquid_control_assembled": True,
                "representative_burst_assembled": True,
            },
            "market_ingest": {
                "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
                "source_provider": "solana_public_standard_wss",
                "endpoint_host": "api.mainnet.solana.com",
                "http_hydration_used": False,
            },
            "economic_outcomes_opened": False,
            "fresh_confirmation_consumed": False,
            "provider_execute_called": False,
            "private_key_used": False,
            "transaction_signed": False,
            "transaction_submitted": False,
            "helius_dependency_active": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            attestation = _validate_provider_preflight_artifact(
                provider_preflight_path=path,
                protocol=protocol,
                parity=parity,
            )
        self.assertEqual(
            attestation["selected_control_hash_sha256"],
            control_hash,
        )

    def test_route_input_attestation_accepts_available_missing_and_right_censored(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            route_input = {
                "feature_snapshot_frozen_before_provider_quotes": True,
                "episodes": [
                    {
                        "episode_key": "available",
                        "feature_snapshot": {
                            "complete": True,
                            "features": {FEATURE_ID: 0.25},
                            "external_evidence": {
                                "early_buyer_churn_prospective_v1": {
                                    "feature_id": FEATURE_ID,
                                    "status": "CAUSAL_AVAILABLE",
                                    "feature_value": 0.25,
                                    "computed_before_provider_quotes": True,
                                    "external_provider_used": False,
                                }
                            },
                        },
                    },
                    {
                        "episode_key": "missing",
                        "feature_snapshot": {
                            "complete": True,
                            "features": {FEATURE_ID: None},
                            "external_evidence": {
                                "early_buyer_churn_prospective_v1": {
                                    "feature_id": FEATURE_ID,
                                    "status": "MISSING_NO_OBSERVED_BUY",
                                    "feature_value": None,
                                    "computed_before_provider_quotes": True,
                                    "external_provider_used": False,
                                }
                            },
                        },
                    },
                    {
                        "episode_key": "right",
                        "feature_snapshot": {
                            "complete": False,
                            "features": {FEATURE_ID: None},
                            "external_evidence": {
                                "early_buyer_churn_prospective_v1": {
                                    "feature_id": FEATURE_ID,
                                    "status": "RIGHT_CENSORED",
                                    "feature_value": None,
                                    "computed_before_provider_quotes": True,
                                    "external_provider_used": False,
                                }
                            },
                        },
                    },
                ],
            }
            (run_dir / "route-input-v2.json").write_text(
                json.dumps(route_input),
                encoding="utf-8",
            )
            report = _attest_route_input(run_dir)

        self.assertTrue(report["instrumentation_valid"])
        self.assertEqual(report["complete_episode_count"], 2)
        self.assertEqual(report["causal_available_count"], 1)
        self.assertEqual(report["missing_no_buy_count"], 1)
        self.assertEqual(report["right_censored_count"], 1)

    def test_route_input_attestation_rejects_external_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            route_input = {
                "feature_snapshot_frozen_before_provider_quotes": True,
                "episodes": [
                    {
                        "episode_key": "bad",
                        "feature_snapshot": {
                            "complete": True,
                            "features": {FEATURE_ID: 0.2},
                            "external_evidence": {
                                "early_buyer_churn_prospective_v1": {
                                    "feature_id": FEATURE_ID,
                                    "status": "CAUSAL_AVAILABLE",
                                    "feature_value": 0.2,
                                    "computed_before_provider_quotes": True,
                                    "external_provider_used": True,
                                }
                            },
                        },
                    }
                ],
            }
            (run_dir / "route-input-v2.json").write_text(
                json.dumps(route_input),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "external_provider"):
                _attest_route_input(run_dir)

    def test_decision_requires_all_frozen_keep_gates(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        primary = {
            "usable_pair_count": 35,
            "spearman": -0.10,
            "spearman_without_best_trade": -0.11,
            "leave_one_out_sign_consistency_fraction": 1.0,
            "lower_or_equal_feature_half": {"median_outcome_pct": -5.0},
            "higher_feature_half": {"median_outcome_pct": -20.0},
        }
        incremental = {"partial_spearman": -0.05}
        decision, checks = _decision(
            protocol=protocol,
            primary=primary,
            incremental=incremental,
        )
        self.assertEqual(decision, "KEEP")
        self.assertTrue(all(value is True for value in checks.values()))

        incremental["partial_spearman"] = 0.01
        decision, checks = _decision(
            protocol=protocol,
            primary=primary,
            incremental=incremental,
        )
        self.assertEqual(decision, "NO_CONFIRMATION_CLOSE_OR_REVIEW")
        self.assertFalse(checks["partial_spearman_negative"])

    def test_decision_insufficient_sample_never_rescues(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        primary = {
            "usable_pair_count": 29,
            "spearman": -0.5,
            "spearman_without_best_trade": -0.5,
            "leave_one_out_sign_consistency_fraction": 1.0,
            "lower_or_equal_feature_half": {"median_outcome_pct": 10.0},
            "higher_feature_half": {"median_outcome_pct": -20.0},
        }
        incremental = {"partial_spearman": -0.5}
        decision, checks = _decision(
            protocol=protocol,
            primary=primary,
            incremental=incremental,
        )
        self.assertEqual(decision, "INSUFFICIENT_SAMPLE_NO_EXTENSION")
        self.assertFalse(checks["minimum_primary_pairs_met"])

    def test_fresh_name_matching_prior_fails_before_source_evaluation(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        prior_ids = list(
            (protocol.get("instrumentation") or {}).get("parity_runs") or []
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = [root / run_id for run_id in prior_ids]
            fresh = root / prior_ids[-1]
            with patch(
                "benchmarks.early_buyer_churn_prospective_v1.run.read_json",
                side_effect=[
                    protocol,
                    {"contract_hash_sha256": "hash"},
                ],
            ), patch(
                "benchmarks.early_buyer_churn_prospective_v1.run.validate_protocol"
            ):
                with self.assertRaisesRegex(ValueError, "fresh run identity matches"):
                    run_confirmation(
                        prior_run_dirs=prior,
                        fresh_run_dir=fresh,
                        parity_report_path=root / "unused-parity.json",
                    )


if __name__ == "__main__":
    unittest.main()
