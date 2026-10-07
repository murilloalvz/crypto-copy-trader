from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from src.database import rows
from src.multichain_market_contract_v59 import canonical_network_v59
from src.wallet_cohort_manifest_v65 import (
    WalletCohortEvidenceMemberV65,
    build_wallet_cohort_manifest_v65,
)
from src.wallet_strategy_lab import build_wallet_strategy_fingerprint

VERSION = "v60_opportunity_wallet_convergence_discovery_v0_freeze_cohort"
EVIDENCE_VERSION = "wallet_strategy_lab_fingerprint_v1"
DEFAULT_OUTPUT = Path(__file__).parent / "frozen_cohort_v60_discovery_v0.json"

# Source: docs/opportunity-wallet-convergence-v60-protocol-2026-09-08.md,
# "Initial public Solana study seeds". Research seeds only, not a copy-trading
# recommendation or an approved live cohort.
SEED_WALLETS = (
    ("Cented", "CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o"),
    ("Theo", "Bi4rd5FH5bYEN8scZ7wevxNZyNmKHdaBcvewdPFxYdLt"),
    ("Cupsey", "2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f"),
    ("Decu", "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"),
    ("Pain", "J6TDXvarvpBdPXTaTU8eJbtso1PUCYKGkVtMKUUY8iEa"),
    ("Kadenox", "B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC"),
    ("Trunoest", "ardinRsN1mNYVeoJWTBsWeYeXvuR9UUDGMsCDKpb6AT"),
    ("Kev", "BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd"),
)

SOLANA = canonical_network_v59("solana", "mainnet")


def _pre_period_swaps(address: str, pre_period_start: int, pre_period_end: int) -> list[dict]:
    return rows(
        """SELECT block_time, status, kind, dex, token_mint, token_change
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
          AND block_time >= ? AND block_time < ?
        ORDER BY block_time""",
        (address, pre_period_start, pre_period_end),
    )


def freeze_cohort_v0(
    *,
    pre_period_end: int,
    pre_period_days: int,
    min_pre_period_swaps: int,
    seeds: tuple[tuple[str, str], ...] = SEED_WALLETS,
) -> dict:
    pre_period_start = pre_period_end - pre_period_days * 86_400
    registered_at = pre_period_end + 1

    members: list[WalletCohortEvidenceMemberV65] = []
    excluded: list[dict] = []
    for nickname, address in seeds:
        swaps = _pre_period_swaps(address, pre_period_start, pre_period_end)
        if len(swaps) < min_pre_period_swaps:
            excluded.append({"nickname": nickname, "address": address, "pre_period_swap_count": len(swaps)})
            continue
        fingerprint = build_wallet_strategy_fingerprint(address, swaps)
        members.append(
            WalletCohortEvidenceMemberV65(
                chain=SOLANA,
                wallet_address=address,
                strategy_signature=fingerprint.signature,
                evidence_version=EVIDENCE_VERSION,
                evidence_as_of=pre_period_end,
            )
        )

    if not members:
        return {
            "classification": "FAIL_V60_DISCOVERY_V0_NO_ELIGIBLE_SEED",
            "pre_period_start": pre_period_start,
            "pre_period_end": pre_period_end,
            "min_pre_period_swaps": min_pre_period_swaps,
            "excluded": excluded,
        }

    manifest = build_wallet_cohort_manifest_v65(
        cohort_key="v60-discovery-v0",
        registered_at=registered_at,
        members=members,
    )
    return {
        "classification": "PASS_V60_DISCOVERY_V0_COHORT_FROZEN",
        "manifest": {
            "method_version": manifest.method_version,
            "cohort_key": manifest.cohort_key,
            "registered_at": manifest.registered_at,
            "member_count": manifest.member_count,
            "manifest_sha256": manifest.manifest_sha256,
            "members": [
                asdict(item) | {"chain": {"namespace": item.chain.namespace, "reference": item.chain.reference}}
                for item in manifest.members
            ],
        },
        "pre_period_start": pre_period_start,
        "pre_period_end": pre_period_end,
        "min_pre_period_swaps": min_pre_period_swaps,
        "excluded": excluded,
    }


def _self_check() -> None:
    now = 2_000_000_000
    synthetic_swaps = [{"block_time": now - 86_400 * day, "status": "success", "kind": "swap"} for day in range(25)]

    original_pre_period_swaps = globals()["_pre_period_swaps"]
    try:
        globals()["_pre_period_swaps"] = lambda address, start, end: (
            synthetic_swaps if address == SEED_WALLETS[0][1] else []
        )
        result = freeze_cohort_v0(
            pre_period_end=now,
            pre_period_days=30,
            min_pre_period_swaps=20,
            seeds=(SEED_WALLETS[0], SEED_WALLETS[1]),
        )
    finally:
        globals()["_pre_period_swaps"] = original_pre_period_swaps

    assert result["classification"] == "PASS_V60_DISCOVERY_V0_COHORT_FROZEN", result
    assert result["manifest"]["member_count"] == 1, result
    assert len(result["excluded"]) == 1, result
    assert result["manifest"]["registered_at"] == now + 1, result
    print("self-check OK:", result["manifest"]["manifest_sha256"][:16], "...")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the v60 discovery-v0 wallet cohort manifest from already-synced local data."
    )
    parser.add_argument("--pre-period-end", type=int, default=None, help="unix seconds; defaults to now")
    parser.add_argument("--pre-period-days", type=int, default=30)
    parser.add_argument("--min-pre-period-swaps", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    pre_period_end = args.pre_period_end if args.pre_period_end is not None else int(time.time())
    result = freeze_cohort_v0(
        pre_period_end=pre_period_end,
        pre_period_days=args.pre_period_days,
        min_pre_period_swaps=args.min_pre_period_swaps,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nwritten to {args.output} -- commit this file before reading any StoredMarketTrade for discovery.")
    return 0 if result["classification"] == "PASS_V60_DISCOVERY_V0_COHORT_FROZEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
