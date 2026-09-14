"""Dependency-free strict JSON-RPC transport for Robinhood read-only calls.

The live collector intentionally has its own environment/bootstrap dependencies.
Direct-quote transport must not inherit those dependencies merely to make RPC
calls, so this module owns the small JSON-RPC surface it needs.

Batch responses are never matched by array position. Every item is reconstructed
by its unique JSON-RPC ``id``; malformed, missing, duplicate, unexpected, or
per-item error responses fail the whole batch.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


BATCH_CONTRACT_VERSION = "robinhood_rpc_batch_v0"


class JsonRpcErrorV0(RuntimeError):
    pass


class BatchRpcClientV0:
    """Small dependency-free JSON-RPC client with strict batch support."""

    def __init__(self, url: str, timeout_s: float = 10.0):
        if not isinstance(url, str) or not url.strip():
            raise ValueError("RPC url must be non-empty")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.url = url.strip()
        self.timeout_s = float(timeout_s)
        self._id = 0
        self.last_batch_report = None

    def _post_json(self, payload, *, label: str):
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JsonRpcErrorV0(f"{label} transport failure: {exc}") from exc

    def call(self, method: str, params):
        if not isinstance(method, str) or not method:
            raise ValueError("method must be non-empty")
        self._id += 1
        request_id = self._id
        body = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            label=method,
        )
        if not isinstance(body, dict):
            raise JsonRpcErrorV0(f"{method} response must be a JSON object")
        if body.get("id") != request_id:
            raise JsonRpcErrorV0(
                f"{method} response id mismatch: expected={request_id} got={body.get('id')}"
            )
        if body.get("error") is not None:
            raise JsonRpcErrorV0(f"{method} rpc error: {body['error']}")
        if "result" not in body:
            raise JsonRpcErrorV0(f"{method} response missing result")
        return body["result"]

    def chain_id(self) -> int:
        value = self.call("eth_chainId", [])
        return int(str(value), 16)

    def block_number(self) -> int:
        value = self.call("eth_blockNumber", [])
        return int(str(value), 16)

    def block_timestamp(self, number: int) -> int:
        row = self.call("eth_getBlockByNumber", [hex(int(number)), False])
        if not isinstance(row, dict) or row.get("timestamp") is None:
            raise JsonRpcErrorV0(f"missing block timestamp for {number}")
        return int(str(row["timestamp"]), 16)

    def sha3_text(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        value = self.call("web3_sha3", ["0x" + text.encode().hex()])
        if not isinstance(value, str) or not value.startswith("0x"):
            raise JsonRpcErrorV0("invalid web3_sha3 response")
        return value.lower()

    def batch_call(self, calls):
        """Execute ``[(method, params), ...]`` in one HTTP round trip.

        Results are returned in original request order after strict id-based
        reconstruction. Provider response ordering is explicitly irrelevant.
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

        started = time.perf_counter_ns()
        body = self._post_json(payload, label="batch")
        service_ms = (time.perf_counter_ns() - started) / 1_000_000.0

        if not isinstance(body, list):
            raise JsonRpcErrorV0("batch response must be a JSON array")
        if len(body) != len(payload):
            raise JsonRpcErrorV0(
                f"batch response count mismatch: expected={len(payload)} got={len(body)}"
            )

        by_id = {}
        response_ids = []
        for position, item in enumerate(body):
            if not isinstance(item, dict):
                raise JsonRpcErrorV0(f"batch response item {position} is not an object")
            response_id = item.get("id")
            if not isinstance(response_id, int) or isinstance(response_id, bool):
                raise JsonRpcErrorV0(f"batch response item {position} has invalid id")
            if response_id in by_id:
                raise JsonRpcErrorV0(f"batch response contains duplicate id={response_id}")
            by_id[response_id] = item
            response_ids.append(response_id)

        expected = set(request_ids)
        actual = set(by_id)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            raise JsonRpcErrorV0(
                f"batch id mismatch: missing={missing} unexpected={unexpected}"
            )

        results = []
        for index, (request_id, method) in enumerate(zip(request_ids, methods)):
            item = by_id[request_id]
            if item.get("error") is not None:
                raise JsonRpcErrorV0(
                    f"batch[{index}] {method} rpc error: {item['error']}"
                )
            if "result" not in item:
                raise JsonRpcErrorV0(f"batch[{index}] {method} missing result")
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
