from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Any

from src.pumpswap_asset_role import (
    PumpSwapOpportunityAssetRole,
    classify_pumpswap_opportunity_asset,
)
from src.pumpswap_stream import PumpSwapCreatePoolEvent, PumpSwapTradeEvent


VERSION = "post_transition_reacceleration_v0"
INFERENCE_ROLE = "DISCOVERY_DIAGNOSTIC_ONLY"
FLOW_WINDOW_SECONDS = 10


@dataclass(frozen=True)
class PostTransitionIdentity:
    pool: str
    opportunity_mint: str
    reference_mint: str
    opportunity_is_base: bool
    opportunity_decimals: int
    reference_decimals: int
    transition_chain_time: int
    transition_observed_at: int
    creator: str
    pump_origin_confirmed: bool
    pump_birth_market_started_at: int | None
    pump_birth_observed_at: int | None


@dataclass(frozen=True)
class ObservedPostTransitionTrade:
    event_key: str
    transaction_key: str
    observed_at: int
    arrival_index: int
    chain_time: int
    normalized_side: str
    wallet_key: str
    opportunity_amount: float
    reference_amount: float
    event_implied_reference_per_opportunity: float


@dataclass(frozen=True)
class WindowSummary:
    event_count: int
    buy_count: int
    sell_count: int
    unique_buy_wallet_count: int
    unique_sell_wallet_count: int
    gross_reference_flow: float
    signed_reference_flow: float
    top_wallet_gross_flow_share_pct: float | None

    def rates(self, *, window_seconds: int) -> dict[str, float | None]:
        seconds = float(window_seconds)
        return {
            "event_rate_per_s": self.event_count / seconds,
            "buy_rate_per_s": self.buy_count / seconds,
            "sell_rate_per_s": self.sell_count / seconds,
            "gross_reference_flow_rate_per_s": self.gross_reference_flow / seconds,
            "signed_reference_flow_rate_per_s": self.signed_reference_flow / seconds,
        }


@dataclass(frozen=True)
class PostTransitionSnapshot:
    version: str
    inference_role: str
    as_of_observed_at: int
    as_of_arrival_index: int | None
    identity: dict[str, Any]
    transition_semantics: str
    trade_count_available: int
    reference_trade_event_key: str | None
    reference_price: float | None
    current_trade_event_key: str | None
    current_price: float | None
    current_return_from_reference_pct: float | None
    running_peak_price: float | None
    running_trough_price: float | None
    running_trough_return_from_reference_pct: float | None
    current_drawdown_from_running_peak_pct: float | None
    max_drawdown_from_running_peak_pct: float | None
    max_drawdown_duration_seconds: float | None
    current_recovery_from_running_trough_pct: float | None
    seconds_since_running_trough: float | None
    seconds_since_transition_observed: float
    seconds_since_transition_chain: float | None
    pullback_observed: bool
    recent_window: dict[str, Any]
    prior_window: dict[str, Any]
    dynamics: dict[str, Any]
    structural_reacceleration_candidate: bool
    provider_quote_used: bool
    future_outcome_used: bool
    future_extrema_used: bool


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _finite_positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def identity_from_create_event(
    event: PumpSwapCreatePoolEvent,
    *,
    observed_at: int,
    pump_birth_market_started_at: int | None = None,
    pump_birth_observed_at: int | None = None,
) -> PostTransitionIdentity:
    learned_at = int(observed_at)
    if learned_at < int(event.timestamp):
        raise ValueError("transition observed_at cannot precede CreatePoolEvent timestamp")

    role = classify_pumpswap_opportunity_asset(
        base_mint=event.base_mint,
        quote_mint=event.quote_mint,
    )
    if role is None:
        raise ValueError("PumpSwap pair has no unambiguous opportunity/reference asset role")

    if event.base_mint_decimals < 0 or event.quote_mint_decimals < 0:
        raise ValueError("mint decimals must be non-negative")

    if role.opportunity_is_base:
        opportunity_decimals = int(event.base_mint_decimals)
        reference_decimals = int(event.quote_mint_decimals)
    else:
        opportunity_decimals = int(event.quote_mint_decimals)
        reference_decimals = int(event.base_mint_decimals)

    if (
        (pump_birth_market_started_at is None)
        != (pump_birth_observed_at is None)
    ):
        raise ValueError("Pump birth lifecycle requires both chain and observed clocks")

    origin_confirmed = (
        pump_birth_market_started_at is not None
        and pump_birth_observed_at is not None
    )
    if origin_confirmed:
        birth_chain = int(pump_birth_market_started_at)
        birth_observed = int(pump_birth_observed_at)
        if birth_chain < 0 or birth_observed < birth_chain:
            raise ValueError("invalid Pump birth lifecycle clock")
        if birth_chain > int(event.timestamp):
            raise ValueError("Pump birth cannot occur after PumpSwap transition")
        if birth_observed > learned_at:
            raise ValueError("Pump birth was not causally known by transition observation")
    else:
        birth_chain = None
        birth_observed = None

    return PostTransitionIdentity(
        pool=_required(event.pool, "pool"),
        opportunity_mint=role.opportunity_mint,
        reference_mint=role.reference_mint,
        opportunity_is_base=role.opportunity_is_base,
        opportunity_decimals=opportunity_decimals,
        reference_decimals=reference_decimals,
        transition_chain_time=int(event.timestamp),
        transition_observed_at=learned_at,
        creator=_required(event.creator, "creator"),
        pump_origin_confirmed=origin_confirmed,
        pump_birth_market_started_at=birth_chain,
        pump_birth_observed_at=birth_observed,
    )


def _normalize_trade(
    *,
    identity: PostTransitionIdentity,
    event: PumpSwapTradeEvent,
    observed_at: int,
    event_key: str,
    transaction_key: str,
    arrival_index: int,
) -> ObservedPostTransitionTrade:
    if _required(event.pool, "trade pool") != identity.pool:
        raise ValueError("trade pool does not match transition pool")
    learned_at = int(observed_at)
    order_index = int(arrival_index)
    if order_index < 0:
        raise ValueError("arrival_index must be non-negative")
    if learned_at < int(event.timestamp):
        raise ValueError("trade observed_at cannot precede trade timestamp")
    if learned_at < identity.transition_observed_at:
        raise ValueError("trade cannot be observed before transition availability")
    if int(event.timestamp) < identity.transition_chain_time:
        raise ValueError("post-transition trade chain_time precedes transition")

    base_units = _finite_positive(
        int(event.base_amount_raw) / (10 ** identity.opportunity_decimals)
        if identity.opportunity_is_base
        else int(event.base_amount_raw) / (10 ** identity.reference_decimals),
        "base units",
    )
    quote_units = _finite_positive(
        int(event.quote_amount_raw) / (10 ** identity.reference_decimals)
        if identity.opportunity_is_base
        else int(event.quote_amount_raw) / (10 ** identity.opportunity_decimals),
        "quote units",
    )

    if identity.opportunity_is_base:
        opportunity_amount = base_units
        reference_amount = quote_units
    else:
        opportunity_amount = quote_units
        reference_amount = base_units

    price = _finite_positive(
        reference_amount / opportunity_amount,
        "event-implied reference/opportunity ratio",
    )

    role = PumpSwapOpportunityAssetRole(
        opportunity_mint=identity.opportunity_mint,
        reference_mint=identity.reference_mint,
        opportunity_is_base=identity.opportunity_is_base,
    )
    normalized_side = role.normalize_event_side(event.side)

    return ObservedPostTransitionTrade(
        event_key=_required(event_key, "event_key"),
        transaction_key=_required(transaction_key, "transaction_key"),
        observed_at=learned_at,
        arrival_index=order_index,
        chain_time=int(event.timestamp),
        normalized_side=normalized_side,
        wallet_key=_required(event.user, "wallet"),
        opportunity_amount=opportunity_amount,
        reference_amount=reference_amount,
        event_implied_reference_per_opportunity=price,
    )


def _window_summary(rows: list[ObservedPostTransitionTrade]) -> WindowSummary:
    buys = [row for row in rows if row.normalized_side == "buy"]
    sells = [row for row in rows if row.normalized_side == "sell"]
    gross = sum(row.reference_amount for row in rows)
    signed = sum(
        row.reference_amount if row.normalized_side == "buy" else -row.reference_amount
        for row in rows
    )
    by_wallet: dict[str, float] = {}
    for row in rows:
        by_wallet[row.wallet_key] = by_wallet.get(row.wallet_key, 0.0) + row.reference_amount
    top_share = None
    if gross > 0 and by_wallet:
        top_share = 100.0 * max(by_wallet.values()) / gross
    return WindowSummary(
        event_count=len(rows),
        buy_count=len(buys),
        sell_count=len(sells),
        unique_buy_wallet_count=len({row.wallet_key for row in buys}),
        unique_sell_wallet_count=len({row.wallet_key for row in sells}),
        gross_reference_flow=gross,
        signed_reference_flow=signed,
        top_wallet_gross_flow_share_pct=top_share,
    )


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _ratio(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or right <= 0:
        return None
    value = float(left) / float(right)
    return value if math.isfinite(value) else None


class PostTransitionResearchState:
    """Pure causal research state for one PumpSwap lifecycle transition.

    It consumes only raw CreatePool/Buy/Sell event facts already present in the
    repository. No provider route quote, future outcome, future local minimum or
    future local maximum is consulted.
    """

    def __init__(self, identity: PostTransitionIdentity):
        self.identity = identity
        self._trades: dict[str, ObservedPostTransitionTrade] = {}
        self._arrival_owners: dict[int, str] = {}
        self._next_arrival_index = 0

    @classmethod
    def from_create_event(
        cls,
        event: PumpSwapCreatePoolEvent,
        *,
        observed_at: int,
        pump_birth_market_started_at: int | None = None,
        pump_birth_observed_at: int | None = None,
    ) -> "PostTransitionResearchState":
        return cls(
            identity_from_create_event(
                event,
                observed_at=observed_at,
                pump_birth_market_started_at=pump_birth_market_started_at,
                pump_birth_observed_at=pump_birth_observed_at,
            )
        )

    def ingest_trade(
        self,
        event: PumpSwapTradeEvent,
        *,
        observed_at: int,
        event_key: str,
        transaction_key: str,
        arrival_index: int | None = None,
    ) -> bool:
        normalized_event_key = _required(event_key, "event_key")
        existing = self._trades.get(normalized_event_key)
        if existing is not None:
            replay_index = (
                existing.arrival_index
                if arrival_index is None
                else int(arrival_index)
            )
            replay = _normalize_trade(
                identity=self.identity,
                event=event,
                observed_at=observed_at,
                event_key=normalized_event_key,
                transaction_key=transaction_key,
                arrival_index=replay_index,
            )
            if existing != replay:
                raise ValueError("conflicting replay for post-transition trade event")
            return False

        if arrival_index is None:
            order_index = self._next_arrival_index
            self._next_arrival_index += 1
        else:
            order_index = int(arrival_index)
            if order_index < 0:
                raise ValueError("arrival_index must be non-negative")
            self._next_arrival_index = max(
                self._next_arrival_index,
                order_index + 1,
            )

        owner = self._arrival_owners.get(order_index)
        if owner is not None and owner != normalized_event_key:
            raise ValueError("arrival_index already belongs to another event")

        normalized = _normalize_trade(
            identity=self.identity,
            event=event,
            observed_at=observed_at,
            event_key=normalized_event_key,
            transaction_key=transaction_key,
            arrival_index=order_index,
        )
        self._trades[normalized.event_key] = normalized
        self._arrival_owners[order_index] = normalized.event_key
        return True

    def _available_rows(
        self,
        as_of_observed_at: int,
        *,
        max_arrival_index: int | None = None,
    ) -> list[ObservedPostTransitionTrade]:
        cutoff = int(as_of_observed_at)
        if cutoff < self.identity.transition_observed_at:
            return []
        order_cutoff = (
            int(max_arrival_index)
            if max_arrival_index is not None
            else None
        )
        return sorted(
            (
                row
                for row in self._trades.values()
                if (
                    row.observed_at < cutoff
                    or (
                        row.observed_at == cutoff
                        and (
                            order_cutoff is None
                            or row.arrival_index <= order_cutoff
                        )
                    )
                )
            ),
            key=lambda row: (
                row.observed_at,
                row.arrival_index,
                row.chain_time,
                row.event_key,
            ),
        )

    def snapshot(
        self,
        *,
        as_of_observed_at: int,
        max_arrival_index: int | None = None,
    ) -> PostTransitionSnapshot:
        cutoff = int(as_of_observed_at)
        if cutoff < self.identity.transition_observed_at:
            raise ValueError("snapshot precedes transition availability")
        if max_arrival_index is not None and int(max_arrival_index) < 0:
            raise ValueError("max_arrival_index must be non-negative")

        rows = self._available_rows(
            cutoff,
            max_arrival_index=max_arrival_index,
        )
        reference = rows[0] if rows else None
        current = rows[-1] if rows else None

        reference_price = (
            reference.event_implied_reference_per_opportunity
            if reference is not None
            else None
        )
        current_price = (
            current.event_implied_reference_per_opportunity
            if current is not None
            else None
        )

        running_peak = None
        running_peak_observed_at = None
        running_trough = None
        running_trough_observed_at = None
        max_drawdown = None
        max_drawdown_duration = None

        for row in rows:
            price = row.event_implied_reference_per_opportunity
            if running_peak is None or price > running_peak:
                running_peak = price
                running_peak_observed_at = row.observed_at
            if running_trough is None or price < running_trough:
                running_trough = price
                running_trough_observed_at = row.observed_at

            drawdown = 100.0 * (price / running_peak - 1.0)
            if max_drawdown is None or drawdown < max_drawdown:
                max_drawdown = drawdown
                max_drawdown_duration = float(
                    row.observed_at - int(running_peak_observed_at)
                )

        current_return = (
            100.0 * (current_price / reference_price - 1.0)
            if current_price is not None and reference_price is not None
            else None
        )
        trough_return = (
            100.0 * (running_trough / reference_price - 1.0)
            if running_trough is not None and reference_price is not None
            else None
        )
        current_drawdown = (
            100.0 * (current_price / running_peak - 1.0)
            if current_price is not None and running_peak is not None
            else None
        )
        recovery_from_trough = (
            100.0 * (current_price / running_trough - 1.0)
            if current_price is not None and running_trough is not None
            else None
        )
        seconds_since_trough = (
            float(cutoff - int(running_trough_observed_at))
            if running_trough_observed_at is not None
            else None
        )

        recent_start = cutoff - FLOW_WINDOW_SECONDS
        prior_start = cutoff - (2 * FLOW_WINDOW_SECONDS)
        prior_rows = [
            row
            for row in rows
            if prior_start <= row.observed_at < recent_start
        ]
        recent_rows = [
            row
            for row in rows
            if recent_start <= row.observed_at <= cutoff
        ]
        recent = _window_summary(recent_rows)
        prior = _window_summary(prior_rows)
        recent_rates = recent.rates(window_seconds=FLOW_WINDOW_SECONDS)
        prior_rates = prior.rates(window_seconds=FLOW_WINDOW_SECONDS)

        dynamics = {
            "window_seconds": FLOW_WINDOW_SECONDS,
            "event_rate_delta_per_s": _difference(
                recent_rates["event_rate_per_s"],
                prior_rates["event_rate_per_s"],
            ),
            "buy_rate_delta_per_s": _difference(
                recent_rates["buy_rate_per_s"],
                prior_rates["buy_rate_per_s"],
            ),
            "sell_rate_delta_per_s": _difference(
                recent_rates["sell_rate_per_s"],
                prior_rates["sell_rate_per_s"],
            ),
            "gross_reference_flow_rate_delta_per_s": _difference(
                recent_rates["gross_reference_flow_rate_per_s"],
                prior_rates["gross_reference_flow_rate_per_s"],
            ),
            "signed_reference_flow_rate_delta_per_s": _difference(
                recent_rates["signed_reference_flow_rate_per_s"],
                prior_rates["signed_reference_flow_rate_per_s"],
            ),
            "event_rate_ratio_recent_over_prior": _ratio(
                recent_rates["event_rate_per_s"],
                prior_rates["event_rate_per_s"],
            ),
            "buy_rate_ratio_recent_over_prior": _ratio(
                recent_rates["buy_rate_per_s"],
                prior_rates["buy_rate_per_s"],
            ),
            "gross_reference_flow_rate_ratio_recent_over_prior": _ratio(
                recent_rates["gross_reference_flow_rate_per_s"],
                prior_rates["gross_reference_flow_rate_per_s"],
            ),
            "unique_buy_wallet_delta": (
                recent.unique_buy_wallet_count - prior.unique_buy_wallet_count
            ),
            "top_wallet_gross_flow_share_delta_pct_points": _difference(
                recent.top_wallet_gross_flow_share_pct,
                prior.top_wallet_gross_flow_share_pct,
            ),
        }

        pullback_observed = (
            trough_return is not None and trough_return < 0.0
        )
        dynamics["both_flow_windows_observed"] = (
            prior.event_count > 0 and recent.event_count > 0
        )
        structural_reacceleration = bool(
            pullback_observed
            and recovery_from_trough is not None
            and recovery_from_trough > 0.0
            and dynamics["both_flow_windows_observed"]
            and dynamics["signed_reference_flow_rate_delta_per_s"] is not None
            and dynamics["signed_reference_flow_rate_delta_per_s"] > 0.0
        )

        recent_payload = {
            **asdict(recent),
            **recent_rates,
        }
        prior_payload = {
            **asdict(prior),
            **prior_rates,
        }

        return PostTransitionSnapshot(
            version=VERSION,
            inference_role=INFERENCE_ROLE,
            as_of_observed_at=cutoff,
            as_of_arrival_index=(
                int(max_arrival_index)
                if max_arrival_index is not None
                else None
            ),
            identity=asdict(self.identity),
            transition_semantics=(
                "pumpswap_create_pool_transition_anchor_not_proven_pump_graduation"
            ),
            trade_count_available=len(rows),
            reference_trade_event_key=(reference.event_key if reference else None),
            reference_price=reference_price,
            current_trade_event_key=(current.event_key if current else None),
            current_price=current_price,
            current_return_from_reference_pct=current_return,
            running_peak_price=running_peak,
            running_trough_price=running_trough,
            running_trough_return_from_reference_pct=trough_return,
            current_drawdown_from_running_peak_pct=current_drawdown,
            max_drawdown_from_running_peak_pct=max_drawdown,
            max_drawdown_duration_seconds=max_drawdown_duration,
            current_recovery_from_running_trough_pct=recovery_from_trough,
            seconds_since_running_trough=seconds_since_trough,
            seconds_since_transition_observed=float(
                cutoff - self.identity.transition_observed_at
            ),
            seconds_since_transition_chain=(
                float(current.chain_time - self.identity.transition_chain_time)
                if current is not None
                else None
            ),
            pullback_observed=pullback_observed,
            recent_window=recent_payload,
            prior_window=prior_payload,
            dynamics=dynamics,
            structural_reacceleration_candidate=structural_reacceleration,
            provider_quote_used=False,
            future_outcome_used=False,
            future_extrema_used=False,
        )

    def snapshots_after_each_trade(self) -> list[PostTransitionSnapshot]:
        ordered = sorted(
            self._trades.values(),
            key=lambda row: (
                row.observed_at,
                row.arrival_index,
                row.chain_time,
                row.event_key,
            ),
        )
        return [
            self.snapshot(
                as_of_observed_at=row.observed_at,
                max_arrival_index=row.arrival_index,
            )
            for row in ordered
        ]
