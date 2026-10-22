from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_enrichment_store import admit_opportunity_episode
from src.signal_plane_episode_bridge_v0 import (
    assign_signal_plane_trigger_episode,
    market_movement_trigger_from_snapshot,
)


SIGNAL_PLANE_EPISODE_ADMISSION_VERSION = "signal_plane_episode_admission_v0"


@dataclass(frozen=True)
class SignalPlaneEpisodeAdmissionResult:
    episode_key: str
    token_mint: str
    first_trigger_observed_at: int
    admitted: bool


def admit_signal_plane_trigger_snapshot(
    *,
    acquisition_run_key: str,
    trigger_snapshot: dict | None,
    observation: MarketTradeObservation,
    admit_episode_fn: Callable[..., bool] | None = None,
) -> SignalPlaneEpisodeAdmissionResult | None:
    """Persist/admit one Rust Signal Plane trigger using frozen episode semantics.

    None trigger snapshots are legitimate non-signal decisions and are ignored.
    Trigger reconstruction, episode identity and causal clock validation remain
    fail-closed inside the bridge.
    """

    if trigger_snapshot is None:
        return None

    trigger = market_movement_trigger_from_snapshot(trigger_snapshot)
    episode = assign_signal_plane_trigger_episode(
        acquisition_run_key=acquisition_run_key,
        trigger=trigger,
        observation=observation,
    )
    admission = admit_episode_fn or admit_opportunity_episode
    admitted = admission(
        acquisition_run_key=acquisition_run_key,
        episode_key=episode.episode_key,
        admitted_at=episode.first_trigger_observed_at,
    )
    return SignalPlaneEpisodeAdmissionResult(
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        first_trigger_observed_at=episode.first_trigger_observed_at,
        admitted=admitted,
    )
