"""Systems-only A/B benchmark for Pons direct-quote state transport.

The benchmark compares sequential JSON-RPC calls against strict JSON-RPC batch
calls. Each pair is pinned to the same explicit chain block, alternates execution
order, and must produce identical decoded curve state before latency is compared.

No BUY/SELL return, trade outcome, selector, signing, or submission is opened.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from statistics import median
import time
from typing import Any, Mapping

from benchmarks.robinhood_launch_burst_v0.direct_quote_state import read_curve_quote_state_v0
from benchmarks.robinhood_launch_burst_v0.factory_discovery import discover_factory_v0
from benchmarks.robinhood_launch_burst_v0.protocol_capabilities import probe_protocol_capabilities_v0
from benchmarks.robinhood_launch_burst_v0.rpc_batch_contract_v0 import BatchRpcClientV0
from src.robinhood_pons_launch_burst_v0 import TOKEN_LAUNCHED_SIGNATURE


BENCH_VERSION = "pons_direct_quote_transport_bench_v0"
PASS = "PASS_PONS_DIRECT_QUOTE_TRANSPORT_BENCH_V0"
FAIL = "FAIL_PONS_DIRECT_QUOTE_TRANSPORT_BENCH_V0"
HOLD = "HOLD_PONS_DIRECT_QUOTE_TRANSPORT_BENCH_V0"
DEFAULT_PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
PASS_CAPABILITIES = {
    "PASS_PONS_PROTOCOL_CAPABILITIES_V0_SNIPE_VIEW",
    "PASS_PONS_PROTOCOL_CAPABILITIES_V0_BASE_CURVE_NO_SNIPE_VIEW",
}


class SequentialRpcFacadeV0:
    """Expose single-call RPC only, deliberately hiding ``batch_call``."""

    def __init__(self, client):
        self._client = client

    def call(self, method, params):
        return self._client.call(method, params)

    def block_number(self):
        return self._client.block_number()

    def sha3_text(self, text):
        return self._client.sha3_text(text)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "n": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values) if values else None,
        "mean": (sum(values) / len(values)) if values else None,
    }


def _state_fingerprint(state) -> dict[str, Any]:
    payload = asdict(state)
    payload.pop("observed_at_ns", None)
    payload.pop("provenance", None)
    return payload


def _one_read(
    client,
    *,
    curve: str,
    recipient: str,
    capability_report: Mapping[str, Any],
    block_number: int,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    state, evidence = read_curve_quote_state_v0(
        client,
        curve=curve,
        recipient=recipient,
        capability_report=capability_report,
        block_number=block_number,
    )
    total_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return {
        "state": state,
        "evidence": evidence,
        "total_ms": total_ms,
        "fingerprint": _state_fingerprint(state),
    }


def run_transport_bench_v0(
    *,
    batch_client,
    curve: str,
    recipient: str,
    capability_report: Mapping[str, Any],
    iterations: int = 20,
) -> dict[str, Any]:
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations <= 0:
        raise ValueError("iterations must be a positive integer")
    if not callable(getattr(batch_client, "batch_call", None)):
        raise TypeError("batch_client must expose batch_call")

    sequential_client = SequentialRpcFacadeV0(batch_client)
    pairs = []
    errors = []
    sequential_ms = []
    batch_ms = []
    batch_service_ms = []
    parity_mismatches = 0

    for index in range(iterations):
        block_number = int(batch_client.block_number())
        order = ("sequential", "batch") if index % 2 == 0 else ("batch", "sequential")
        reads: dict[str, Any] = {}
        try:
            for mode in order:
                client = sequential_client if mode == "sequential" else batch_client
                reads[mode] = _one_read(
                    client,
                    curve=curve,
                    recipient=recipient,
                    capability_report=capability_report,
                    block_number=block_number,
                )

            sequential = reads["sequential"]
            batch = reads["batch"]
            same_state = sequential["fingerprint"] == batch["fingerprint"]
            same_block_hash = (
                sequential["evidence"]["block"]["hash"]
                == batch["evidence"]["block"]["hash"]
            )
            same_requested_block = (
                sequential["evidence"]["pinned_block_requested"] == block_number
                and batch["evidence"]["pinned_block_requested"] == block_number
            )
            parity = same_state and same_block_hash and same_requested_block
            if not parity:
                parity_mismatches += 1
            else:
                sequential_ms.append(float(sequential["total_ms"]))
                batch_ms.append(float(batch["total_ms"]))
                report = batch["evidence"].get("batch_report") or {}
                service = report.get("service_ms")
                if isinstance(service, (int, float)) and not isinstance(service, bool):
                    batch_service_ms.append(float(service))

            pairs.append(
                {
                    "index": index,
                    "block_number": block_number,
                    "block_hash": batch["evidence"]["block"]["hash"],
                    "execution_order": list(order),
                    "parity": parity,
                    "same_state": same_state,
                    "same_block_hash": same_block_hash,
                    "same_requested_block": same_requested_block,
                    "sequential_total_ms": sequential["total_ms"],
                    "batch_total_ms": batch["total_ms"],
                    "batch_service_ms": (batch["evidence"].get("batch_report") or {}).get("service_ms"),
                    "batch_response_reordered": (batch["evidence"].get("batch_report") or {}).get("response_reordered"),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "index": index,
                    "block_number": block_number,
                    "execution_order": list(order),
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    valid_pairs = len(pairs) - parity_mismatches
    all_valid = not errors and parity_mismatches == 0 and valid_pairs == iterations
    speedup_values = [
        seq / bat
        for seq, bat in zip(sequential_ms, batch_ms)
        if bat > 0
    ]
    delta_values = [
        seq - bat
        for seq, bat in zip(sequential_ms, batch_ms)
    ]
    classification = PASS if all_valid else FAIL
    return {
        "method_version": BENCH_VERSION,
        "classification": classification,
        "iterations_requested": iterations,
        "valid_pairs": valid_pairs,
        "parity_mismatches": parity_mismatches,
        "error_count": len(errors),
        "sequential_total_ms": _distribution(sequential_ms),
        "batch_total_ms": _distribution(batch_ms),
        "batch_http_service_ms": _distribution(batch_service_ms),
        "sequential_minus_batch_ms": _distribution(delta_values),
        "speedup_x": _distribution(speedup_values),
        "median_speedup_x": median(speedup_values) if speedup_values else None,
        "pairs": pairs,
        "errors": errors,
        "economic_outcomes_opened": False,
        "provider_route_outcomes_opened": False,
        "trade_returns_computed": False,
        "selector_modified": False,
        "notes": [
            "same_block_pairing_required_before_latency_comparison",
            "execution_order_alternates_to_reduce_order_and_cache_bias",
            "latency_statistics_include_only_exact_state_parity_pairs",
            "transport_benchmark_only_not_economic_evidence",
        ],
    }


def _resolve_capabilities(client, *, factory_address: str | None, lookback_blocks: int):
    topic0 = client.sha3_text(TOKEN_LAUNCHED_SIGNATURE)
    discovery = discover_factory_v0(
        client,
        token_launched_topic0=topic0,
        lookback_blocks=lookback_blocks,
        override_address=factory_address,
    )
    factory = discovery.get("selected_factory")
    if not factory:
        return discovery, None
    capabilities = probe_protocol_capabilities_v0(
        client,
        factory=str(factory),
        token_launched_topic0=topic0,
        lookback_blocks=lookback_blocks,
    )
    return discovery, capabilities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--factory-address")
    parser.add_argument("--factory-lookback-blocks", type=int, default=5_000)
    parser.add_argument("--curve", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()

    url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC
    client = BatchRpcClientV0(url, 10)
    try:
        discovery, capabilities = _resolve_capabilities(
            client,
            factory_address=args.factory_address,
            lookback_blocks=args.factory_lookback_blocks,
        )
        if capabilities is None:
            result = {
                "method_version": BENCH_VERSION,
                "classification": HOLD,
                "hold_reason": "FACTORY_UNRESOLVED",
                "factory_discovery": discovery,
                "economic_outcomes_opened": False,
            }
        elif capabilities.get("classification") not in PASS_CAPABILITIES:
            result = {
                "method_version": BENCH_VERSION,
                "classification": HOLD,
                "hold_reason": "CAPABILITY_UNRESOLVED",
                "factory_discovery": discovery,
                "protocol_capabilities": capabilities,
                "economic_outcomes_opened": False,
            }
        else:
            result = run_transport_bench_v0(
                batch_client=client,
                curve=args.curve,
                recipient=args.recipient,
                capability_report=capabilities,
                iterations=args.iterations,
            )
            result["factory_discovery"] = discovery
            result["protocol_capabilities"] = capabilities
    except Exception as exc:
        result = {
            "method_version": BENCH_VERSION,
            "classification": FAIL,
            "error": f"{type(exc).__name__}:{exc}",
            "economic_outcomes_opened": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
