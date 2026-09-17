from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_concentration_decay_v0.run import (
    DEFAULT_CONTRACT,
    DEFAULT_POLICY,
    FEATURE_ID,
    _read_json,
    _validate_policy,
    run_evaluation,
)
from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_feature_eligible_v0,
    feature_spec_v0,
)


EXPECTED_POLICY_HASH = "401109ad1ede8b175fd3db2b0ed6e564bc3f71040246acb04d591c33acfb188c"


class LaunchBurstConcentrationDecayV0Tests(unittest.TestCase):
    def test_policy_hash_and_route_contract_are_frozen(self):
        policy = _read_json(DEFAULT_POLICY)
        contract = _read_json(DEFAULT_CONTRACT)
        self.assertEqual(policy["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        _validate_policy(policy, contract)
        self.assertEqual(policy["economic_contract"]["route_contract_hash_sha256"], contract["contract_hash_sha256"])
        self.assertEqual(policy["feature_rule"]["value"], 0.0)
        self.assertEqual(policy["feature_rule"]["op"], "<=")

    def test_feature_remains_diagnostic_and_cannot_be_promoted_by_this_experiment(self):
        spec = feature_spec_v0(FEATURE_ID)
        self.assertEqual(spec.track, TRACK_MARKET_FIRST)
        self.assertTrue(spec.diagnostic_only)
        self.assertFalse(spec.selector_eligible)
        self.assertFalse(spec.future_dependent)
        self.assertFalse(spec.execution_only)
        with self.assertRaisesRegex(ValueError, "diagnostic-only"):
            assert_selector_feature_eligible_v0(FEATURE_ID, selector_track=TRACK_MARKET_FIRST)

    def test_full_evaluation_uses_semantic_zero_threshold_and_can_keep_only_on_robust_metrics(self):
        contract = _read_json(DEFAULT_CONTRACT)
        route_hash = contract["contract_hash_sha256"]
        decisions = []
        dynamics_rows = []
        episodes = []

        candidate_returns = [10, 11, 12, 13, 14, 15, 16, 17, 18, 20]
        for index, ret in enumerate(candidate_returns):
            key = f"candidate-{index}"
            decisions.append({
                "episode_key": key,
                "token_mint": f"token-c-{index}",
                "decision_as_of": 1000 + index,
                "admitted": True,
                "status": "ROUTE_CLOSED",
                "route_paper_pnl_usd": 25.0 * ret / 100.0,
                "gross_route_return_pct": ret + 2.4,
            })
            dynamics_rows.append({
                "episode_key": key,
                "baseline_admitted": True,
                "features": {FEATURE_ID: -float(index + 1)},
            })
            episodes.append({"episode_key": key})

        for index, ret in enumerate((-100.0, -80.0)):
            key = f"other-{index}"
            decisions.append({
                "episode_key": key,
                "token_mint": f"token-o-{index}",
                "decision_as_of": 2000 + index,
                "admitted": True,
                "status": "ROUTE_CLOSED",
                "route_paper_pnl_usd": 25.0 * ret / 100.0,
                "gross_route_return_pct": ret + 2.4,
            })
            dynamics_rows.append({
                "episode_key": key,
                "baseline_admitted": True,
                "features": {FEATURE_ID: float(index + 1)},
            })
            episodes.append({"episode_key": key})

        route_input = {
            "contract_hash_sha256": route_hash,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "episodes": episodes,
        }
        route_result = {"contract_hash_sha256": route_hash, "decisions": decisions}
        dynamics = {
            "classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1",
            "source_integrity": {
                "exact_reconstruction_parity": True,
                "route_contract_hash_sha256": route_hash,
            },
            "rows": dynamics_rows,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "route-input-v2.json").write_text(json.dumps(route_input), encoding="utf-8")
            (run_dir / "route-result-v2.json").write_text(json.dumps(route_result), encoding="utf-8")
            (run_dir / "market-first-feature-discovery-v1.json").write_text(json.dumps(dynamics), encoding="utf-8")
            report = run_evaluation(run_dir=run_dir)

        self.assertEqual(report["classification"], "PASS_LAUNCH_BURST_CONCENTRATION_DECAY_V0_EVALUATION")
        self.assertEqual(report["decision"], "KEEP")
        self.assertEqual(report["population"]["candidate_selected_count"], 10)
        self.assertAlmostEqual(report["population"]["signal_frequency_pct_of_feature_available_baseline"], 100.0 * 10 / 12)
        self.assertEqual(report["economics"]["candidate"]["n"], 10)
        self.assertGreater(report["economics"]["candidate"]["net_return_pct"]["mean_without_best_trade"], 0)
        self.assertFalse(report["selector_changed"])
        self.assertTrue(report["fresh_confirmation_required"])


if __name__ == "__main__":
    unittest.main()
