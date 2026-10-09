from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.opportunity_token_hazard import TokenHazardEvidence


TOKEN = "TOKEN"


def _episode() -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key="episode",
        acquisition_run_key="run",
        token_mint=TOKEN,
        first_trigger_key="trigger",
        first_trigger_kind="activity_acceleration",
        first_trigger_direction="upward_pressure",
        first_trigger_chain_time=990,
        first_trigger_observed_at=991,
        episode_closes_at=1051,
        decision_as_of=None,
    )


def _hazard(observed_at=999):
    return TokenHazardEvidence(
        episode_key="episode",
        token_mint=TOKEN,
        provider="solana_tracker_token_info",
        observed_at=observed_at,
        status="AVAILABLE",
        risk_score=3.5,
        rugged=False,
        jupiter_verified=True,
        top10_pct=20.0,
        dev_pct=1.0,
        snipers_pct=2.0,
        bundlers_pct=3.0,
        insiders_pct=4.0,
        freeze_authority_present=False,
        mint_authority_present=False,
        risk_factors=(("Top 10 Holders", "warning", 500.0),),
        data_quality_flags=(),
    )


class OpportunityHazardEnrichmentTests(unittest.TestCase):
    def test_available_hazard_is_included_when_observed_by_as_of(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                bundle = build_episode_enrichment_bundle(
                    episode=_episode(), as_of=1000, hazard_evidence=_hazard(999)
                )

        self.assertEqual(bundle.risk.status, "AVAILABLE")
        self.assertEqual(bundle.risk.observed_at, 999)
        self.assertAlmostEqual(bundle.risk.risk_score, 3.5)
        self.assertFalse(bundle.risk.rugged)

    def test_later_hazard_is_not_backfilled_into_earlier_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                bundle = build_episode_enrichment_bundle(
                    episode=_episode(), as_of=1000, hazard_evidence=_hazard(1001)
                )

        self.assertEqual(bundle.risk.status, "not_observed_as_of")
        self.assertIsNone(bundle.risk.risk_score)
        self.assertIn("token_hazard_observed_after_as_of", bundle.risk.data_quality_flags)


if __name__ == "__main__":
    unittest.main()
