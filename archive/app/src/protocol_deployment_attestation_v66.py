from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable

from src.multichain_market_contract_v59 import ChainNetworkV59, canonical_network_v59


PROTOCOL_DEPLOYMENT_ATTESTATION_VERSION = "protocol_deployment_attestation_v66"
CAPABILITY_EVIDENCE_KINDS = {
    "deployed_call_succeeded",
    "deployed_event_observed",
    "verified_runtime_source_match",
    "source_only",
    "third_party_claim",
    "conflicting",
}
AUTHORITATIVE_READ_EVIDENCE = {
    "deployed_call_succeeded",
    "verified_runtime_source_match",
}
AUTHORITATIVE_EVENT_EVIDENCE = {
    "deployed_event_observed",
    "verified_runtime_source_match",
}
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX_HASH_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class DeploymentCapabilityEvidenceV66:
    capability: str
    evidence_kind: str
    observed_at: int
    evidence_reference: str


@dataclass(frozen=True)
class ProtocolDeploymentAttestationV66:
    method_version: str
    protocol_key: str
    generation: str
    chain: ChainNetworkV59
    deployment_address: str
    observed_at: int
    runtime_code_hash: str | None
    source_commit_sha: str | None
    capabilities: tuple[DeploymentCapabilityEvidenceV66, ...]
    attestation_sha256: str
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _canonical_address(chain: ChainNetworkV59, value: str) -> str:
    raw = _required(value, "deployment_address")
    if chain.namespace == "eip155":
        if not _EVM_ADDRESS_RE.fullmatch(raw):
            raise ValueError("eip155 deployment_address must be a 20-byte hex address")
        return raw.lower()
    return raw


def _canonical_hash(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not _HEX_HASH_RE.fullmatch(raw):
        raise ValueError(f"{name} must be a 32-byte hex hash")
    return raw.lower().removeprefix("0x")


def _canonical_capability(item: DeploymentCapabilityEvidenceV66) -> DeploymentCapabilityEvidenceV66:
    capability = _required(item.capability, "capability")
    kind = _required(item.evidence_kind, "evidence_kind")
    reference = _required(item.evidence_reference, "evidence_reference")
    if kind not in CAPABILITY_EVIDENCE_KINDS:
        raise ValueError("unsupported capability evidence_kind")
    observed_at = int(item.observed_at)
    if observed_at < 0:
        raise ValueError("capability observed_at must be non-negative")
    return DeploymentCapabilityEvidenceV66(
        capability=capability,
        evidence_kind=kind,
        observed_at=observed_at,
        evidence_reference=reference,
    )


def build_protocol_deployment_attestation_v66(
    *,
    protocol_key: str,
    generation: str,
    chain: ChainNetworkV59,
    deployment_address: str,
    observed_at: int,
    capabilities: Iterable[DeploymentCapabilityEvidenceV66],
    runtime_code_hash: str | None = None,
    source_commit_sha: str | None = None,
) -> ProtocolDeploymentAttestationV66:
    """Freeze deployment identity separately from a mutable protocol/repository name."""

    protocol = _required(protocol_key, "protocol_key")
    gen = _required(generation, "generation")
    network = canonical_network_v59(chain.namespace, chain.reference)
    address = _canonical_address(network, deployment_address)
    cutoff = int(observed_at)
    if cutoff < 0:
        raise ValueError("observed_at must be non-negative")
    code_hash = _canonical_hash(runtime_code_hash, "runtime_code_hash")
    source_sha = _canonical_hash(source_commit_sha, "source_commit_sha")

    rows: list[DeploymentCapabilityEvidenceV66] = []
    seen: set[str] = set()
    for raw in capabilities:
        item = _canonical_capability(raw)
        if item.capability in seen:
            raise ValueError("duplicate deployment capability")
        if item.observed_at > cutoff:
            raise ValueError("capability evidence cannot postdate attestation")
        seen.add(item.capability)
        rows.append(item)
    rows.sort(key=lambda item: item.capability)

    flags: list[str] = []
    if code_hash is None:
        flags.append("runtime_code_hash_unavailable")
    if source_sha is None:
        flags.append("source_commit_unpinned")
    if any(item.evidence_kind == "conflicting" for item in rows):
        flags.append("conflicting_capability_evidence")
    if any(item.evidence_kind in {"source_only", "third_party_claim"} for item in rows):
        flags.append("non_authoritative_capabilities_present")

    payload = {
        "method_version": PROTOCOL_DEPLOYMENT_ATTESTATION_VERSION,
        "protocol_key": protocol,
        "generation": gen,
        "chain_namespace": network.namespace,
        "chain_reference": network.reference,
        "deployment_address": address,
        "observed_at": cutoff,
        "runtime_code_hash": code_hash,
        "source_commit_sha": source_sha,
        "capabilities": [
            {
                "capability": item.capability,
                "evidence_kind": item.evidence_kind,
                "observed_at": item.observed_at,
                "evidence_reference": item.evidence_reference,
            }
            for item in rows
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()

    return ProtocolDeploymentAttestationV66(
        method_version=PROTOCOL_DEPLOYMENT_ATTESTATION_VERSION,
        protocol_key=protocol,
        generation=gen,
        chain=network,
        deployment_address=address,
        observed_at=cutoff,
        runtime_code_hash=code_hash,
        source_commit_sha=source_sha,
        capabilities=tuple(rows),
        attestation_sha256=digest,
        data_quality_flags=tuple(flags),
    )


def capability_evidence_v66(
    attestation: ProtocolDeploymentAttestationV66,
    capability: str,
) -> DeploymentCapabilityEvidenceV66 | None:
    target = _required(capability, "capability")
    return next((item for item in attestation.capabilities if item.capability == target), None)


def capability_authoritative_for_read_v66(
    attestation: ProtocolDeploymentAttestationV66,
    capability: str,
) -> bool:
    item = capability_evidence_v66(attestation, capability)
    return item is not None and item.evidence_kind in AUTHORITATIVE_READ_EVIDENCE


def capability_authoritative_for_event_v66(
    attestation: ProtocolDeploymentAttestationV66,
    capability: str,
) -> bool:
    item = capability_evidence_v66(attestation, capability)
    return item is not None and item.evidence_kind in AUTHORITATIVE_EVENT_EVIDENCE
