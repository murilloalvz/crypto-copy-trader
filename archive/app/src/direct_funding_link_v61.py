from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from src.multichain_market_contract_v59 import ChainNetworkV59, canonical_network_v59


DIRECT_FUNDING_LINK_VERSION = "direct_funding_link_v61"
TRANSFER_ASSET_KINDS = {"native", "token"}


@dataclass(frozen=True)
class LaunchActorReferenceV61:
    chain: ChainNetworkV59
    token_address: str
    deployer_wallet: str
    launch_chain_time: int
    launch_observed_at: int
    reference_key: str


@dataclass(frozen=True)
class FundingTransferObservationV61:
    transfer_key: str
    chain: ChainNetworkV59
    from_wallet: str
    to_wallet: str
    chain_time: int
    observed_at: int
    asset_kind: str
    amount_raw: str
    asset_address: str | None = None
    transaction_key: str | None = None
    block_number: int | None = None
    event_index: int | None = None


@dataclass(frozen=True)
class DirectFundingLinkEvidenceV61:
    method_version: str
    reference_key: str
    chain_namespace: str
    chain_reference: str
    token_address: str
    deployer_wallet: str
    participant_wallet: str
    as_of: int
    launch_chain_time: int
    launch_observed_at: int
    candidate_transfer_count: int
    known_prelaunch_transfer_count: int
    deployer_to_participant_count: int
    participant_to_deployer_count: int
    deployer_to_participant_native_count: int
    participant_to_deployer_native_count: int
    first_direct_link_offset_seconds: int | None
    last_direct_link_offset_seconds: int | None
    latest_deployer_to_participant_offset_seconds: int | None
    direct_link_transaction_keys: tuple[str, ...]
    evidence_classification: str
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _same_chain(left: ChainNetworkV59, right: ChainNetworkV59) -> bool:
    a = canonical_network_v59(left.namespace, left.reference)
    b = canonical_network_v59(right.namespace, right.reference)
    return a == b


def validate_launch_reference_v61(reference: LaunchActorReferenceV61) -> None:
    canonical_network_v59(reference.chain.namespace, reference.chain.reference)
    _required(reference.token_address, "token_address")
    _required(reference.deployer_wallet, "deployer_wallet")
    _required(reference.reference_key, "reference_key")
    if int(reference.launch_chain_time) < 0 or int(reference.launch_observed_at) < 0:
        raise ValueError("launch timestamps must be non-negative")
    if int(reference.launch_observed_at) < int(reference.launch_chain_time):
        raise ValueError("launch_observed_at cannot precede launch_chain_time")


def validate_transfer_v61(item: FundingTransferObservationV61) -> None:
    canonical_network_v59(item.chain.namespace, item.chain.reference)
    _required(item.transfer_key, "transfer_key")
    source = _required(item.from_wallet, "from_wallet")
    destination = _required(item.to_wallet, "to_wallet")
    if source == destination:
        raise ValueError("self-transfer is not a direct funding relationship")
    if item.asset_kind not in TRANSFER_ASSET_KINDS:
        raise ValueError("unsupported transfer asset_kind")
    if item.asset_kind == "native" and item.asset_address is not None:
        raise ValueError("native transfer cannot carry asset_address")
    if item.asset_kind == "token":
        _required(item.asset_address or "", "asset_address")
    if int(item.chain_time) < 0 or int(item.observed_at) < 0:
        raise ValueError("transfer timestamps must be non-negative")
    if int(item.observed_at) < int(item.chain_time):
        raise ValueError("transfer observed_at cannot precede chain_time")
    try:
        amount = int(str(item.amount_raw))
    except ValueError as exc:
        raise ValueError("amount_raw must be a positive integer string") from exc
    if amount <= 0:
        raise ValueError("amount_raw must be positive")
    if item.transaction_key is not None and not item.transaction_key.strip():
        raise ValueError("transaction_key cannot be blank")
    if item.block_number is not None and int(item.block_number) < 0:
        raise ValueError("block_number must be non-negative")
    if item.event_index is not None and int(item.event_index) < 0:
        raise ValueError("event_index must be non-negative")


def build_direct_funding_link_evidence_v61(
    *,
    reference: LaunchActorReferenceV61,
    participant_wallet: str,
    as_of: int,
    transfers: Iterable[FundingTransferObservationV61],
) -> DirectFundingLinkEvidenceV61:
    """Describe direct deployer/participant transfer links known by a causal cutoff.

    A transfer counts only when it occurred strictly before the token launch and was
    actually observed by ``as_of``. A historical transfer discovered after the research
    decision therefore cannot be retroactively used as evidence.

    The result deliberately says DIRECT_LINK_* rather than insider/manipulation/sniper.
    A direct transfer is stronger provenance evidence than address concentration, but it
    still does not establish ownership, intent, coordination, or profitable extraction.
    """

    validate_launch_reference_v61(reference)
    participant = _required(participant_wallet, "participant_wallet")
    if participant == reference.deployer_wallet:
        raise ValueError("participant_wallet cannot equal deployer_wallet")
    cutoff = int(as_of)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")
    if reference.launch_observed_at > cutoff:
        raise ValueError("launch/deployer identity was not known by as_of")

    candidates: list[FundingTransferObservationV61] = []
    known_prelaunch: list[FundingTransferObservationV61] = []
    seen_keys: set[str] = set()
    for item in transfers:
        validate_transfer_v61(item)
        if item.transfer_key in seen_keys:
            raise ValueError("duplicate transfer_key")
        seen_keys.add(item.transfer_key)
        if not _same_chain(reference.chain, item.chain):
            continue
        wallets = {item.from_wallet, item.to_wallet}
        if reference.deployer_wallet not in wallets or participant not in wallets:
            continue
        candidates.append(item)
        if int(item.chain_time) < int(reference.launch_chain_time) and int(item.observed_at) <= cutoff:
            known_prelaunch.append(item)

    known_prelaunch.sort(
        key=lambda item: (
            int(item.chain_time),
            int(item.observed_at),
            item.transfer_key,
        )
    )
    outgoing = [
        item
        for item in known_prelaunch
        if item.from_wallet == reference.deployer_wallet and item.to_wallet == participant
    ]
    incoming = [
        item
        for item in known_prelaunch
        if item.from_wallet == participant and item.to_wallet == reference.deployer_wallet
    ]
    outgoing_native = [item for item in outgoing if item.asset_kind == "native"]
    incoming_native = [item for item in incoming if item.asset_kind == "native"]

    offsets = [int(item.chain_time) - int(reference.launch_chain_time) for item in known_prelaunch]
    outgoing_offsets = [int(item.chain_time) - int(reference.launch_chain_time) for item in outgoing]
    tx_keys = tuple(
        dict.fromkeys(
            item.transaction_key
            for item in known_prelaunch
            if item.transaction_key is not None
        )
    )

    if outgoing_native:
        classification = "DIRECT_NATIVE_DEPLOYER_TO_PARTICIPANT_PRELAUNCH"
    elif outgoing:
        classification = "DIRECT_TOKEN_DEPLOYER_TO_PARTICIPANT_PRELAUNCH"
    elif incoming:
        classification = "DIRECT_PARTICIPANT_TO_DEPLOYER_PRELAUNCH"
    elif known_prelaunch:
        classification = "DIRECT_PRELAUNCH_LINK"
    else:
        classification = "NO_CAUSALLY_KNOWN_DIRECT_PRELAUNCH_LINK"

    flags: list[str] = []
    late_prelaunch = [
        item
        for item in candidates
        if int(item.chain_time) < int(reference.launch_chain_time) and int(item.observed_at) > cutoff
    ]
    postlaunch = [item for item in candidates if int(item.chain_time) >= int(reference.launch_chain_time)]
    if late_prelaunch:
        flags.append("prelaunch_direct_links_discovered_after_as_of_excluded")
    if postlaunch:
        flags.append("postlaunch_direct_links_excluded")
    if outgoing and not outgoing_native:
        flags.append("deployer_to_participant_link_is_token_not_native")
    if known_prelaunch and not tx_keys:
        flags.append("direct_link_transaction_identity_unavailable")

    return DirectFundingLinkEvidenceV61(
        method_version=DIRECT_FUNDING_LINK_VERSION,
        reference_key=reference.reference_key,
        chain_namespace=reference.chain.namespace,
        chain_reference=reference.chain.reference,
        token_address=reference.token_address,
        deployer_wallet=reference.deployer_wallet,
        participant_wallet=participant,
        as_of=cutoff,
        launch_chain_time=int(reference.launch_chain_time),
        launch_observed_at=int(reference.launch_observed_at),
        candidate_transfer_count=len(candidates),
        known_prelaunch_transfer_count=len(known_prelaunch),
        deployer_to_participant_count=len(outgoing),
        participant_to_deployer_count=len(incoming),
        deployer_to_participant_native_count=len(outgoing_native),
        participant_to_deployer_native_count=len(incoming_native),
        first_direct_link_offset_seconds=min(offsets) if offsets else None,
        last_direct_link_offset_seconds=max(offsets) if offsets else None,
        latest_deployer_to_participant_offset_seconds=max(outgoing_offsets) if outgoing_offsets else None,
        direct_link_transaction_keys=tx_keys,
        evidence_classification=classification,
        data_quality_flags=tuple(flags),
    )
