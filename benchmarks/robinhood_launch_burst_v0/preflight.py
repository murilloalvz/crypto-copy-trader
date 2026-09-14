"""Network + factory + deployed-protocol preflight for Robinhood/Pons Launch Burst V0."""
from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from benchmarks.robinhood_launch_burst_v0.factory_discovery import discover_factory_v0
from benchmarks.robinhood_launch_burst_v0.live import DEFAULT_PUBLIC_RPC, RpcClient
from benchmarks.robinhood_launch_burst_v0.protocol_capabilities import probe_protocol_capabilities_v0
from src.robinhood_pons_launch_burst_v0 import (
    CURVE_BUY_SIGNATURE,
    CURVE_SELL_SIGNATURE,
    ROBINHOOD_CHAIN_ID,
    TOKEN_LAUNCHED_SIGNATURE,
)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--factory-address")
    parser.add_argument("--factory-lookback-blocks", type=int, default=5_000)
    args = parser.parse_args()

    url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC
    client = RpcClient(url, 10)
    try:
        chain = client.chain_id()
        latest = client.block_number()
        topics = {
            "TokenLaunched": client.sha3_text(TOKEN_LAUNCHED_SIGNATURE),
            "CurveBuy": client.sha3_text(CURVE_BUY_SIGNATURE),
            "CurveSell": client.sha3_text(CURVE_SELL_SIGNATURE),
        }
        discovery = discover_factory_v0(
            client,
            token_launched_topic0=topics["TokenLaunched"],
            lookback_blocks=args.factory_lookback_blocks,
            override_address=args.factory_address,
        )
        factory_ok = str(discovery["classification"]).startswith("PASS")
        capabilities = None
        capability_ok = False
        selected_factory = discovery.get("selected_factory")
        if factory_ok and selected_factory:
            capabilities = probe_protocol_capabilities_v0(
                client,
                factory=selected_factory,
                token_launched_topic0=topics["TokenLaunched"],
                lookback_blocks=args.factory_lookback_blocks,
            )
            capability_ok = str(capabilities["classification"]).startswith("PASS")
        classification = (
            "PASS_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0"
            if chain == ROBINHOOD_CHAIN_ID and factory_ok and capability_ok
            else "HOLD_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0"
        )
        result = {
            "classification": classification,
            "chain_id": chain,
            "expected_chain_id": ROBINHOOD_CHAIN_ID,
            "latest_block": latest,
            "selected_factory": selected_factory,
            "factory_discovery": discovery,
            "protocol_capabilities": capabilities,
            "protocol_generation_key": (capabilities or {}).get("generation_key"),
            "public_rpc_default_used": url == DEFAULT_PUBLIC_RPC,
            "topic0": topics,
            "economic_outcomes_opened": False,
            "notes": [
                "factory_addresses_are_versioned_evidence_not_eternal_constants",
                "multiple_active_factories_must_be_captured_as_separate_strata",
                "deployed_curve_capabilities_override_repository_semantic_assumptions",
                "public_rpc_is_bootstrap_only_not_latency_grade",
            ],
        }
    except Exception as exc:
        result = {
            "classification": "FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0",
            "error": f"{type(exc).__name__}:{exc}",
            "economic_outcomes_opened": False,
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
