from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

from benchmarks.market_first_live_discovery_v0 import LIVE_DISCOVERY_VERSION
from benchmarks.pumpswap_identity_bootstrap_v0.bootstrap import PASS_CLASSIFICATION as BOOTSTRAP_PASS
from src.market_activity_discovery_run_v0 import (
    MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
)
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


DISCOVERY_DURATION_SECONDS = MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS
if DISCOVERY_DURATION_SECONDS != 6 * 60 * 60:  # fail import-time if frozen protocol drifts
    raise RuntimeError("Market Activity Discovery V0 admission duration is no longer six hours")

PASS_CLASSIFICATION = "PASS_MARKET_FIRST_LIVE_DISCOVERY_V0"
FAIL_CLASSIFICATION = "FAIL_MARKET_FIRST_LIVE_DISCOVERY_V0"
SOURCE_SCOPE = "helius_standard_wss_pump_pumpswap_logs"


@dataclass(frozen=True)
class BootstrapEvidenceV0:
    report_path: Path
    run_id: str
    identities_path: Path
    identities: tuple[PumpSwapPoolIdentityObservation, ...]
    unresolved_pool_count: int
    observed_pool_count: int
    decoded_identity_count: int


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSON object required at {path}:{line_number}")
        rows.append(row)
    return rows


def _resolve_artifact_path(report_path: Path, declared: object) -> Path:
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("bootstrap identities artifact path is missing")
    candidate = Path(declared)
    if candidate.exists():
        return candidate
    sibling = report_path.parent / candidate.name
    if sibling.exists():
        return sibling
    raise ValueError(f"bootstrap identities artifact not found: {declared}")


def _load_identity_rows(path: Path) -> tuple[PumpSwapPoolIdentityObservation, ...]:
    identities: list[PumpSwapPoolIdentityObservation] = []
    seen: set[tuple[str, int, str]] = set()
    for row in _jsonl(path):
        if row.get("type") != "pumpswap_pool_identity_observation":
            continue
        identity = PumpSwapPoolIdentityObservation(
            pool=str(row["pool"]),
            base_mint=str(row["base_mint"]),
            quote_mint=str(row["quote_mint"]),
            observed_wall_ns=int(row["observed_wall_ns"]),
            observed_slot=int(row["observed_slot"]),
            evidence_key=str(row["evidence_key"]),
            source=str(row["source"]),
        )
        key = (identity.pool, identity.observed_wall_ns, identity.evidence_key)
        if key in seen:
            raise ValueError("duplicate bootstrap identity observation")
        seen.add(key)
        identities.append(identity)
    identities.sort(key=lambda item: (item.observed_wall_ns, item.pool, item.evidence_key))
    return tuple(identities)


def load_bootstrap_evidence_v0(report_path: Path) -> BootstrapEvidenceV0:
    path = Path(report_path)
    report = _json(path)
    if report.get("classification") != BOOTSTRAP_PASS or report.get("valid_bootstrap") is not True:
        raise ValueError("PumpSwap identity bootstrap must be a real PASS before six-hour discovery")
    if report.get("chain_complete_coverage_claimed") is not False:
        raise ValueError("bootstrap cannot claim chain-complete coverage")
    artifacts = report.get("artifacts")
    identity_summary = report.get("identity")
    if not isinstance(artifacts, dict) or not isinstance(identity_summary, dict):
        raise ValueError("bootstrap report missing artifacts/identity summary")
    identities_path = _resolve_artifact_path(path, artifacts.get("identities"))
    identities = _load_identity_rows(identities_path)
    declared_count = int(identity_summary.get("decoded_identity_count") or 0)
    if declared_count != len(identities):
        raise ValueError("bootstrap identity artifact count does not match report")
    if not identities:
        raise ValueError("bootstrap PASS contains no causal PumpSwap identities")
    run_id = str(report.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("bootstrap run_id is missing")
    return BootstrapEvidenceV0(
        report_path=path,
        run_id=run_id,
        identities_path=identities_path,
        identities=identities,
        unresolved_pool_count=int(identity_summary.get("unresolved_pool_count") or 0),
        observed_pool_count=int(identity_summary.get("observed_pool_count") or 0),
        decoded_identity_count=declared_count,
    )


def validate_bootstrap_before_discovery_start_v0(
    evidence: BootstrapEvidenceV0,
    *,
    discovery_start_wall_ns: int,
) -> None:
    start = int(discovery_start_wall_ns)
    if start <= 0:
        raise ValueError("discovery_start_wall_ns must be positive")
    late = tuple(
        item.evidence_key
        for item in evidence.identities
        if item.observed_wall_ns >= start
    )
    if late:
        raise ValueError(
            "bootstrap identity was not available before discovery start: " + ",".join(late[:5])
        )


def event_is_inside_discovery_window_v0(
    first_received_wall_ns: int,
    *,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
) -> bool:
    observed = int(first_received_wall_ns)
    start = int(discovery_start_wall_ns)
    close = int(discovery_close_wall_ns)
    if observed <= 0 or start <= 0 or close <= start:
        raise ValueError("invalid discovery wall-clock window")
    return start <= observed < close


def classify_live_discovery_v0(gates: dict[str, bool]) -> str:
    return PASS_CLASSIFICATION if gates and all(bool(value) for value in gates.values()) else FAIL_CLASSIFICATION


def identities_available_before_v0(
    identities: Sequence[PumpSwapPoolIdentityObservation],
    *,
    pool: str,
    event_wall_ns: int,
) -> tuple[PumpSwapPoolIdentityObservation, ...]:
    return tuple(
        item
        for item in identities
        if item.pool == pool and item.is_available_by_wall_ns(int(event_wall_ns))
    )
