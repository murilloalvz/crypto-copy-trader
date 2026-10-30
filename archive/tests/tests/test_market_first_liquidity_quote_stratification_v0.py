from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_liquidity_discovery_v0.quote_stratify import (
    dominant_quote_mint_v0,
    run_quote_stratification_v0,
)


def _row(*, quote_mint: str, baseline: bool, sniper: bool, usable: bool, raw: int, ratio: float, change: float, impact: float | None):
    return {
        "episode_key": f"{quote_mint}:{raw}:{sniper}",
        "baseline_admitted": baseline,
        "sniper_selected": sniper,
        "entry_group": "ENTRY_USABLE" if usable else "ENTRY_UNAVAILABLE",
        "entry_usable": usable,
        "provider_price_impact_pct_points": impact,
        "quote_mint": quote_mint,
        "features": {
            "mf_pump_real_quote_reserve_raw_at_cutoff": raw,
            "mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff": ratio,
            "mf_pump_real_quote_reserve_change_over_virtual_start": change,
        },
    }


class MarketFirstLiquidityQuoteStratificationV0Tests(unittest.TestCase):
    def test_dominant_quote_uses_support_only_and_deterministic_tie_break(self):
        rows = [
            _row(quote_mint="B", baseline=True, sniper=False, usable=True, raw=1, ratio=.1, change=.1, impact=1.0),
            _row(quote_mint="A", baseline=True, sniper=False, usable=False, raw=2, ratio=.2, change=.2, impact=None),
        ]
        self.assertEqual(dominant_quote_mint_v0(rows), "A")

    def test_report_reuses_same_quote_for_baseline_and_sniper_and_makes_raw_comparable(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            source = {
                "classification": "PASS_MARKET_FIRST_LIQUIDITY_DISCOVERY_V0",
                "threshold_search_performed": False,
                "selector_changed": False,
                "provider_execution_used_as_feature": False,
                "source_integrity": {"exact_event_key_parity": True},
                "rows": [
                    _row(quote_mint="SOL", baseline=True, sniper=True, usable=True, raw=10, ratio=.1, change=.1, impact=.5),
                    _row(quote_mint="SOL", baseline=True, sniper=False, usable=False, raw=20, ratio=.2, change=.2, impact=None),
                    _row(quote_mint="SOL", baseline=True, sniper=True, usable=False, raw=30, ratio=.3, change=.3, impact=1.5),
                    _row(quote_mint="USDC", baseline=True, sniper=True, usable=True, raw=999, ratio=.4, change=.4, impact=.2),
                ],
            }
            (run_dir / "market-first-liquidity-discovery-v0.json").write_text(json.dumps(source), encoding="utf-8")
            report = run_quote_stratification_v0(run_dir=run_dir)

            self.assertEqual(report["dominant_quote_mint"], "SOL")
            self.assertEqual(report["baseline_dominant_quote_count"], 3)
            self.assertEqual(report["sniper_dominant_quote_count"], 2)
            baseline_raw = report["cohorts"]["baseline_dominant_quote"]["features"]["mf_pump_real_quote_reserve_raw_at_cutoff"]
            sniper_raw = report["cohorts"]["sniper_dominant_quote"]["features"]["mf_pump_real_quote_reserve_raw_at_cutoff"]
            self.assertTrue(baseline_raw["globally_comparable"])
            self.assertTrue(sniper_raw["globally_comparable"])
            self.assertFalse(report["threshold_search_performed"])
            self.assertFalse(report["selector_changed"])


if __name__ == "__main__":
    unittest.main()
