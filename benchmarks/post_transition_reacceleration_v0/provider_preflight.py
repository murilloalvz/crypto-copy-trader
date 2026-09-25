from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    DEFAULT_CONTRACT,
    collector_capabilities,
    load_and_validate_contract,
)
from src.assets import USDC_MINT, WRAPPED_SOL_MINT
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)


VERSION = "post_transition_economic_collector_provider_preflight_v0"
PASS = "PASS_POST_TRANSITION_ECONOMIC_COLLECTOR_PROVIDER_PREFLIGHT_V0"
FAIL = "FAIL_POST_TRANSITION_ECONOMIC_COLLECTOR_PROVIDER_PREFLIGHT_V0"
USDC_DECIMALS = 6
WSOL_DECIMALS = 9


def run_preflight(*, api_key: str, timeout_seconds: int = 5) -> dict:
    contract = load_and_validate_contract()
    key = str(api_key or "").strip()
    base = {
        "type": "post_transition_economic_collector_provider_preflight_v0",
        "version": VERSION,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "fresh_economic_outcomes_opened": False,
        "fresh_economic_discovery_authorized": False,
        "cohort_tokens_queried": 0,
        "live_money": False,
        "transaction_submitted": False,
        "probe_pair": "USDC->WSOL",
        "probe_notional_usd": float(contract["position"]["notional_usd"]),
        "capabilities": collector_capabilities(contract),
    }
    if not key:
        return {
            **base,
            "classification": FAIL,
            "reason": "JUPITER_API_KEY_MISSING",
        }

    amount_raw = int(
        round(
            float(contract["position"]["notional_usd"])
            * (10 ** USDC_DECIMALS)
        )
    )
    try:
        order = JupiterSwapV2Client(
            api_key=key,
            timeout=int(timeout_seconds),
        ).order(
            input_mint=USDC_MINT,
            output_mint=WRAPPED_SOL_MINT,
            amount_raw=amount_raw,
            taker=None,
            slippage_bps=int(
                contract["costs"]["entry_adverse_slippage_bps"]
            ),
        )
        if order.has_assembled_transaction:
            raise ValueError(
                "read-only preflight unexpectedly returned assembled transaction"
            )
        quote = jupiter_order_to_causal_quote(
            order,
            token_mint=WRAPPED_SOL_MINT,
            side="buy",
            token_decimals=WSOL_DECIMALS,
        )
        if quote.executable:
            raise ValueError("read-only preflight quote must be non-executable")
        impact = quote.provider_price_impact_pct_points
        if impact is None or not math.isfinite(float(impact)):
            raise ValueError("provider price impact missing/non-finite")
    except (JupiterOrderError, ValueError, TypeError) as exc:
        return {
            **base,
            "classification": FAIL,
            "reason": f"{type(exc).__name__}:{exc}",
        }

    return {
        **base,
        "classification": PASS,
        "reason": "read_only_jupiter_route_probe_succeeded",
        "provider_router": quote.provider_router,
        "provider_price_impact_pct_points": float(impact),
        "provider_slippage_bps": quote.provider_slippage_bps,
        "quote_observed_at": quote.observed_at,
        "quote_market_time": quote.market_time,
        "quote_age_seconds": quote.observed_at - quote.market_time,
        "assembled_transaction_present": False,
        "route_only_quote": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=5)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    result = run_preflight(
        api_key=os.environ.get("JUPITER_API_KEY", ""),
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["classification"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
