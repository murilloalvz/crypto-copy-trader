from __future__ import annotations

import hashlib
import os
from typing import Any

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


MAX_SOL_BALANCE_BATCH = 100


def _helius_url() -> str:
    api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("HELIUS_API_KEY is required for Helius holder discovery")
    return f"https://mainnet.helius-rpc.com/?api-key={api_key}"


def _int_amount(value: Any) -> int | None:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def _batched_sol_balances(
    *,
    primary_rpc_url: str,
    fallback_rpc_url: str,
    owners: list[str],
) -> dict[str, int]:
    """Read SOL lamports in bounded standard-RPC batches while preserving owner order."""

    balances: dict[str, int] = {}
    for start in range(0, len(owners), MAX_SOL_BALANCE_BATCH):
        batch = owners[start : start + MAX_SOL_BALANCE_BATCH]
        params = [batch, {"encoding": "base64", "commitment": "confirmed"}]
        try:
            result = ft._rpc_call(primary_rpc_url, "getMultipleAccounts", params)
        except Exception:
            if not fallback_rpc_url or fallback_rpc_url == primary_rpc_url:
                raise
            result = ft._rpc_call(fallback_rpc_url, "getMultipleAccounts", params)

        rows = result.get("value") if isinstance(result, dict) else None
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise RuntimeError("getMultipleAccounts returned an invalid owner balance payload")
        for owner, row in zip(batch, rows):
            lamports = int(row.get("lamports") or 0) if isinstance(row, dict) else 0
            balances[owner] = max(0, lamports)
    return balances


def _discover_control_via_helius_holders(
    *, fixture: dict[str, Any], rpc_url: str
) -> tuple[str, dict[str, Any]]:
    helius_url = _helius_url()
    balance_rpc_url = rpc_url.strip() or helius_url
    mint = str(fixture["input_mint"])
    minimum_usdc = int(fixture["minimum_input_amount_raw"])
    minimum_sol = int(fixture["minimum_sol_lamports"])

    pages_checked = 0
    owners_checked = 0
    balance_batches = 0
    seen_owners: set[str] = set()

    # Helius getTokenAccounts is mint-filtered, avoiding the expensive
    # getTokenLargestAccounts path that several RPC providers rate-limit/reject.
    for page in range(1, 6):
        pages_checked += 1
        result = ft._rpc_call(
            helius_url,
            "getTokenAccounts",
            {
                "page": page,
                "limit": 1000,
                "displayOptions": {},
                "mint": mint,
            },
        )
        rows = result.get("token_accounts") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("Helius getTokenAccounts returned an invalid payload")
        if not rows:
            break

        funded: list[tuple[int, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            owner = str(row.get("owner") or "").strip()
            amount = _int_amount(row.get("amount"))
            if owner and amount is not None and amount >= minimum_usdc and owner not in seen_owners:
                funded.append((amount, owner))

        # Check larger token accounts first and de-duplicate owners across pages.
        funded.sort(reverse=True)
        candidates: list[tuple[int, str]] = []
        for amount, owner in funded:
            if owner in seen_owners:
                continue
            seen_owners.add(owner)
            candidates.append((amount, owner))

        if candidates:
            candidate_owners = [owner for _, owner in candidates]
            balances = _batched_sol_balances(
                primary_rpc_url=balance_rpc_url,
                fallback_rpc_url=helius_url,
                owners=candidate_owners,
            )
            owners_checked += len(candidate_owners)
            balance_batches += (len(candidate_owners) + MAX_SOL_BALANCE_BATCH - 1) // MAX_SOL_BALANCE_BATCH

            for amount, owner in candidates:
                lamports = int(balances.get(owner, 0))
                if lamports < minimum_sol:
                    continue
                return owner, {
                    "owner_public_key_sha256": hashlib.sha256(owner.encode("utf-8")).hexdigest(),
                    "token_account_amount_raw": amount,
                    "sol_lamports": lamports,
                    "candidates_checked": owners_checked,
                    "pages_checked": pages_checked,
                    "balance_batches": balance_batches,
                    "balance_batch_size_max": MAX_SOL_BALANCE_BATCH,
                    "discovery_source": "helius_getTokenAccounts_mint_filtered_batched_owner_balances",
                    "address_redacted": True,
                }

    raise RuntimeError(
        "Helius mint-filtered holder discovery found no public owner meeting the frozen USDC/SOL floors "
        f"after pages={pages_checked} owners_checked={owners_checked} balance_batches={balance_batches}"
    )


def main() -> int:
    original = sim._discover_control
    sim._discover_control = _discover_control_via_helius_holders
    try:
        return sim.main()
    finally:
        sim._discover_control = original


if __name__ == "__main__":
    raise SystemExit(main())
