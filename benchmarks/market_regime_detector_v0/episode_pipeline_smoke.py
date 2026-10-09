"""End-to-end research smoke: covered bins -> Page-Hinkley -> episode regime facts."""

from benchmarks.market_regime_detector_v0.covered_page_hinkley import run_covered_page_hinkley_v0
from benchmarks.market_regime_detector_v0.covered_smoke import _series
from benchmarks.market_regime_detector_v0.episode_adapter import to_market_regime_research_facts_v0
from src.market_episode_research_snapshot import build_market_episode_research_snapshot_v0
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_snapshot_core import build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0


def main() -> int:
    low = [2, 2, 3, 1] * 45
    high = [8, 8, 9, 7] * 60
    series = _series(low + high)
    covered = run_covered_page_hinkley_v0(series)
    regime = to_market_regime_research_facts_v0(covered)

    assert regime.detection_count >= 1
    assert regime.latest_detection_chain_time == covered.detections[-1].detected_bin_start_chain_time
    assert regime.missing_bins_skipped == 0

    decision_as_of = 500
    mint = "MINT_A"
    episode = MarketOpportunityEpisode(
        episode_key="EP-SMOKE",
        acquisition_run_key="RUN-SMOKE",
        token_mint=mint,
        first_trigger_key="TR-SMOKE",
        first_trigger_kind="market_radar",
        first_trigger_direction="up",
        first_trigger_chain_time=180,
        first_trigger_observed_at=181,
        episode_closes_at=560,
        decision_as_of=decision_as_of,
    )
    protocol = build_market_protocol_facts_v0(token_mint=mint, as_of=decision_as_of)
    core = build_opportunity_snapshot_core_v1(
        token_mint=mint,
        as_of=decision_as_of,
        flow_observations=(),
        quotes=(),
        flow_windows_seconds=(30, 300),
    )
    intelligence = build_market_intelligence_baseline_v0(protocol=protocol, snapshot=core)
    creation_mode = build_pump_creation_mode_facts_v0(token_mint=mint, as_of=decision_as_of)

    snapshot = build_market_episode_research_snapshot_v0(
        episode=episode,
        market_intelligence=intelligence,
        pump_creation_mode=creation_mode,
        regime=regime,
    )

    assert snapshot.token_mint == mint
    assert snapshot.decision_as_of == decision_as_of
    assert snapshot.regime is not None
    assert snapshot.regime.detection_count == regime.detection_count
    assert snapshot.regime.latest_detection_chain_time <= snapshot.decision_as_of
    assert "regime_evidence_not_available" not in snapshot.data_quality_flags
    assert "pump_create_v2_mode_not_observed" in snapshot.data_quality_flags

    print("PASS_MARKET_EPISODE_REGIME_PIPELINE_V0")
    print(f"detections={snapshot.regime.detection_count}")
    print(f"latest_detection_chain_time={snapshot.regime.latest_detection_chain_time}")
    print(f"decision_as_of={snapshot.decision_as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
