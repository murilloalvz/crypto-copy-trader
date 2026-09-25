from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    DEFAULT_CONTRACT,
    load_and_validate_contract,
)
from src.assets import USDC_MINT, WRAPPED_SOL_MINT
from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
)


VERSION = "post_transition_assembled_entry_preflight_v0"
PASS = "PASS_POST_TRANSITION_ASSEMBLED_ENTRY_PREFLIGHT_V0"
FAIL = "FAIL_POST_TRANSITION_ASSEMBLED_ENTRY_PREFLIGHT_V0"
USDC_DECIMALS = 6
WSOL_DECIMALS = 9


def _redact(value: str, *secrets: str) -> str:
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:1000]


def run_preflight(*, api_key: str, taker_public_key: str) -> dict:
    contract = load_and_validate_contract()
    base = {
        "type": VERSION,
        "version": VERSION,
        "classification": FAIL,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "probe_pair": "USDC->WSOL",
        "probe_notional_usd": float(contract["position"]["notional_usd"]),
        "cohort_tokens_queried": 0,
        "fresh_economic_outcomes_opened": False,
        "provider_execute_called": False,
        "transaction_submitted": False,
        "live_money": False,
    }
    if not api_key.strip():
        return {**base, "reason": "JUPITER_API_KEY_MISSING"}
    if not taker_public_key.strip():
        return {**base, "reason": "JUPITER_TAKER_PUBLIC_KEY_MISSING"}

    amount_raw = int(
        round(float(contract["position"]["notional_usd"]) * (10**USDC_DECIMALS))
    )
    try:
        order = JupiterSwapV2Client(
            api_key=api_key.strip(),
            timeout=int(contract["fresh_run"]["provider_timeout_seconds"]),
        ).order(
            input_mint=USDC_MINT,
            output_mint=WRAPPED_SOL_MINT,
            amount_raw=amount_raw,
            taker=taker_public_key.strip(),
            slippage_bps=int(contract["costs"]["entry_adverse_slippage_bps"]),
        )
        quote = jupiter_order_to_causal_quote(
            order,
            token_mint=WRAPPED_SOL_MINT,
            side="buy",
            token_decimals=WSOL_DECIMALS,
        )
    except (JupiterOrderError, ValueError, TypeError) as exc:
        return {
            **base,
            "reason": _redact(
                f"{type(exc).__name__}:{exc}",
                api_key,
                taker_public_key,
            ),
        }

    impact = quote.provider_price_impact_pct_points
    gates = {
        "assembled_transaction_present": bool(order.transaction),
        "normalized_quote_executable": quote.executable is True,
        "exact_output_quantity_present": bool(str(quote.output_amount_raw or "").strip()),
        "provider_price_impact_present": (
            impact is not None and math.isfinite(float(impact))
        ),
        "provider_price_impact_within_frozen_limit": (
            impact is not None
            and math.isfinite(float(impact))
            and float(impact)
            <= float(
                contract["route_quality"][
                    "max_provider_price_impact_pct_points"
                ]
            )
        ),
        "error_code_clear": order.error_code in {None, 0},
    }
    return {
        **base,
        "classification": PASS if all(gates.values()) else FAIL,
        "reason": (
            "read_only_assembled_control_route_succeeded"
            if all(gates.values())
            else "assembled_control_route_gate_failed"
        ),
        "provider_router": quote.provider_router,
        "provider_slippage_bps": quote.provider_slippage_bps,
        "provider_price_impact_pct_points": impact,
        "quote_observed_at": quote.observed_at,
        "quote_market_time": quote.market_time,
        "quote_age_seconds": quote.observed_at - quote.market_time,
        "assembled_transaction_present": bool(order.transaction),
        "output_amount_raw_present": bool(str(quote.output_amount_raw or "").strip()),
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    try:
        report = run_preflight(
            api_key=os.environ.get("JUPITER_API_KEY", ""),
            taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", ""),
        )
    except Exception as exc:
        report = {
            "type": VERSION,
            "version": VERSION,
            "classification": FAIL,
            "reason": f"{type(exc).__name__}:{exc}",
            "cohort_tokens_queried": 0,
            "fresh_economic_outcomes_opened": False,
            "provider_execute_called": False,
            "transaction_submitted": False,
            "live_money": False,
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
