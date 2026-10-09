from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable

from src.multichain_market_contract_v59 import ChainNetworkV59, canonical_network_v59
from src.opportunity_wallet_convergence_v60 import FrozenWalletCohortMemberV60


WALLET_COHORT_MANIFEST_VERSION = "wallet_cohort_manifest_v65_sha256"
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class WalletCohortEvidenceMemberV65:
    chain: ChainNetworkV59
    wallet_address: str
    strategy_signature: str
    evidence_version: str
    evidence_as_of: int


@dataclass(frozen=True)
class WalletCohortManifestV65:
    method_version: str
    cohort_key: str
    registered_at: int
    member_count: int
    members: tuple[WalletCohortEvidenceMemberV65, ...]
    manifest_sha256: str


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _canonical_wallet(chain: ChainNetworkV59, wallet: str) -> str:
    network = canonical_network_v59(chain.namespace, chain.reference)
    raw = _required(wallet, "wallet_address")
    if network.namespace == "eip155":
        if not _EVM_ADDRESS_RE.fullmatch(raw):
            raise ValueError("eip155 wallet_address must be a 20-byte hex address")
        return raw.lower()
    return raw


def _canonical_member(item: WalletCohortEvidenceMemberV65) -> WalletCohortEvidenceMemberV65:
    network = canonical_network_v59(item.chain.namespace, item.chain.reference)
    wallet = _canonical_wallet(network, item.wallet_address)
    signature = _required(item.strategy_signature, "strategy_signature")
    evidence_version = _required(item.evidence_version, "evidence_version")
    evidence_as_of = int(item.evidence_as_of)
    if evidence_as_of < 0:
        raise ValueError("evidence_as_of must be non-negative")
    return WalletCohortEvidenceMemberV65(
        chain=network,
        wallet_address=wallet,
        strategy_signature=signature,
        evidence_version=evidence_version,
        evidence_as_of=evidence_as_of,
    )


def _member_identity(item: WalletCohortEvidenceMemberV65) -> tuple[str, str, str]:
    return (
        item.chain.namespace,
        item.chain.reference,
        item.wallet_address,
    )


def _member_payload(item: WalletCohortEvidenceMemberV65) -> dict[str, object]:
    return {
        "chain_namespace": item.chain.namespace,
        "chain_reference": item.chain.reference,
        "wallet_address": item.wallet_address,
        "strategy_signature": item.strategy_signature,
        "evidence_version": item.evidence_version,
        "evidence_as_of": int(item.evidence_as_of),
    }


def build_wallet_cohort_manifest_v65(
    *,
    cohort_key: str,
    registered_at: int,
    members: Iterable[WalletCohortEvidenceMemberV65],
) -> WalletCohortManifestV65:
    """Create a deterministic cohort manifest that can be committed before a study starts.

    The hash proves the exact membership/evidence payload used by the study. It does not prove
    wall-clock honesty by itself; the protocol requires the manifest to be committed in the repo
    before the first eligible episode/entry in a prospective cohort study.
    """

    cohort = _required(cohort_key, "cohort_key")
    registration = int(registered_at)
    if registration < 0:
        raise ValueError("registered_at must be non-negative")

    canonical: list[WalletCohortEvidenceMemberV65] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in members:
        item = _canonical_member(raw)
        identity = _member_identity(item)
        if identity in seen:
            raise ValueError("duplicate wallet identity in cohort manifest")
        seen.add(identity)
        if int(item.evidence_as_of) >= registration:
            raise ValueError("member evidence_as_of must be strictly before registered_at")
        canonical.append(item)

    if not canonical:
        raise ValueError("cohort manifest requires at least one member")

    canonical.sort(key=lambda item: _member_identity(item))
    payload = {
        "method_version": WALLET_COHORT_MANIFEST_VERSION,
        "cohort_key": cohort,
        "registered_at": registration,
        "members": [_member_payload(item) for item in canonical],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()

    return WalletCohortManifestV65(
        method_version=WALLET_COHORT_MANIFEST_VERSION,
        cohort_key=cohort,
        registered_at=registration,
        member_count=len(canonical),
        members=tuple(canonical),
        manifest_sha256=digest,
    )


def manifest_to_v60_members_v65(
    manifest: WalletCohortManifestV65,
    *,
    chain_namespace: str,
    chain_reference: str | int,
) -> tuple[FrozenWalletCohortMemberV60, ...]:
    """Bridge one chain slice of a pre-registered manifest into v60.

    v60 is currently Solana-store-oriented and does not carry chain identity itself. The caller
    must therefore request one explicit chain slice. Cross-chain members are never silently mixed.
    """

    network = canonical_network_v59(chain_namespace, chain_reference)
    rows = [item for item in manifest.members if item.chain == network]
    return tuple(
        FrozenWalletCohortMemberV60(
            wallet_address=item.wallet_address,
            cohort_key=manifest.cohort_key,
            frozen_at=int(manifest.registered_at),
            strategy_signature=item.strategy_signature,
            evidence_version=item.evidence_version,
        )
        for item in rows
    )


def manifest_is_registered_before_v65(
    manifest: WalletCohortManifestV65,
    *,
    episode_as_of: int,
) -> bool:
    """Mechanical temporal gate; repository commit chronology remains an external audit step."""

    cutoff = int(episode_as_of)
    if cutoff < 0:
        raise ValueError("episode_as_of must be non-negative")
    return int(manifest.registered_at) < cutoff
