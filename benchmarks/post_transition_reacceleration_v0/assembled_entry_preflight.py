from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from urllib.request import Request, urlopen

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


def _rpc_call(rpc_url: str, method: str, params: list) -> object:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    request = Request(
        rpc_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "crypto-copy-trader/0.3",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Solana RPC returned a non-object payload")
    if payload.get("error") is not None:
        raise RuntimeError(f"Solana RPC {method} error: {payload['error']}")
    return payload.get("result")


def _read_taker_balances(*, rpc_url: str, taker_public_key: str) -> dict:
    balance = _rpc_call(
        rpc_url,
        "getBalance",
        [taker_public_key, {"commitment": "confirmed"}],
    )
    if not isinstance(balance, dict) or balance.get("value") is None:
        raise RuntimeError("getBalance returned an invalid payload")

    accounts = _rpc_call(
        rpc_url,
        "getTokenAccountsByOwner",
        [
            taker_public_key,
            {"mint": USDC_MINT},
            {"encoding": "jsonParsed", "commitment": "confirmed"},
        ],
    )
    rows = accounts.get("value") if isinstance(accounts, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("getTokenAccountsByOwner returned an invalid payload")

    usdc_raw = 0
    for row in rows:
        info = row["account"]["data"]["parsed"]["info"]
        usdc_raw += int(info["tokenAmount"]["amount"])

    return {
        "sol_lamports": int(balance["value"]),
        "usdc_amount_raw": usdc_raw,
    }


def _redact(value: str, *secrets: str) -> str:
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:1000]


def run_preflight(
    *,
    api_key: str,
    taker_public_key: str,
    rpc_url: str = "",
) -> dict:
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
    balance_diagnostic = None
    balance_diagnostic_error = None
    if rpc_url.strip():
        try:
            balance_diagnostic = _read_taker_balances(
                rpc_url=rpc_url.strip(),
                taker_public_key=taker_public_key.strip(),
            )
            balance_diagnostic["frozen_entry_notional_raw"] = amount_raw
            balance_diagnostic["usdc_covers_frozen_notional"] = (
                int(balance_diagnostic["usdc_amount_raw"]) >= amount_raw
            )
            balance_diagnostic["sol_positive"] = (
                int(balance_diagnostic["sol_lamports"]) > 0
            )
        except Exception as exc:
            balance_diagnostic_error = _redact(
                f"{type(exc).__name__}:{exc}",
                api_key,
                taker_public_key,
                rpc_url,
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
            "taker_balance_diagnostic": balance_diagnostic,
            "taker_balance_diagnostic_error": balance_diagnostic_error,
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
        "provider_mode": order.mode,
        "provider_error_code": order.error_code,
        "provider_error_message": _redact(
            str(order.error_message or ""),
            api_key,
            taker_public_key,
            rpc_url,
        ) or None,
        "provider_slippage_bps": quote.provider_slippage_bps,
        "provider_price_impact_pct_points": impact,
        "quote_observed_at": quote.observed_at,
        "quote_market_time": quote.market_time,
        "quote_age_seconds": quote.observed_at - quote.market_time,
        "assembled_transaction_present": bool(order.transaction),
        "output_amount_raw_present": bool(str(quote.output_amount_raw or "").strip()),
        "taker_balance_diagnostic": balance_diagnostic,
        "taker_balance_diagnostic_error": balance_diagnostic_error,
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
            rpc_url=os.environ.get("SOLANA_RPC_URL", ""),
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
