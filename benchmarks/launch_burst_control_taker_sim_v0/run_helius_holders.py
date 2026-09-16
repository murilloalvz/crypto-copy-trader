from __future__ import annotations

import hashlib
import os
from typing import Any

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


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


def _discover_control_via_helius_holders(
    *, fixture: dict[str, Any], rpc_url: str
) -> tuple[str, dict[str, Any]]:
    del rpc_url  # discovery deliberately uses the Helius mint-filtered token API.
    url = _helius_url()
    mint = str(fixture["input_mint"])
    minimum_usdc = int(fixture["minimum_input_amount_raw"])
    minimum_sol = int(fixture["minimum_sol_lamports"])

    pages_checked = 0
    owners_checked = 0
    seen_owners: set[str] = set()

    # Helius getTokenAccounts is mint-filtered, avoiding the expensive
    # getTokenLargestAccounts path that several RPC providers rate-limit/reject.
    for page in range(1, 6):
        pages_checked += 1
        result = ft._rpc_call(
            url,
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
            if owner and amount is not None and amount >= minimum_usdc:
                funded.append((amount, owner))

        # Check larger accounts first and de-duplicate owners across token accounts/pages.
        funded.sort(reverse=True)
        for amount, owner in funded:
            if owner in seen_owners:
                continue
            seen_owners.add(owner)
            owners_checked += 1
            balance = ft._rpc_call(
                url,
                "getBalance",
                [owner, {"commitment": "confirmed"}],
            )
            lamports = int(balance.get("value") or 0) if isinstance(balance, dict) else 0
            if lamports < minimum_sol:
                continue
            return owner, {
                "owner_public_key_sha256": hashlib.sha256(owner.encode("utf-8")).hexdigest(),
                "token_account_amount_raw": amount,
                "sol_lamports": lamports,
                "candidates_checked": owners_checked,
                "pages_checked": pages_checked,
                "discovery_source": "helius_getTokenAccounts_mint_filtered",
                "address_redacted": True,
            }

    raise RuntimeError(
        "Helius mint-filtered holder discovery found no public owner meeting the frozen USDC/SOL floors "
        f"after pages={pages_checked} owners_checked={owners_checked}"
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
