import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.jupiter_market_discovery_probe import (
    probe_jupiter_market_discovery,
)


class JupiterMarketDiscoveryProbeV0Tests(unittest.TestCase):
    def test_all_lists_are_preserved_without_creating_recommendation(self):
        def fake_get_json(url, *, api_key, timeout_seconds):
            if "toporganicscore" in url:
                return [{"id": "A", "organicScore": 90}, {"id": "B", "organicScore": 80}]
            if "toptraded" in url:
                return [{"id": "B"}, {"id": "C"}]
            if "toptrending" in url:
                return [{"id": "D"}, {"id": "B"}]
            if url.endswith("/recent"):
                return [{"id": "E", "firstPool": {"createdAt": "now"}}]
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "discovery.jsonl"
            report = probe_jupiter_market_discovery(
                output_path=out,
                api_key=None,
                rps=1000,
                limit=50,
                get_json=fake_get_json,
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(report["valid_probe"])
        self.assertEqual(report["unique_mints"], 5)
        self.assertEqual(report["mints_present_in_multiple_lists"], 1)
        self.assertEqual(report["multi_list_mint_examples"], ["B"])
        self.assertFalse(report["recommendation_or_bot_score_created"])
        self.assertTrue(report["market_first_external_discovery_candidate"])
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row["economic_edge_evaluated"] is False for row in rows))

    def test_partial_provider_failure_fails_probe_instead_of_treating_list_as_empty(self):
        def fake_get_json(url, *, api_key, timeout_seconds):
            if "toptraded" in url:
                raise OSError("provider unavailable")
            return [{"id": "A"}]

        with tempfile.TemporaryDirectory() as directory:
            report = probe_jupiter_market_discovery(
                output_path=Path(directory) / "discovery.jsonl",
                rps=1000,
                get_json=fake_get_json,
            )
        self.assertFalse(report["valid_probe"])
        self.assertEqual(report["query_errors"], 1)
        self.assertNotIn("toptraded_5m", report["queries_succeeded"])

    def test_invalid_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                probe_jupiter_market_discovery(
                    output_path=Path(directory) / "discovery.jsonl",
                    limit=101,
                )


if __name__ == "__main__":
    unittest.main()
