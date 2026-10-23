from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from src.robinhood_pons_adapter_v62 import PonsLaunchV62, validate_launch_v62


PONS_CURVE_STATE_PROGRESS_VERSION = "pons_curve_state_progress_v64_exact_state"


@dataclass(frozen=True)
class PonsCurveStateObservationV64:
    """One same-block read of the Pons v2 bonding-curve state.

    The observation must come from one coherent block/state reference. It is intentionally
    independent of reconstructed external trade volume because fee-sweep buybacks can move the
    curve's real reserve internally.
    """

    token_address: str
    graduation_threshold_raw: int
    real_quote_reserve_raw: int
    sellable_tokens_raw: int
    ready_to_graduate: bool
    graduated: bool
    block_number: int
    chain_time: int
    observed_at: int
    source_provider: str


@dataclass(frozen=True)
class PonsCurveProgressSnapshotV64:
    method_version: str
    token_address: str
    as_of: int
    observation_block_number: int | None
    observation_chain_time: int | None
    observation_observed_at: int | None
    graduation_threshold_raw: int
    real_quote_reserve_raw: int | None
    sellable_tokens_raw: int | None
    reserve_progress_pct: float | None
    remaining_quote_to_threshold_raw: int | None
    remaining_quote_to_threshold_pct: float | None
    ready_to_graduate: bool | None
    graduated: bool | None
    curve_tradable: bool | None
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _canonical_evm_address(value: str) -> str:
    normalized = str(value).strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValueError("token_address must be a 20-byte EVM address")
    try:
        int(normalized[2:], 16)
    except ValueError as exc:
        raise ValueError("token_address must be a 20-byte EVM address") from exc
    return normalized


def validate_curve_state_observation_v64(item: PonsCurveStateObservationV64) -> None:
    _canonical_evm_address(item.token_address)
    _required(item.source_provider, "source_provider")
    if int(item.graduation_threshold_raw) <= 0:
        raise ValueError("graduation_threshold_raw must be positive")
    if int(item.real_quote_reserve_raw) < 0:
        raise ValueError("real_quote_reserve_raw must be non-negative")
    if int(item.sellable_tokens_raw) < 0:
        raise ValueError("sellable_tokens_raw must be non-negative")
    if int(item.block_number) < 0:
        raise ValueError("block_number must be non-negative")
    if int(item.chain_time) < 0 or int(item.observed_at) < 0:
        raise ValueError("timestamps must be non-negative")
    if int(item.observed_at) < int(item.chain_time):
        raise ValueError("observed_at cannot precede chain_time")

    if item.graduated and item.ready_to_graduate:
        raise ValueError("graduated curve cannot also report ready_to_graduate")
    if not item.graduated:
        expected_ready = int(item.sellable_tokens_raw) == 0
        if bool(item.ready_to_graduate) != expected_ready:
            raise ValueError("ready_to_graduate must agree with sellable_tokens_raw")


def build_pons_curve_progress_snapshot_v64(
    *,
    launch: PonsLaunchV62,
    observations: Iterable[PonsCurveStateObservationV64],
    as_of: int,
) -> PonsCurveProgressSnapshotV64:
    """Select the latest state the collector could know by ``as_of`` and measure progress.

    Causal availability requires both ``chain_time <= as_of`` and ``observed_at <= as_of``.
    A historical state discovered later cannot retroactively affect an earlier decision.

    Progress is intentionally unavailable once ``graduated`` is true because the curve's reserves
    are drained during graduation; reporting the post-drain zero as 0% progress would be false.
    """

    validate_launch_v62(launch)
    cutoff = int(as_of)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")

    token = _canonical_evm_address(launch.token_address)
    threshold = int(launch.graduation_threshold_raw)

    eligible: list[PonsCurveStateObservationV64] = []
    for item in observations:
        validate_curve_state_observation_v64(item)
        if _canonical_evm_address(item.token_address) != token:
            continue
        if int(item.graduation_threshold_raw) != threshold:
            raise ValueError("state graduation threshold does not match frozen launch threshold")
        if int(item.chain_time) <= cutoff and int(item.observed_at) <= cutoff:
            eligible.append(item)

    if not eligible:
        return PonsCurveProgressSnapshotV64(
            method_version=PONS_CURVE_STATE_PROGRESS_VERSION,
            token_address=token,
            as_of=cutoff,
            observation_block_number=None,
            observation_chain_time=None,
            observation_observed_at=None,
            graduation_threshold_raw=threshold,
            real_quote_reserve_raw=None,
            sellable_tokens_raw=None,
            reserve_progress_pct=None,
            remaining_quote_to_threshold_raw=None,
            remaining_quote_to_threshold_pct=None,
            ready_to_graduate=None,
            graduated=None,
            curve_tradable=None,
            data_quality_flags=("NO_CAUSAL_STATE_OBSERVATION",),
        )

    eligible.sort(
        key=lambda item: (
            int(item.chain_time),
            int(item.block_number),
            int(item.observed_at),
        )
    )
    item = eligible[-1]

    flags: list[str] = []
    reserve = int(item.real_quote_reserve_raw)
    sellable = int(item.sellable_tokens_raw)

    progress = None
    remaining_raw = None
    remaining_pct = None
    curve_tradable = False if item.graduated else not item.ready_to_graduate

    if item.graduated:
        flags.append("POST_GRADUATION_CURVE_STATE_PROGRESS_NOT_MEANINGFUL")
    else:
        progress_value = 100.0 * reserve / threshold
        progress = progress_value if math.isfinite(progress_value) else None
        remaining_raw = max(threshold - reserve, 0)
        remaining_pct_value = 100.0 * remaining_raw / threshold
        remaining_pct = remaining_pct_value if math.isfinite(remaining_pct_value) else None
        if reserve > threshold:
            flags.append("REAL_QUOTE_RESERVE_ABOVE_THRESHOLD")
        if item.ready_to_graduate:
            flags.append("CURVE_READY_TO_GRADUATE_TRADING_HALTED")
        if reserve >= threshold and not item.ready_to_graduate:
            flags.append("RESERVE_THRESHOLD_REACHED_WITH_SELLABLE_TOKENS")

    return PonsCurveProgressSnapshotV64(
        method_version=PONS_CURVE_STATE_PROGRESS_VERSION,
        token_address=token,
        as_of=cutoff,
        observation_block_number=int(item.block_number),
        observation_chain_time=int(item.chain_time),
        observation_observed_at=int(item.observed_at),
        graduation_threshold_raw=threshold,
        real_quote_reserve_raw=reserve,
        sellable_tokens_raw=sellable,
        reserve_progress_pct=progress,
        remaining_quote_to_threshold_raw=remaining_raw,
        remaining_quote_to_threshold_pct=remaining_pct,
        ready_to_graduate=bool(item.ready_to_graduate),
        graduated=bool(item.graduated),
        curve_tradable=curve_tradable,
        data_quality_flags=tuple(flags),
    )
