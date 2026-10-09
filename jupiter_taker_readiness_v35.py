from __future__ import annotations

import argparse

from src.assets import USDC_MINT
from src.config import settings
from src.solana import SolanaClient, SolanaRPCError

LAMPORTS_PER_SOL = 1_000_000_000
USDC_DECIMALS = 6
DEFAULT_MIN_SOL = 0.01


def _sum_usdc_raw(result) -> int:
    rows = (result or {}).get("value", []) if isinstance(result, dict) else []
    total = 0
    for row in rows:
        try:
            amount = row["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]
            total += int(amount)
        except (KeyError, TypeError, ValueError) as exc:
            raise SolanaRPCError("getTokenAccountsByOwner returned invalid USDC token-account data") from exc
    return total


def inspect_taker_readiness(*, notional_usd: float, min_sol: float, timeout_seconds: int) -> int:
    if notional_usd <= 0:
        raise ValueError("notional_usd must be positive")
    if min_sol < 0:
        raise ValueError("min_sol cannot be negative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    taker = settings.jupiter_taker_public_key.strip()
    print("Crypto Copy Trader — Jupiter Taker Readiness v35")
    print("Mode: READ ONLY — balance preflight only; no Jupiter order, signing, execute or transfer.")
    if not taker:
        print("classification=CONFIG_MISSING reason=JUPITER_TAKER_PUBLIC_KEY")
        return 2

    client = SolanaClient(
        settings.rpc_url,
        timeout=timeout_seconds,
        fallback_urls=settings.rpc_fallback_urls,
    )
    try:
        balance = client.call(
            "getBalance",
            [taker, {"commitment": "confirmed"}],
            max_attempts=1,
        )
        token_accounts = client.call(
            "getTokenAccountsByOwner",
            [
                taker,
                {"mint": USDC_MINT},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
            max_attempts=1,
        )
    except SolanaRPCError as exc:
        print(f"classification=RPC_ERROR error={type(exc).__name__}:{exc}")
        return 3

    sol_lamports = int((balance or {}).get("value", 0)) if isinstance(balance, dict) else 0
    usdc_raw = _sum_usdc_raw(token_accounts)
    required_usdc_raw = int(round(notional_usd * (10**USDC_DECIMALS)))
    min_sol_lamports = int(round(min_sol * LAMPORTS_PER_SOL))

    sol = sol_lamports / LAMPORTS_PER_SOL
    usdc = usdc_raw / (10**USDC_DECIMALS)
    deficit_usdc_raw = max(0, required_usdc_raw - usdc_raw)
    deficit_usdc = deficit_usdc_raw / (10**USDC_DECIMALS)

    has_usdc = usdc_raw >= required_usdc_raw
    has_sol = sol_lamports >= min_sol_lamports

    if has_usdc and has_sol:
        classification = "READY"
    elif not has_usdc and not has_sol:
        classification = "INSUFFICIENT_USDC_AND_SOL"
    elif not has_usdc:
        classification = "INSUFFICIENT_USDC"
    else:
        classification = "INSUFFICIENT_SOL"

    print(f"TAKER={taker}")
    print(f"SOL={sol:.9f} MIN_SOL={min_sol:.9f} HAS_SOL={has_sol}")
    print(
        f"USDC={usdc:.6f} REQUIRED_USDC={notional_usd:.6f} "
        f"USDC_DEFICIT={deficit_usdc:.6f} HAS_USDC={has_usdc}"
    )
    print(f"classification={classification}")
    return 0 if classification == "READY" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Jupiter taker balance readiness preflight")
    parser.add_argument("--notional-usd", type=float, default=25.0)
    parser.add_argument("--min-sol", type=float, default=DEFAULT_MIN_SOL)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(
        inspect_taker_readiness(
            notional_usd=args.notional_usd,
            min_sol=args.min_sol,
            timeout_seconds=args.rpc_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
