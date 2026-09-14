"""Pons V2 factory discovery for Robinhood Launch Burst V0.

The production integration has already seen documentation/source drift around the
V2 factory address.  This module therefore treats addresses as versioned evidence,
not as an eternal constant.  Discovery is read-only and uses two facts:

* runtime bytecode exists at the candidate address; and
* recent ``TokenLaunched`` logs are emitted by that address.

If multiple candidates are active, V0 refuses to merge them.  They must be
captured as separate factory strata or explicitly selected by the operator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


PRODUCTION_OBSERVED_FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
REPO_MAIN_ANNOUNCED_FACTORY = "0x7e1eabd52ae29598e6483f72dcf1a70b14284db8"


@dataclass(frozen=True)
class FactoryCandidateV0:
    name: str
    address: str
    provenance: str


FACTORY_CANDIDATES_V0 = (
    FactoryCandidateV0(
        "production_observed",
        PRODUCTION_OBSERVED_FACTORY,
        "live-chain integrations + explorer activity observed 2026-09; do not infer permanence",
    ),
    FactoryCandidateV0(
        "repo_main_announced",
        REPO_MAIN_ANNOUNCED_FACTORY,
        "ponsdotdev/ponsfamily main README observed 2026-09-14; requires live-chain confirmation",
    ),
)


@dataclass(frozen=True)
class FactoryProbeV0:
    name: str
    address: str
    provenance: str
    code_present: bool
    code_size_bytes: int
    recent_launch_count: int
    latest_launch_block: int | None
    lookback_from_block: int
    lookback_to_block: int
    probe_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_address(value: str) -> str:
    value = str(value).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid EVM address: {value!r}")
    int(value[2:], 16)
    return value


def _code_size(code: object) -> int:
    if not isinstance(code, str) or not code.startswith("0x"):
        return 0
    body = code[2:]
    if not body or set(body) <= {"0"}:
        return 0
    try:
        bytes.fromhex(body)
    except ValueError:
        return 0
    return len(body) // 2


def probe_factory_v0(
    client,
    *,
    candidate: FactoryCandidateV0,
    token_launched_topic0: str,
    latest_block: int,
    lookback_blocks: int,
) -> FactoryProbeV0:
    if lookback_blocks <= 0:
        raise ValueError("lookback_blocks must be positive")
    address = _norm_address(candidate.address)
    start = max(0, latest_block - lookback_blocks + 1)
    try:
        code = client.call("eth_getCode", [address, "latest"])
        size = _code_size(code)
        query = {
            "fromBlock": hex(start),
            "toBlock": hex(latest_block),
            "address": address,
            "topics": [token_launched_topic0],
        }
        rows = client.call("eth_getLogs", [query])
        if not isinstance(rows, list):
            raise ValueError("eth_getLogs did not return a list")
        blocks = []
        for row in rows:
            if isinstance(row, dict) and row.get("blockNumber") is not None:
                blocks.append(int(str(row["blockNumber"]), 16))
        return FactoryProbeV0(
            candidate.name,
            address,
            candidate.provenance,
            size > 0,
            size,
            len(rows),
            max(blocks) if blocks else None,
            start,
            latest_block,
            None,
        )
    except Exception as exc:
        return FactoryProbeV0(
            candidate.name,
            address,
            candidate.provenance,
            False,
            0,
            0,
            None,
            start,
            latest_block,
            f"{type(exc).__name__}:{exc}",
        )


def discover_factory_v0(
    client,
    *,
    token_launched_topic0: str,
    lookback_blocks: int = 5_000,
    override_address: str | None = None,
) -> dict:
    latest = client.block_number()
    if override_address:
        address = _norm_address(override_address)
        known = next((c for c in FACTORY_CANDIDATES_V0 if c.address == address), None)
        candidate = known or FactoryCandidateV0(
            "operator_override",
            address,
            "explicit operator override; not trusted without on-chain bytecode probe",
        )
        probe = probe_factory_v0(
            client,
            candidate=candidate,
            token_launched_topic0=token_launched_topic0,
            latest_block=latest,
            lookback_blocks=lookback_blocks,
        )
        classification = (
            "PASS_FACTORY_OVERRIDE_V0" if probe.code_present and probe.probe_error is None
            else "FAIL_FACTORY_OVERRIDE_V0"
        )
        return {
            "classification": classification,
            "latest_block": latest,
            "selected_factory": address if classification.startswith("PASS") else None,
            "selection_reason": "OPERATOR_OVERRIDE_BYTECODE_PRESENT" if classification.startswith("PASS") else None,
            "probes": [probe.to_dict()],
        }

    probes = [
        probe_factory_v0(
            client,
            candidate=candidate,
            token_launched_topic0=token_launched_topic0,
            latest_block=latest,
            lookback_blocks=lookback_blocks,
        )
        for candidate in FACTORY_CANDIDATES_V0
    ]
    active = [p for p in probes if p.code_present and p.recent_launch_count > 0 and p.probe_error is None]
    if len(active) == 1:
        selected = active[0]
        classification = "PASS_FACTORY_DISCOVERY_V0"
        reason = "UNIQUE_RECENT_TOKEN_LAUNCHED_EMITTER"
    elif len(active) > 1:
        selected = None
        classification = "HOLD_MULTIPLE_ACTIVE_FACTORIES_V0"
        reason = "SEPARATE_FACTORY_STRATA_REQUIRED"
    else:
        selected = None
        classification = "HOLD_NO_RECENT_FACTORY_ACTIVITY_V0"
        reason = "NO_CANDIDATE_EMITTED_TOKEN_LAUNCHED_IN_LOOKBACK"
    return {
        "classification": classification,
        "latest_block": latest,
        "selected_factory": selected.address if selected else None,
        "selection_reason": reason,
        "probes": [p.to_dict() for p in probes],
    }
