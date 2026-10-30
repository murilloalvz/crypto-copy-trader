from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_sniper_v1.strict_compare import (
    validate_sniper_source_integrity_v1,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _input(episodes: list[dict]) -> dict:
    return {
        "type": "launch_burst_prospective_route_input_v2",
        "feature_snapshot_frozen_before_provider_quotes": True,
        "episodes": episodes,
    }


def _result(decisions: list[dict]) -> dict:
    return {
        "type": "launch_burst_prospective_route_paper_result_v2",
        "classification": "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2",
        "decisions": decisions,
    }


class LaunchBurstSniperStrictCompareV1Tests(unittest.TestCase):
    def test_exact_episode_and_token_parity_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            route_input = root / "input.json"
            route_result = root / "result.json"
            smart = root / "smart.json"
            _write(
                route_input,
                _input([
                    {"episode_key": "A", "token_mint": "MintA"},
                    {"episode_key": "B", "token_mint": "MintB"},
                ]),
            )
            _write(
                route_result,
                _result([
                    {"episode_key": "B", "token_mint": "MintB"},
                    {"episode_key": "A", "token_mint": "MintA"},
                ]),
            )
            _write(smart, {"trades": [{"episode_key": "A"}]})

            integrity = validate_sniper_source_integrity_v1(
                route_input_path=route_input,
                route_result_path=route_result,
                smart_result_path=smart,
            )
            self.assertTrue(integrity["exact_episode_key_parity"])
            self.assertTrue(integrity["exact_token_mint_parity"])
            self.assertEqual(integrity["route_episode_count"], 2)
            self.assertEqual(integrity["smart_trade_count"], 1)

    def test_same_length_but_different_episode_keys_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            route_input = root / "input.json"
            route_result = root / "result.json"
            _write(route_input, _input([{"episode_key": "A", "token_mint": "MintA"}]))
            _write(route_result, _result([{"episode_key": "B", "token_mint": "MintA"}]))

            with self.assertRaisesRegex(ValueError, "episode keys differ"):
                validate_sniper_source_integrity_v1(
                    route_input_path=route_input,
                    route_result_path=route_result,
                    smart_result_path=None,
                )

    def test_matching_key_with_different_token_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            route_input = root / "input.json"
            route_result = root / "result.json"
            _write(route_input, _input([{"episode_key": "A", "token_mint": "MintA"}]))
            _write(route_result, _result([{"episode_key": "A", "token_mint": "MintB"}]))

            with self.assertRaisesRegex(ValueError, "token mint mismatch"):
                validate_sniper_source_integrity_v1(
                    route_input_path=route_input,
                    route_result_path=route_result,
                    smart_result_path=None,
                )

    def test_duplicate_episode_key_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            route_input = root / "input.json"
            route_result = root / "result.json"
            _write(
                route_input,
                _input([
                    {"episode_key": "A", "token_mint": "MintA"},
                    {"episode_key": "A", "token_mint": "MintA"},
                ]),
            )
            _write(route_result, _result([{"episode_key": "A", "token_mint": "MintA"}]))

            with self.assertRaisesRegex(ValueError, "duplicate episode_key"):
                validate_sniper_source_integrity_v1(
                    route_input_path=route_input,
                    route_result_path=route_result,
                    smart_result_path=None,
                )

    def test_smart_orphan_episode_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            route_input = root / "input.json"
            route_result = root / "result.json"
            smart = root / "smart.json"
            _write(route_input, _input([{"episode_key": "A", "token_mint": "MintA"}]))
            _write(route_result, _result([{"episode_key": "A", "token_mint": "MintA"}]))
            _write(smart, {"trades": [{"episode_key": "Z"}]})

            with self.assertRaisesRegex(ValueError, "outside the route universe"):
                validate_sniper_source_integrity_v1(
                    route_input_path=route_input,
                    route_result_path=route_result,
                    smart_result_path=smart,
                )


if __name__ == "__main__":
    unittest.main()
