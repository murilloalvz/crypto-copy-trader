"""Read-only operational probe for Pons V2 curve math.

This command discovers/validates the factory, binds semantics to deployed curve
capabilities, reads one target curve at a pinned block, and optionally computes
BUY/SELL mathematical quotes. It never builds, signs, simulates or submits a
transaction and never opens economic outcomes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os

from dotenv import load_dotenv

from benchmarks.robinhood_launch_burst_v0.direct_quote_state import read_curve_quote_state_v0
from benchmarks.robinhood_launch_burst_v0.factory_discovery import discover_factory_v0
from benchmarks.robinhood_launch_burst_v0.live import DEFAULT_PUBLIC_RPC, RpcClient
from benchmarks.robinhood_launch_burst_v0.protocol_capabilities import probe_protocol_capabilities_v0
from src.pons_v2_curve_quote_v0 import quote_buy_v0, quote_sell_v0
from src.robinhood_pons_launch_burst_v0 import TOKEN_LAUNCHED_SIGNATURE


PASS_CAPABILITIES = {
    "PASS_PONS_PROTOCOL_CAPABILITIES_V0_SNIPE_VIEW",
    "PASS_PONS_PROTOCOL_CAPABILITIES_V0_BASE_CURVE_NO_SNIPE_VIEW",
}


def run_direct_quote_probe_v0(
    *,
    client,
    curve: str,
    recipient: str,
    factory_address: str | None = None,
    factory_lookback_blocks: int = 5_000,
    quote_in_raw: int | None = None,
    tokens_in_raw: int | None = None,
) -> dict:
    topic0 = client.sha3_text(TOKEN_LAUNCHED_SIGNATURE)
    discovery = discover_factory_v0(
        client,
        token_launched_topic0=topic0,
        lookback_blocks=factory_lookback_blocks,
        override_address=factory_address,
    )
    factory = discovery.get("selected_factory")
    if not factory:
        return {
            "classification": "HOLD_PONS_DIRECT_QUOTE_V0_FACTORY_UNRESOLVED",
            "factory_discovery": discovery,
            "economic_outcomes_opened": False,
            "fill_claimed": False,
        }

    capabilities = probe_protocol_capabilities_v0(
        client,
        factory=str(factory),
        token_launched_topic0=topic0,
        lookback_blocks=factory_lookback_blocks,
    )
    if capabilities.get("classification") not in PASS_CAPABILITIES:
        return {
            "classification": "HOLD_PONS_DIRECT_QUOTE_V0_CAPABILITIES_UNRESOLVED",
            "factory_discovery": discovery,
            "protocol_capabilities": capabilities,
            "economic_outcomes_opened": False,
            "fill_claimed": False,
        }

    state, evidence = read_curve_quote_state_v0(
        client,
        curve=curve,
        recipient=recipient,
        capability_report=capabilities,
    )
    buy = quote_buy_v0(state=state, quote_in_raw=quote_in_raw) if quote_in_raw is not None else None
    sell = quote_sell_v0(state=state, tokens_in_raw=tokens_in_raw) if tokens_in_raw is not None else None
    return {
        "classification": "PASS_PONS_DIRECT_QUOTE_V0",
        "factory_discovery": discovery,
        "protocol_capabilities": capabilities,
        "state_evidence": evidence,
        "buy_quote": asdict(buy) if buy is not None else None,
        "sell_quote": asdict(sell) if sell is not None else None,
        "economic_outcomes_opened": False,
        "fill_claimed": False,
        "notes": [
            "mathematical_curve_quote_only",
            "not_transaction_simulation",
            "not_landed_fill_evidence",
            "not_trade_recommendation",
        ],
    }


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--factory-address")
    parser.add_argument("--factory-lookback-blocks", type=int, default=5_000)
    parser.add_argument("--curve", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--quote-in-raw", type=int)
    parser.add_argument("--tokens-in-raw", type=int)
    args = parser.parse_args()

    if args.quote_in_raw is None and args.tokens_in_raw is None:
        parser.error("provide --quote-in-raw and/or --tokens-in-raw")
    if args.quote_in_raw is not None and args.quote_in_raw <= 0:
        parser.error("--quote-in-raw must be positive")
    if args.tokens_in_raw is not None and args.tokens_in_raw <= 0:
        parser.error("--tokens-in-raw must be positive")

    url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC
    client = RpcClient(url, 10)
    try:
        result = run_direct_quote_probe_v0(
            client=client,
            curve=args.curve,
            recipient=args.recipient,
            factory_address=args.factory_address,
            factory_lookback_blocks=args.factory_lookback_blocks,
            quote_in_raw=args.quote_in_raw,
            tokens_in_raw=args.tokens_in_raw,
        )
    except Exception as exc:
        result = {
            "classification": "FAIL_PONS_DIRECT_QUOTE_V0",
            "error": f"{type(exc).__name__}:{exc}",
            "economic_outcomes_opened": False,
            "fill_claimed": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
