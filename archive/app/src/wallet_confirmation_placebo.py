import statistics
from dataclasses import dataclass

from src.opportunity_intelligence import WalletActionObservation


@dataclass(frozen=True)
class WalletCohort:
    name: str
    addresses: tuple[str, ...]
    role: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("cohort name cannot be empty")
        normalized = tuple(address.strip() for address in self.addresses)
        if not normalized or any(not address for address in normalized):
            raise ValueError("cohort must contain non-empty addresses")
        if len(set(normalized)) != len(normalized):
            raise ValueError("cohort addresses must be unique")
        if self.role not in {"target", "placebo"}:
            raise ValueError("cohort role must be target or placebo")


@dataclass(frozen=True)
class ConfirmationPolicy:
    window_seconds: int = 300
    min_unique_buy_wallets: int = 2

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.min_unique_buy_wallets <= 0:
            raise ValueError("min_unique_buy_wallets must be positive")


@dataclass(frozen=True)
class WalletConfirmationEvent:
    token_mint: str
    as_of: int
    cohort_name: str
    cohort_role: str
    window_seconds: int
    min_unique_buy_wallets: int
    buy_action_count: int
    unique_buy_wallet_count: int
    first_buy_observed_at: int | None
    latest_buy_observed_at: int | None
    confirmed: bool


@dataclass(frozen=True)
class TokenOutcomeObservation:
    token_mint: str
    as_of: int
    horizon_minutes: int
    status: str
    return_pct: float | None = None

    def __post_init__(self) -> None:
        if not self.token_mint.strip():
            raise ValueError("token_mint cannot be empty")
        if self.as_of < 0 or self.horizon_minutes <= 0:
            raise ValueError("invalid outcome timing")
        if self.status not in {"completed", "failed", "pending"}:
            raise ValueError("outcome status must be completed, failed or pending")
        if self.status == "completed" and self.return_pct is None:
            raise ValueError("completed outcome requires return_pct")
        if self.status != "completed" and self.return_pct is not None:
            raise ValueError("non-completed outcome cannot have return_pct")


@dataclass(frozen=True)
class ConfirmationOutcomeSummary:
    cohort_name: str
    cohort_role: str
    horizon_minutes: int
    confirmed_event_count: int
    completed_count: int
    failed_count: int
    pending_or_missing_count: int
    coverage_pct: float
    mean_return_pct: float | None
    median_return_pct: float | None
    positive_share_pct: float | None
    rally_20_share_pct: float | None
    crash_25_share_pct: float | None


@dataclass(frozen=True)
class PlaceboComparison:
    target: ConfirmationOutcomeSummary
    placebos: tuple[ConfirmationOutcomeSummary, ...]
    target_minus_median_placebo_mean_return_pct: float | None
    target_minus_median_placebo_median_return_pct: float | None
    target_minus_median_placebo_positive_share_pct: float | None
    interpretation_label: str


def validate_cohort_design(
    target: WalletCohort,
    placebos: tuple[WalletCohort, ...] | list[WalletCohort],
    *,
    require_equal_size: bool = True,
) -> None:
    """Validate structural placebo controls without pretending to solve matching quality.

    Activity/holding/DEX matching must be frozen from a pre-period dataset and documented by
    the caller. This function only enforces properties that are objective at this layer:
    roles, unique names, disjoint wallets and optionally equal cohort size.
    """

    if target.role != "target":
        raise ValueError("target cohort must have role=target")
    if not placebos:
        raise ValueError("at least one placebo cohort is required")
    names = {target.name}
    used = set(target.addresses)
    for placebo in placebos:
        if placebo.role != "placebo":
            raise ValueError("placebo cohorts must have role=placebo")
        if placebo.name in names:
            raise ValueError("cohort names must be unique")
        names.add(placebo.name)
        overlap = used.intersection(placebo.addresses)
        if overlap:
            raise ValueError("target/placebo cohorts must be wallet-disjoint")
        used.update(placebo.addresses)
        if require_equal_size and len(placebo.addresses) != len(target.addresses):
            raise ValueError("placebo cohorts must match target wallet count")


def build_wallet_confirmation_event(
    observations: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    *,
    token_mint: str,
    as_of: int,
    cohort: WalletCohort,
    policy: ConfirmationPolicy | None = None,
) -> WalletConfirmationEvent:
    """Build one causal confirmation event using observed_at, never future chain history."""

    policy = policy or ConfirmationPolicy()
    if not token_mint.strip() or as_of < 0:
        raise ValueError("invalid token/as_of")
    start = max(0, as_of - policy.window_seconds)
    addresses = set(cohort.addresses)
    buys: list[WalletActionObservation] = []
    for item in observations:
        if item.observed_at < item.chain_time:
            raise ValueError("wallet observed_at cannot be earlier than chain_time")
        if item.token_mint != token_mint or item.side != "buy":
            continue
        if item.address not in addresses:
            continue
        if not start <= item.observed_at <= as_of:
            continue
        buys.append(item)

    unique = {item.address for item in buys}
    return WalletConfirmationEvent(
        token_mint=token_mint,
        as_of=as_of,
        cohort_name=cohort.name,
        cohort_role=cohort.role,
        window_seconds=policy.window_seconds,
        min_unique_buy_wallets=policy.min_unique_buy_wallets,
        buy_action_count=len(buys),
        unique_buy_wallet_count=len(unique),
        first_buy_observed_at=min((item.observed_at for item in buys), default=None),
        latest_buy_observed_at=max((item.observed_at for item in buys), default=None),
        confirmed=len(unique) >= policy.min_unique_buy_wallets,
    )


def _share(values: list[float], predicate) -> float | None:
    if not values:
        return None
    return 100.0 * sum(bool(predicate(value)) for value in values) / len(values)


def summarize_confirmation_outcomes(
    events: list[WalletConfirmationEvent] | tuple[WalletConfirmationEvent, ...],
    outcomes: list[TokenOutcomeObservation] | tuple[TokenOutcomeObservation, ...],
    *,
    cohort_name: str,
    horizon_minutes: int,
) -> ConfirmationOutcomeSummary:
    if horizon_minutes <= 0:
        raise ValueError("horizon_minutes must be positive")
    eligible = [
        event
        for event in events
        if event.cohort_name == cohort_name and event.confirmed
    ]
    roles = {event.cohort_role for event in eligible}
    if len(roles) > 1:
        raise ValueError("one cohort name cannot mix roles")
    role = next(iter(roles), "unknown")

    outcome_map = {
        (item.token_mint, item.as_of, item.horizon_minutes): item
        for item in outcomes
        if item.horizon_minutes == horizon_minutes
    }
    completed: list[float] = []
    failed = pending_or_missing = 0
    for event in eligible:
        outcome = outcome_map.get((event.token_mint, event.as_of, horizon_minutes))
        if outcome is None or outcome.status == "pending":
            pending_or_missing += 1
        elif outcome.status == "failed":
            failed += 1
        else:
            completed.append(float(outcome.return_pct))

    denominator = len(eligible)
    return ConfirmationOutcomeSummary(
        cohort_name=cohort_name,
        cohort_role=role,
        horizon_minutes=horizon_minutes,
        confirmed_event_count=denominator,
        completed_count=len(completed),
        failed_count=failed,
        pending_or_missing_count=pending_or_missing,
        coverage_pct=100.0 * len(completed) / denominator if denominator else 0.0,
        mean_return_pct=statistics.fmean(completed) if completed else None,
        median_return_pct=statistics.median(completed) if completed else None,
        positive_share_pct=_share(completed, lambda value: value > 0),
        rally_20_share_pct=_share(completed, lambda value: value >= 20),
        crash_25_share_pct=_share(completed, lambda value: value <= -25),
    )


def _median_available(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return statistics.median(present) if present else None


def _delta(target: float | None, baseline: float | None) -> float | None:
    if target is None or baseline is None:
        return None
    return target - baseline


def compare_target_to_placebos(
    events: list[WalletConfirmationEvent] | tuple[WalletConfirmationEvent, ...],
    outcomes: list[TokenOutcomeObservation] | tuple[TokenOutcomeObservation, ...],
    *,
    target_cohort_name: str,
    placebo_cohort_names: tuple[str, ...] | list[str],
    horizon_minutes: int,
) -> PlaceboComparison:
    if not placebo_cohort_names:
        raise ValueError("at least one placebo cohort name is required")
    if target_cohort_name in set(placebo_cohort_names):
        raise ValueError("target cohort cannot also be a placebo")

    target = summarize_confirmation_outcomes(
        events,
        outcomes,
        cohort_name=target_cohort_name,
        horizon_minutes=horizon_minutes,
    )
    placebos = tuple(
        summarize_confirmation_outcomes(
            events,
            outcomes,
            cohort_name=name,
            horizon_minutes=horizon_minutes,
        )
        for name in placebo_cohort_names
    )
    placebo_mean = _median_available([item.mean_return_pct for item in placebos])
    placebo_median = _median_available([item.median_return_pct for item in placebos])
    placebo_positive = _median_available([item.positive_share_pct for item in placebos])

    if target.completed_count == 0 or not any(item.completed_count for item in placebos):
        label = "NO_COMPARABLE_OUTCOMES"
    elif target.coverage_pct < 80 or any(
        item.confirmed_event_count and item.coverage_pct < 80 for item in placebos
    ):
        label = "DESCRIPTIVE_LOW_COVERAGE"
    else:
        label = "DESCRIPTIVE_PLACEBO_COMPARISON"

    return PlaceboComparison(
        target=target,
        placebos=placebos,
        target_minus_median_placebo_mean_return_pct=_delta(
            target.mean_return_pct, placebo_mean
        ),
        target_minus_median_placebo_median_return_pct=_delta(
            target.median_return_pct, placebo_median
        ),
        target_minus_median_placebo_positive_share_pct=_delta(
            target.positive_share_pct, placebo_positive
        ),
        interpretation_label=label,
    )
