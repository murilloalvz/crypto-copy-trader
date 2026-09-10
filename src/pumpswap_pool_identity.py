"""Causal PumpSwap pool identity observations.

Pool identity is modeled separately from point-in-time reserve state.  A decoded
Pool account can establish exact base/quote mint identity once the account response
has actually been observed locally, without inventing a chain timestamp for the
account snapshot.  Consumers must compare ``observed_wall_ns`` against the event's
local receive clock; later observations must never backfill earlier events.
"""

from __future__ import annotations

from dataclasses import dataclass


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_nonnegative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True)
class PumpSwapPoolIdentityObservation:
    """Exact PumpSwap pool identity available at a local observation time.

    ``observed_slot`` records the RPC context slot of the account snapshot.  It is
    provenance, not a substitute for chain_time.  ``observed_wall_ns`` is the causal
    availability clock used to prevent future account lookups from backfilling an
    earlier market event.
    """

    pool: str
    base_mint: str
    quote_mint: str
    observed_wall_ns: int
    observed_slot: int
    evidence_key: str
    source: str

    def __post_init__(self) -> None:
        for name in ("pool", "base_mint", "quote_mint", "evidence_key", "source"):
            _require_nonempty(getattr(self, name), name)
        _require_nonnegative_int(self.observed_wall_ns, "observed_wall_ns")
        _require_nonnegative_int(self.observed_slot, "observed_slot")

    @property
    def token_mint(self) -> str:
        return self.base_mint

    @property
    def observed_at(self) -> int:
        return self.observed_wall_ns // 1_000_000_000

    def is_available_by_wall_ns(self, as_of_wall_ns: int) -> bool:
        _require_nonnegative_int(as_of_wall_ns, "as_of_wall_ns")
        return self.observed_wall_ns <= as_of_wall_ns
