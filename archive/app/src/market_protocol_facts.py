"""Causal protocol-aware market facts for Pump and PumpSwap.

This module intentionally exposes facts, provenance and missingness only. It does
not score opportunities, recommend trades, infer migration from PumpSwap activity,
or backfill evidence that was unavailable at ``as_of``.

``as_of`` is the local evidence-availability clock. ``chain_time`` is an independent
on-chain ordering clock and is never compared to ``as_of`` as a causal gate.
"""

from dataclasses import dataclass
from typing import Iterable


MARKET_PROTOCOL_FACTS_VERSION = "market_protocol_facts_v1_clock_domains"

_ALLOWED_MIGRATION_EVIDENCE_KINDS = frozenset(
    {
        "pump_migrate_instruction",
        "pump_migrate_event",
        "validated_migration_link",
    }
)


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_clock(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_optional_nonnegative(value: int | None, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative integer when present")


@dataclass(frozen=True)
class PumpCurveStateObservation:
    """Point-in-time Pump bonding-curve account/event state."""

    token_mint: str
    chain_time: int
    observed_at: int
    evidence_key: str
    source: str
    complete: bool | None = None
    quote_mint: str | None = None
    virtual_token_reserves: int | None = None
    virtual_quote_reserves: int | None = None
    real_token_reserves: int | None = None
    real_quote_reserves: int | None = None
    token_total_supply: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.token_mint, "token_mint")
        _require_nonempty(self.evidence_key, "evidence_key")
        _require_nonempty(self.source, "source")
        _require_clock(self.chain_time, "chain_time")
        _require_clock(self.observed_at, "observed_at")
        if self.complete is not None and not isinstance(self.complete, bool):
            raise ValueError("complete must be bool or None")
        if self.quote_mint is not None:
            _require_nonempty(self.quote_mint, "quote_mint")
        for name in (
            "virtual_token_reserves",
            "virtual_quote_reserves",
            "real_token_reserves",
            "real_quote_reserves",
            "token_total_supply",
        ):
            _require_optional_nonnegative(getattr(self, name), name)

    def is_available_at(self, as_of: int) -> bool:
        return self.observed_at <= as_of


@dataclass(frozen=True)
class PumpSwapPoolObservation:
    """Point-in-time PumpSwap pool facts."""

    token_mint: str
    pool: str
    chain_time: int
    observed_at: int
    evidence_key: str
    source: str
    base_mint: str | None = None
    quote_mint: str | None = None
    pool_index: int | None = None
    pool_base_token_reserves: int | None = None
    pool_quote_token_reserves: int | None = None
    virtual_quote_reserves: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.token_mint, "token_mint")
        _require_nonempty(self.pool, "pool")
        _require_nonempty(self.evidence_key, "evidence_key")
        _require_nonempty(self.source, "source")
        _require_clock(self.chain_time, "chain_time")
        _require_clock(self.observed_at, "observed_at")
        if self.base_mint is not None:
            _require_nonempty(self.base_mint, "base_mint")
        if self.quote_mint is not None:
            _require_nonempty(self.quote_mint, "quote_mint")
        _require_optional_nonnegative(self.pool_index, "pool_index")
        _require_optional_nonnegative(
            self.pool_base_token_reserves, "pool_base_token_reserves"
        )
        _require_optional_nonnegative(
            self.pool_quote_token_reserves, "pool_quote_token_reserves"
        )
        if self.virtual_quote_reserves is not None and (
            not isinstance(self.virtual_quote_reserves, int)
            or isinstance(self.virtual_quote_reserves, bool)
        ):
            raise ValueError("virtual_quote_reserves must be an integer when present")
        if (
            self.pool_quote_token_reserves is not None
            and self.virtual_quote_reserves is not None
            and self.pool_quote_token_reserves + self.virtual_quote_reserves < 0
        ):
            raise ValueError("effective quote reserves cannot be negative")

    def is_available_at(self, as_of: int) -> bool:
        return self.observed_at <= as_of

    @property
    def effective_quote_reserves(self) -> int | None:
        if self.pool_quote_token_reserves is None or self.virtual_quote_reserves is None:
            return None
        return self.pool_quote_token_reserves + self.virtual_quote_reserves


@dataclass(frozen=True)
class PumpMigrationEvidence:
    """Explicit Pump -> PumpSwap lineage evidence."""

    token_mint: str
    pool: str
    pool_index: int
    chain_time: int
    observed_at: int
    evidence_key: str
    source: str
    evidence_kind: str

    def __post_init__(self) -> None:
        _require_nonempty(self.token_mint, "token_mint")
        _require_nonempty(self.pool, "pool")
        _require_nonempty(self.evidence_key, "evidence_key")
        _require_nonempty(self.source, "source")
        _require_clock(self.chain_time, "chain_time")
        _require_clock(self.observed_at, "observed_at")
        _require_optional_nonnegative(self.pool_index, "pool_index")
        if self.evidence_kind not in _ALLOWED_MIGRATION_EVIDENCE_KINDS:
            raise ValueError(f"unsupported migration evidence_kind: {self.evidence_kind}")

    def is_available_at(self, as_of: int) -> bool:
        return self.observed_at <= as_of


@dataclass(frozen=True)
class MarketProtocolFactsV0:
    method_version: str
    token_mint: str
    as_of: int
    lifecycle_label: str

    pump_activity_observed: bool
    pump_curve_complete: bool | None
    pump_latest_chain_time: int | None
    pump_latest_observed_at: int | None
    pump_quote_mint: str | None
    pump_virtual_token_reserves: int | None
    pump_virtual_quote_reserves: int | None
    pump_real_token_reserves: int | None
    pump_real_quote_reserves: int | None
    pump_token_total_supply: int | None

    pumpswap_activity_observed: bool
    pumpswap_latest_chain_time: int | None
    pumpswap_latest_observed_at: int | None
    pumpswap_pool: str | None
    pumpswap_pool_index: int | None
    pumpswap_base_mint: str | None
    pumpswap_quote_mint: str | None
    pumpswap_pool_base_token_reserves: int | None
    pumpswap_pool_quote_token_reserves: int | None
    pumpswap_virtual_quote_reserves: int | None
    pumpswap_effective_quote_reserves: int | None

    canonical_migration_proven: bool
    migration_pool: str | None
    migration_evidence_kind: str | None
    migration_chain_time: int | None
    migration_observed_at: int | None

    provenance_keys: tuple[str, ...]
    data_quality_flags: tuple[str, ...]


def _causal_for_token(
    rows: Iterable[PumpCurveStateObservation | PumpSwapPoolObservation | PumpMigrationEvidence],
    *,
    token_mint: str,
    as_of: int,
) -> list[PumpCurveStateObservation | PumpSwapPoolObservation | PumpMigrationEvidence]:
    return [
        row
        for row in rows
        if row.token_mint == token_mint and row.is_available_at(as_of)
    ]


def _latest(rows):
    if not rows:
        return None
    return max(rows, key=lambda row: (row.chain_time, row.observed_at, row.evidence_key))


def _pump_complete_state(
    rows: list[PumpCurveStateObservation],
) -> tuple[bool | None, bool]:
    explicit = sorted(
        (row for row in rows if row.complete is not None),
        key=lambda row: (row.chain_time, row.observed_at, row.evidence_key),
    )
    if not explicit:
        return None, False

    saw_true = False
    regression = False
    for row in explicit:
        if row.complete is True:
            saw_true = True
        elif saw_true:
            regression = True

    if regression:
        return None, True
    return bool(explicit[-1].complete), False


def build_market_protocol_facts_v0(
    *,
    token_mint: str,
    as_of: int,
    pump_curve_observations: Iterable[PumpCurveStateObservation] = (),
    pumpswap_pool_observations: Iterable[PumpSwapPoolObservation] = (),
    migration_evidence: Iterable[PumpMigrationEvidence] = (),
) -> MarketProtocolFactsV0:
    """Build immutable protocol facts known at local ``as_of``.

    The builder filters by exact mint and local observation availability. On-chain
    timestamps order on-chain state but are not compared to local ``as_of`` as a
    causal gate. Later-arriving evidence remains invisible to earlier snapshots.
    """

    _require_nonempty(token_mint, "token_mint")
    _require_clock(as_of, "as_of")

    pump_rows = [
        row
        for row in _causal_for_token(
            pump_curve_observations, token_mint=token_mint, as_of=as_of
        )
        if isinstance(row, PumpCurveStateObservation)
    ]
    swap_rows = [
        row
        for row in _causal_for_token(
            pumpswap_pool_observations, token_mint=token_mint, as_of=as_of
        )
        if isinstance(row, PumpSwapPoolObservation)
    ]
    migration_rows = [
        row
        for row in _causal_for_token(
            migration_evidence, token_mint=token_mint, as_of=as_of
        )
        if isinstance(row, PumpMigrationEvidence)
    ]

    pump_latest = _latest(pump_rows)
    swap_latest = _latest(swap_rows)
    pump_complete, pump_complete_conflict = _pump_complete_state(pump_rows)

    canonical_rows = [row for row in migration_rows if row.pool_index == 0]
    canonical_migration = _latest(canonical_rows)
    canonical_migration_proven = canonical_migration is not None

    if canonical_migration_proven:
        lifecycle_label = "PUMPSWAP_MIGRATED_CANONICAL"
    elif swap_rows:
        lifecycle_label = "PUMPSWAP_ACTIVE_UNPROVEN_LINEAGE"
    elif pump_complete is True:
        lifecycle_label = "PUMP_CURVE_COMPLETE"
    elif pump_rows:
        lifecycle_label = "PUMP_BONDING_ACTIVE"
    else:
        lifecycle_label = "UNKNOWN"

    flags: list[str] = []
    all_rows = (*pump_rows, *swap_rows, *migration_rows)
    if any(row.chain_time > as_of for row in all_rows):
        flags.append("chain_clock_ahead_of_local_snapshot_clock_observed")

    if not pump_rows:
        flags.append("pump_curve_state_not_observed")
    else:
        if pump_complete is None:
            flags.append("pump_curve_complete_missing")
        if pump_complete_conflict:
            flags.append("pump_curve_complete_regression_conflict")
        pump_reserve_values = (
            pump_latest.virtual_token_reserves,
            pump_latest.virtual_quote_reserves,
            pump_latest.real_token_reserves,
            pump_latest.real_quote_reserves,
        )
        if any(value is None for value in pump_reserve_values):
            flags.append("pump_reserves_partial")

    if swap_rows:
        if (
            swap_latest.pool_base_token_reserves is None
            or swap_latest.pool_quote_token_reserves is None
        ):
            flags.append("pumpswap_raw_reserves_partial")
        if swap_latest.virtual_quote_reserves is None:
            flags.append("pumpswap_virtual_quote_reserves_missing")
        if not canonical_migration_proven:
            flags.append("pumpswap_lineage_unproven")

    if migration_rows and not canonical_migration_proven:
        flags.append("migration_evidence_noncanonical_pool_index")

    provenance = tuple(
        sorted({row.evidence_key for row in all_rows})
    )

    return MarketProtocolFactsV0(
        method_version=MARKET_PROTOCOL_FACTS_VERSION,
        token_mint=token_mint,
        as_of=as_of,
        lifecycle_label=lifecycle_label,
        pump_activity_observed=bool(pump_rows),
        pump_curve_complete=pump_complete,
        pump_latest_chain_time=(pump_latest.chain_time if pump_latest else None),
        pump_latest_observed_at=(pump_latest.observed_at if pump_latest else None),
        pump_quote_mint=(pump_latest.quote_mint if pump_latest else None),
        pump_virtual_token_reserves=(pump_latest.virtual_token_reserves if pump_latest else None),
        pump_virtual_quote_reserves=(pump_latest.virtual_quote_reserves if pump_latest else None),
        pump_real_token_reserves=(pump_latest.real_token_reserves if pump_latest else None),
        pump_real_quote_reserves=(pump_latest.real_quote_reserves if pump_latest else None),
        pump_token_total_supply=(pump_latest.token_total_supply if pump_latest else None),
        pumpswap_activity_observed=bool(swap_rows),
        pumpswap_latest_chain_time=(swap_latest.chain_time if swap_latest else None),
        pumpswap_latest_observed_at=(swap_latest.observed_at if swap_latest else None),
        pumpswap_pool=(swap_latest.pool if swap_latest else None),
        pumpswap_pool_index=(swap_latest.pool_index if swap_latest else None),
        pumpswap_base_mint=(swap_latest.base_mint if swap_latest else None),
        pumpswap_quote_mint=(swap_latest.quote_mint if swap_latest else None),
        pumpswap_pool_base_token_reserves=(swap_latest.pool_base_token_reserves if swap_latest else None),
        pumpswap_pool_quote_token_reserves=(swap_latest.pool_quote_token_reserves if swap_latest else None),
        pumpswap_virtual_quote_reserves=(swap_latest.virtual_quote_reserves if swap_latest else None),
        pumpswap_effective_quote_reserves=(swap_latest.effective_quote_reserves if swap_latest else None),
        canonical_migration_proven=canonical_migration_proven,
        migration_pool=(canonical_migration.pool if canonical_migration else None),
        migration_evidence_kind=(canonical_migration.evidence_kind if canonical_migration else None),
        migration_chain_time=(canonical_migration.chain_time if canonical_migration else None),
        migration_observed_at=(canonical_migration.observed_at if canonical_migration else None),
        provenance_keys=provenance,
        data_quality_flags=tuple(sorted(set(flags))),
    )
