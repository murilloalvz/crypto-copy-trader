"""Prospective feature-only Robinhood/Pons Launch Burst V0 collector."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.robinhood_launch_burst_v0.factory_discovery import discover_factory_v0
from src.robinhood_pons_launch_burst_v0 import (
    CURVE_BUY_SIGNATURE,
    CURVE_SELL_SIGNATURE,
    METHOD_VERSION,
    ROBINHOOD_CHAIN_ID,
    TOKEN_LAUNCHED_SIGNATURE,
    WINDOWS_SECONDS,
    RobinhoodPonsBurstBookV0,
    decode_curve_trade_log_v0,
    decode_token_launched_log_v0,
)

DEFAULT_PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"


class JsonRpcError(RuntimeError):
    pass


class RpcClient:
    def __init__(self, url, timeout_s=10.0):
        if not isinstance(url, str) or not url.strip():
            raise ValueError("RPC url must be non-empty")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.url = url.strip()
        self.timeout_s = float(timeout_s)
        self._id = 0

    def call(self, method, params):
        if not isinstance(method, str) or not method:
            raise ValueError("method must be non-empty")
        self._id += 1
        request_id = self._id
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        ).encode()
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JsonRpcError(f"{method} transport failure: {exc}") from exc
        if not isinstance(body, dict):
            raise JsonRpcError(f"{method} response must be a JSON object")
        if body.get("id") != request_id:
            raise JsonRpcError(
                f"{method} response id mismatch: expected={request_id} got={body.get('id')}"
            )
        if body.get("error") is not None:
            raise JsonRpcError(f"{method} rpc error: {body['error']}")
        if "result" not in body:
            raise JsonRpcError(f"{method} response missing result")
        return body["result"]

    def chain_id(self):
        value = self.call("eth_chainId", [])
        try:
            return int(str(value), 16)
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(f"invalid eth_chainId response: {value!r}") from exc

    def block_number(self):
        value = self.call("eth_blockNumber", [])
        try:
            return int(str(value), 16)
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(f"invalid eth_blockNumber response: {value!r}") from exc

    def block_timestamp(self, number):
        row = self.call("eth_getBlockByNumber", [hex(number), False])
        if not isinstance(row, dict) or row.get("timestamp") is None:
            raise JsonRpcError(f"missing block timestamp for {number}")
        try:
            return int(str(row["timestamp"]), 16)
        except (TypeError, ValueError) as exc:
            raise JsonRpcError(
                f"invalid block timestamp for {number}: {row.get('timestamp')!r}"
            ) from exc

    def sha3_text(self, text):
        value = self.call("web3_sha3", ["0x" + text.encode().hex()])
        if not isinstance(value, str) or not value.startswith("0x"):
            raise JsonRpcError("invalid web3_sha3 response")
        return value.lower()

    def get_logs(self, from_block, to_block, addresses):
        if from_block > to_block:
            return []
        query = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "address": addresses,
        }
        rows = self.call("eth_getLogs", [query])
        if not isinstance(rows, list):
            raise JsonRpcError("eth_getLogs did not return a list")
        return [row for row in rows if isinstance(row, dict)]


def _write(path, row):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    low = int(position)
    high = min(low + 1, len(values) - 1)
    fraction = position - low
    return values[low] * (1 - fraction) + values[high] * fraction


def _summary(values):
    return {
        "n": len(values),
        "p50": _percentile(values, 0.5),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def _features(snapshots):
    output = {}
    for horizon in WINDOWS_SECONDS:
        cohort = [
            row
            for row in snapshots
            if row["native_eth_cohort"] and row["horizon_seconds"] == horizon
        ]
        output[str(horizon)] = {
            "n": len(cohort),
            "nonempty": sum(row["trade_count"] > 0 for row in cohort),
            "trade_count": _summary([float(row["trade_count"]) for row in cohort]),
            "signed_quote_flow_over_activity": _summary(
                [
                    row["signed_quote_flow_over_activity"]
                    for row in cohort
                    if row["signed_quote_flow_over_activity"] is not None
                ]
            ),
            "buy_fee_share_bps_observed": _summary(
                [
                    row["buy_fee_share_bps_observed"]
                    for row in cohort
                    if row["buy_fee_share_bps_observed"] is not None
                ]
            ),
            "buy_total_charge_share_bps_observed": _summary(
                [
                    row["buy_total_charge_share_bps_observed"]
                    for row in cohort
                    if row["buy_total_charge_share_bps_observed"] is not None
                ]
            ),
            "deployer_buy_quote_share": _summary(
                [
                    row["deployer_buy_quote_share"]
                    for row in cohort
                    if row["deployer_buy_quote_share"] is not None
                ]
            ),
            "top1_buyer_quote_share": _summary(
                [
                    row["top1_buyer_quote_share"]
                    for row in cohort
                    if row["top1_buyer_quote_share"] is not None
                ]
            ),
            "time_to_5_trades_ms": _summary(
                [
                    row["time_to_5_trades_ms"]
                    for row in cohort
                    if row["time_to_5_trades_ms"] is not None
                ]
            ),
            "snapshot_dispatch_lag_ms": _summary(
                [row["snapshot_dispatch_lag_ms"] for row in cohort]
            ),
        }
    return output


def _stamp_block_timestamp(client, cache, raw):
    block_number = int(str(raw.get("blockNumber", "0x0")), 16)
    if block_number not in cache:
        cache[block_number] = client.block_timestamp(block_number)
    raw["block_timestamp_s"] = cache[block_number]


def run(args):
    load_dotenv()
    rpc_url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC
    run_id = f"robinhood_launch_burst_v0-{int(time.time())}-{uuid.uuid4().hex[:10]}"
    run_dir = Path(args.artifacts_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    events_path = run_dir / "events.jsonl"
    snapshots_path = run_dir / "snapshots.jsonl"
    report_path = run_dir / "report.json"

    client = RpcClient(rpc_url, args.rpc_timeout_seconds)
    errors = []
    book = RobinhoodPonsBurstBookV0()
    snapshots = []
    block_timestamp_cache = {}
    poll_latency_ms = []
    start_ns = time.time_ns()
    stop_reason = "unknown"
    initial_block = None
    final_block = None
    polls = 0
    discovery = None
    selected_factory = None
    failure_stage = "preflight_chain_id"
    preflight_completed = False

    try:
        chain_id = client.chain_id()
        if chain_id != ROBINHOOD_CHAIN_ID:
            raise RuntimeError(f"wrong chain id: {chain_id}")

        failure_stage = "preflight_topic_hashes"
        topics = {
            "token_launched": client.sha3_text(TOKEN_LAUNCHED_SIGNATURE),
            "curve_buy": client.sha3_text(CURVE_BUY_SIGNATURE),
            "curve_sell": client.sha3_text(CURVE_SELL_SIGNATURE),
        }

        failure_stage = "preflight_factory_discovery"
        discovery = discover_factory_v0(
            client,
            token_launched_topic0=topics["token_launched"],
            lookback_blocks=args.factory_lookback_blocks,
            override_address=args.factory_address,
        )
        if not str(discovery["classification"]).startswith("PASS"):
            raise RuntimeError(
                "factory discovery not uniquely runnable: " + discovery["classification"]
            )
        selected_factory = discovery["selected_factory"]

        failure_stage = "preflight_initial_block"
        latest = client.block_number()
        initial_block = latest
        next_block = latest + 1
        preflight_completed = True
        failure_stage = "capture_loop"

        while True:
            if (time.time_ns() - start_ns) / 1e9 >= args.duration_seconds:
                stop_reason = "duration_elapsed"
                break

            poll_started = time.perf_counter_ns()
            try:
                latest = client.block_number()
                polls += 1
                if latest >= next_block:
                    from_block = next_block
                    to_block = min(latest, next_block + args.max_block_span - 1)

                    factory_logs = client.get_logs(
                        from_block, to_block, selected_factory
                    )
                    factory_receipt_ns = time.time_ns()
                    new_curves = []
                    for raw in factory_logs:
                        raw["observed_at_ns"] = factory_receipt_ns
                        _stamp_block_timestamp(client, block_timestamp_cache, raw)
                        launch = decode_token_launched_log_v0(
                            raw, topic0=topics["token_launched"]
                        )
                        if launch and book.add_launch(launch):
                            new_curves.append(launch.curve)
                            _write(events_path, {"kind": "launch", **launch.__dict__})

                    wall_ns = time.time_ns()
                    active_curves = [
                        curve
                        for curve, launch in book.launches_by_curve.items()
                        if wall_ns <= launch.observed_at_ns + 35_000_000_000
                    ]
                    for curve in new_curves:
                        if curve not in active_curves:
                            active_curves.append(curve)

                    if active_curves:
                        trade_logs = client.get_logs(
                            from_block, to_block, active_curves
                        )
                        trade_receipt_ns = time.time_ns()
                        for raw in trade_logs:
                            raw["observed_at_ns"] = trade_receipt_ns
                            _stamp_block_timestamp(client, block_timestamp_cache, raw)
                            trade = decode_curve_trade_log_v0(
                                raw,
                                buy_topic0=topics["curve_buy"],
                                sell_topic0=topics["curve_sell"],
                            )
                            if trade and book.add_trade(trade):
                                _write(events_path, {"kind": "trade", **trade.__dict__})

                    final_block = to_block
                    next_block = to_block + 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}:{exc}")
                if len(errors) >= args.max_transport_errors:
                    stop_reason = "transport_error_limit"
                    break

            snapshot_now_ns = time.time_ns()
            for snapshot in book.ready_snapshots(snapshot_now_ns):
                row = snapshot.to_dict()
                snapshots.append(row)
                _write(snapshots_path, row)

            poll_latency_ms.append((time.perf_counter_ns() - poll_started) / 1e6)
            time.sleep(args.poll_ms / 1000)

        failure_stage = "final_snapshot_flush"
        snapshot_now_ns = time.time_ns()
        for snapshot in book.ready_snapshots(snapshot_now_ns):
            row = snapshot.to_dict()
            snapshots.append(row)
            _write(snapshots_path, row)

        failure_stage = "report_build"
        counts = book.counts()
        gates = {
            "chain_id_correct": chain_id == ROBINHOOD_CHAIN_ID,
            "factory_uniquely_selected": selected_factory is not None,
            "transport_errors_zero": len(errors) == 0,
            "feature_only": True,
            "economic_outcomes_closed": True,
            "selector_unfrozen": True,
        }
        if stop_reason == "transport_error_limit":
            classification = "FAIL_ROBINHOOD_LAUNCH_BURST_TRANSPORT_V0"
        elif counts["native_eth_launches"] == 0:
            classification = "PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_V0_NO_NATIVE_LAUNCHES"
        else:
            classification = "PASS_ROBINHOOD_LAUNCH_BURST_FEATURE_CAPTURE_V0"

        report = {
            "type": "robinhood_pons_launch_burst_live_report_v0",
            "method_version": METHOD_VERSION,
            "classification": classification,
            "feature_only": True,
            "economic_outcomes_opened": False,
            "selector_frozen": False,
            "preflight_completed": preflight_completed,
            "chain_id": chain_id,
            "factory": selected_factory,
            "factory_discovery": discovery,
            "rpc_kind": "json_rpc_polling_v0",
            "public_rpc_default_used": rpc_url == DEFAULT_PUBLIC_RPC,
            "start_wall_ns": start_ns,
            "finished_wall_ns": time.time_ns(),
            "duration_seconds_requested": args.duration_seconds,
            "stop_reason": stop_reason,
            "initial_block": initial_block,
            "final_block": final_block,
            "polls": polls,
            "poll_ms": args.poll_ms,
            "poll_latency_ms": _summary(poll_latency_ms),
            "counts": counts,
            "feature_report_native_eth": _features(snapshots),
            "topic0": topics,
            "transport_errors": errors,
            "gates": gates,
            "notes": [
                "feature_only_no_selector_no_outcomes",
                "native_eth_launches_are_headline_cohort",
                "custom_pair_launches_preserved_as_coverage_only",
                "availability_clock_is_batch_receipt_observed_at_ns",
                "block_timestamp_lookup_does_not_move_availability_clock",
                "json_rpc_polling_is_bootstrap_acquisition_not_final_sequencer_feed",
                "factory_selected_by_live_bytecode_plus_recent_event_discovery",
                "single_rpc_responses_are_matched_to_request_id_fail_closed",
            ],
        }
    except Exception as exc:
        report = {
            "type": "robinhood_pons_launch_burst_live_report_v0",
            "method_version": METHOD_VERSION,
            "classification": "FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0",
            "feature_only": True,
            "economic_outcomes_opened": False,
            "selector_frozen": False,
            "preflight_completed": preflight_completed,
            "failure_stage": failure_stage,
            "factory": selected_factory,
            "factory_discovery": discovery,
            "error": f"{type(exc).__name__}:{exc}",
            "transport_errors": errors,
        }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--poll-ms", type=int, default=350)
    parser.add_argument("--max-block-span", type=int, default=20)
    parser.add_argument("--max-transport-errors", type=int, default=5)
    parser.add_argument("--rpc-timeout-seconds", type=float, default=10)
    parser.add_argument("--rpc-url")
    parser.add_argument("--factory-address")
    parser.add_argument("--factory-lookback-blocks", type=int, default=5_000)
    parser.add_argument("--artifacts-root", default="artifacts/robinhood_launch_burst_v0")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
