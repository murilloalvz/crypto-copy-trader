"""Strict JSON-RPC batch transport for Robinhood read-only state calls.

Robinhood RPC providers may return batch items out of request order. This client
never trusts position: every item is matched by its unique JSON-RPC ``id`` and
the caller receives results in original request order.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from benchmarks.robinhood_launch_burst_v0.live import JsonRpcError, RpcClient


BATCH_CONTRACT_VERSION = "robinhood_rpc_batch_v0"


class BatchRpcClientV0(RpcClient):
    """RpcClient with strict, order-independent JSON-RPC batching."""

    def __init__(self, url, timeout_s=10.0):
        super().__init__(url, timeout_s)
        self.last_batch_report = None

    def batch_call(self, calls):
        """Execute ``[(method, params), ...]`` in one HTTP round trip.

        Responses are reconstructed by JSON-RPC id. Missing ids, duplicate ids,
        unexpected ids, malformed items, or any per-item RPC error fail the
        whole batch rather than silently shifting results between calls.
        """
        if not isinstance(calls, (list, tuple)) or not calls:
            raise ValueError("batch calls must be a non-empty list or tuple")

        payload = []
        request_ids = []
        methods = []
        for index, item in enumerate(calls):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise TypeError(f"batch item {index} must be (method, params)")
            method, params = item
            if not isinstance(method, str) or not method:
                raise ValueError(f"batch item {index} has invalid method")
            self._id += 1
            request_id = self._id
            request_ids.append(request_id)
            methods.append(method)
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )

        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        started = time.perf_counter_ns()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JsonRpcError(f"batch transport failure: {exc}") from exc
        service_ms = (time.perf_counter_ns() - started) / 1_000_000.0

        if not isinstance(body, list):
            raise JsonRpcError("batch response must be a JSON array")
        if len(body) != len(payload):
            raise JsonRpcError(
                f"batch response count mismatch: expected={len(payload)} got={len(body)}"
            )

        by_id = {}
        response_ids = []
        for position, item in enumerate(body):
            if not isinstance(item, dict):
                raise JsonRpcError(f"batch response item {position} is not an object")
            response_id = item.get("id")
            if not isinstance(response_id, int):
                raise JsonRpcError(f"batch response item {position} has invalid id")
            if response_id in by_id:
                raise JsonRpcError(f"batch response contains duplicate id={response_id}")
            by_id[response_id] = item
            response_ids.append(response_id)

        expected = set(request_ids)
        actual = set(by_id)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            raise JsonRpcError(
                f"batch id mismatch: missing={missing} unexpected={unexpected}"
            )

        results = []
        for index, (request_id, method) in enumerate(zip(request_ids, methods)):
            item = by_id[request_id]
            if item.get("error") is not None:
                raise JsonRpcError(
                    f"batch[{index}] {method} rpc error: {item['error']}"
                )
            if "result" not in item:
                raise JsonRpcError(f"batch[{index}] {method} missing result")
            results.append(item["result"])

        self.last_batch_report = {
            "contract_version": BATCH_CONTRACT_VERSION,
            "request_count": len(payload),
            "service_ms": service_ms,
            "response_reordered": response_ids != request_ids,
            "request_ids": request_ids,
            "response_ids": response_ids,
        }
        return results
