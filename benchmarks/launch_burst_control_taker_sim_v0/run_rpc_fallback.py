from __future__ import annotations

import os
from typing import Any

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft
from benchmarks.launch_burst_prospective_route_live_v4.no_funds_assembly_diagnostic import (
    _discover_public_funded_control,
)


def _rpc_candidates(primary: str) -> tuple[str, ...]:
    values = [primary.strip()]
    values.extend(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )

    # The simulation already requires HELIUS_API_KEY for live acquisition. Reuse that
    # credential as an RPC fallback so control-taker discovery does not depend on the
    # public Solana RPC or on a second manually configured secret.
    helius_api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if helius_api_key:
        values.append(f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}")

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return tuple(output)


def _discover_control_with_rpc_fallback(
    *, fixture: dict[str, Any], rpc_url: str
) -> tuple[str, dict[str, Any]]:
    errors: list[str] = []
    candidates = _rpc_candidates(rpc_url)
    if not candidates:
        raise RuntimeError("No Solana RPC candidates configured")

    for index, candidate in enumerate(candidates):
        try:
            control = _discover_public_funded_control(
                rpc_url=candidate,
                input_mint=str(fixture["input_mint"]),
                minimum_input_amount_raw=int(fixture["minimum_input_amount_raw"]),
                minimum_sol_lamports=int(fixture["minimum_sol_lamports"]),
                rpc_call=ft._rpc_call,
            )
            address = str(control.pop("owner_public_key"))
            return address, {
                "owner_public_key_sha256": control.get("owner_public_key_sha256"),
                "token_account_amount_raw": int(control.get("token_account_amount_raw") or 0),
                "sol_lamports": int(control.get("sol_lamports") or 0),
                "candidates_checked": int(control.get("candidates_checked") or 0),
                "rpc_candidate_index": index,
                "rpc_fallback_used": index > 0,
                "rpc_candidate_count": len(candidates),
            }
        except Exception as exc:
            errors.append(f"rpc_candidate_{index}:{type(exc).__name__}:{str(exc)[:200]}")

    raise RuntimeError(
        "Public funded control discovery failed across all configured RPC candidates: "
        + " | ".join(errors)
    )


def main() -> int:
    original = sim._discover_control
    sim._discover_control = _discover_control_with_rpc_fallback
    try:
        return sim.main()
    finally:
        sim._discover_control = original


if __name__ == "__main__":
    raise SystemExit(main())
