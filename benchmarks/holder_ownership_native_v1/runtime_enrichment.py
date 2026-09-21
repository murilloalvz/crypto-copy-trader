from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import math
from pathlib import Path
import time
from typing import Any, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3
from benchmarks.launch_burst_prospective_route_paper_v2 import live as paper_v2


VERSION = "holder_ownership_native_runtime_v1"
FEATURE_ID = "mf_holder_pump_pregrad_non_curve_owner_supply_hhi_native"
EXTERNAL_EVIDENCE_KEY = "holder_ownership_native_v1"
SNAPSHOT_REQUEST_NOT_BEFORE_SECONDS = 3.0
DECISION_CUTOFF_SECONDS = 5.0
PAGE_LIMIT = 1000
MAX_PAGES = 10


def _helius_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY is required for native Holder Ownership V1")
    return f"https://mainnet.helius-rpc.com/?api-key={key}"


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int_amount(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _rpc_once(
    *,
    api_key: str,
    method: str,
    params: Any,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = _helius_url(api_key)
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    request_before_wall_ns = time.time_ns()
    started = time.perf_counter_ns()
    try:
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "crypto-copy-trader/0.3"},
            method="POST",
        )
        with urlopen(request, timeout=max(0.05, timeout_seconds)) as response:
            status_code = int(getattr(response, "status", 200))
            payload = json.loads(response.read().decode("utf-8"))
        error = None
    except HTTPError as exc:
        status_code = int(exc.code)
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        error = f"HTTP_{status_code}"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        status_code = None
        payload = None
        error = f"{type(exc).__name__}:{exc}"[:300]

    response_after_wall_ns = time.time_ns()
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    result = payload.get("result") if isinstance(payload, dict) else None
    rpc_error = payload.get("error") if isinstance(payload, dict) else None
    if error is None and rpc_error is not None:
        error = f"RPC_ERROR:{rpc_error}"[:300]

    return {
        "method": method,
        "request_before_wall_ns": request_before_wall_ns,
        "response_after_wall_ns": response_after_wall_ns,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "error": error,
        "rate_limited": status_code == 429,
        "result": result,
        "private_key_used": False,
        "capital_used": False,
        "retry_count": 0,
    }


def _compact_call(call: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(call, Mapping):
        return None
    return {
        "method": call.get("method"),
        "request_before_wall_ns": call.get("request_before_wall_ns"),
        "response_after_wall_ns": call.get("response_after_wall_ns"),
        "duration_ms": call.get("duration_ms"),
        "status_code": call.get("status_code"),
        "error": call.get("error"),
        "rate_limited": call.get("rate_limited") is True,
        "private_key_used": False,
        "capital_used": False,
        "retry_count": int(call.get("retry_count") or 0),
    }


def _collect_native_holder_evidence_sync(
    *,
    token_mint: str,
    bonding_curve: str,
    observed_t0_wall_ns: int,
    decision_cutoff_wall_ns: int,
    api_key: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": VERSION,
        "token_mint": token_mint,
        "bonding_curve": bonding_curve,
        "observed_t0_wall_ns": int(observed_t0_wall_ns),
        "decision_cutoff_wall_ns": int(decision_cutoff_wall_ns),
        "status": "NOT_STARTED",
        "feature_id": FEATURE_ID,
        "feature_value": None,
        "private_key_used": False,
        "capital_used": False,
        "selector_changed": False,
        "threshold_search_performed": False,
        "automatic_entry_rule_created": False,
        "retry_count": 0,
    }

    def remaining() -> float:
        return (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0

    if remaining() <= 0:
        base["status"] = "LATE_BEFORE_TOKEN_SUPPLY"
        return base

    supply_call = _rpc_once(
        api_key=api_key,
        method="getTokenSupply",
        params=[token_mint, {"commitment": "confirmed"}],
        timeout_seconds=min(1.5, max(0.05, remaining())),
    )
    base["token_supply_call"] = supply_call
    if supply_call.get("rate_limited") is True:
        base["status"] = "HELIUS_RATE_LIMITED"
        return base
    if supply_call.get("error") is not None:
        base["status"] = "TOKEN_SUPPLY_ERROR"
        return base
    if int(supply_call.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_TOKEN_SUPPLY"
        return base

    supply_result = supply_call.get("result")
    supply_value = supply_result.get("value") if isinstance(supply_result, dict) else None
    total_supply_raw = _int_amount((supply_value or {}).get("amount") if isinstance(supply_value, dict) else None)
    if total_supply_raw is None or total_supply_raw <= 0:
        base["status"] = "TOKEN_SUPPLY_INVALID"
        return base

    owner_amounts: dict[str, int] = {}
    account_count = 0
    account_calls: list[dict[str, Any]] = []
    pagination_complete = False

    for page in range(1, MAX_PAGES + 1):
        if remaining() <= 0:
            base["status"] = "LATE_DURING_TOKEN_ACCOUNTS"
            base["token_account_calls"] = account_calls
            return base
        call = _rpc_once(
            api_key=api_key,
            method="getTokenAccounts",
            params={
                "page": page,
                "limit": PAGE_LIMIT,
                "displayOptions": {},
                "mint": token_mint,
            },
            timeout_seconds=min(1.5, max(0.05, remaining())),
        )
        account_calls.append(call)
        if call.get("rate_limited") is True:
            base["status"] = "HELIUS_RATE_LIMITED"
            base["token_account_calls"] = account_calls
            return base
        if call.get("error") is not None:
            base["status"] = "TOKEN_ACCOUNTS_ERROR"
            base["token_account_calls"] = account_calls
            return base
        if int(call.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
            base["status"] = "LATE_TOKEN_ACCOUNTS"
            base["token_account_calls"] = account_calls
            return base

        result = call.get("result")
        rows = result.get("token_accounts") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            base["status"] = "TOKEN_ACCOUNTS_INVALID_PAYLOAD"
            base["token_account_calls"] = account_calls
            return base

        for row in rows:
            if not isinstance(row, dict):
                base["status"] = "TOKEN_ACCOUNT_ROW_INVALID"
                base["token_account_calls"] = account_calls
                return base
            owner = str(row.get("owner") or "").strip()
            amount = _int_amount(row.get("amount"))
            if not owner or amount is None:
                base["status"] = "TOKEN_ACCOUNT_ROW_INVALID"
                base["token_account_calls"] = account_calls
                return base
            account_count += 1
            owner_amounts[owner] = owner_amounts.get(owner, 0) + amount

        if len(rows) < PAGE_LIMIT:
            pagination_complete = True
            break

    base["token_account_calls"] = account_calls
    if not pagination_complete:
        base["status"] = "PAGINATION_LIMIT_OR_INCOMPLETE"
        return base
    if account_count == 0:
        base["status"] = "TOKEN_ACCOUNTS_EMPTY"
        return base

    bonding_curve_amount_raw = int(owner_amounts.get(bonding_curve, 0))
    non_curve_owner_amounts = {
        owner: amount
        for owner, amount in owner_amounts.items()
        if owner != bonding_curve and amount > 0
    }
    if not non_curve_owner_amounts:
        base["status"] = "NO_NON_CURVE_OWNERS"
        return base

    feature_value = sum(
        (float(amount) / float(total_supply_raw)) ** 2
        for amount in non_curve_owner_amounts.values()
    )
    if not math.isfinite(feature_value) or feature_value < 0.0 or feature_value > 1.0000000001:
        base["status"] = "FEATURE_DERIVATION_INVALID"
        return base

    base.update(
        {
            "status": "CAUSAL_AVAILABLE",
            "feature_value": feature_value,
            "total_supply_raw": total_supply_raw,
            "token_account_count": account_count,
            "unique_owner_count": len(owner_amounts),
            "non_curve_owner_count": len(non_curve_owner_amounts),
            "bonding_curve_amount_raw": bonding_curve_amount_raw,
            "owner_amounts_raw": owner_amounts,
            "denominator": "total_supply_raw",
            "excluded_market_owner": bonding_curve,
            "pagination_complete": True,
            "snapshot_request_before_wall_ns": int(
                min(
                    [supply_call["request_before_wall_ns"]]
                    + [call["request_before_wall_ns"] for call in account_calls]
                )
            ),
            "snapshot_response_after_wall_ns": int(
                max(
                    [supply_call["response_after_wall_ns"]]
                    + [call["response_after_wall_ns"] for call in account_calls]
                )
            ),
        }
    )
    return base


def _compact_evidence(record: Mapping[str, Any] | None, *, pending: bool) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {
            "version": VERSION,
            "status": "PENDING_AT_FREEZE" if pending else "NOT_STARTED",
            "feature_id": FEATURE_ID,
            "feature_value": None,
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
        }
    keys = (
        "version",
        "status",
        "feature_id",
        "feature_value",
        "bonding_curve",
        "total_supply_raw",
        "token_account_count",
        "unique_owner_count",
        "non_curve_owner_count",
        "bonding_curve_amount_raw",
        "denominator",
        "excluded_market_owner",
        "pagination_complete",
        "snapshot_request_before_wall_ns",
        "snapshot_response_after_wall_ns",
        "graduation_observed_wall_ns",
        "private_key_used",
        "capital_used",
        "selector_changed",
        "threshold_search_performed",
        "automatic_entry_rule_created",
        "retry_count",
    )
    compact = {key: record.get(key) for key in keys if key in record}
    compact["token_supply_call"] = _compact_call(record.get("token_supply_call"))
    compact["token_account_calls"] = [
        _compact_call(call) for call in (record.get("token_account_calls") or [])
    ]
    return compact


class HolderOwnershipNativeRuntimeV1:
    def __init__(self, *, helius_api_key: str) -> None:
        if not helius_api_key.strip():
            raise ValueError("HELIUS_API_KEY is required for native Holder Ownership V1")
        self.helius_api_key = helius_api_key.strip()
        self.records: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.decision_cutoff_wall_ns_by_token: dict[str, int] = {}
        self.graduation_wall_ns_by_token: dict[str, int] = {}

    def mark_graduation(self, *, token_mint: str, observed_wall_ns: int) -> None:
        current = self.graduation_wall_ns_by_token.get(token_mint)
        if current is None or int(observed_wall_ns) < current:
            self.graduation_wall_ns_by_token[token_mint] = int(observed_wall_ns)
        record = self.records.get(token_mint)
        if isinstance(record, dict):
            request_before = record.get("snapshot_request_before_wall_ns")
            if (
                isinstance(request_before, int)
                and self.graduation_wall_ns_by_token[token_mint] <= request_before
                and record.get("status") == "CAUSAL_AVAILABLE"
            ):
                record["status"] = "GRADUATED_BEFORE_SNAPSHOT"
                record["feature_value"] = None
                record["graduation_observed_wall_ns"] = self.graduation_wall_ns_by_token[token_mint]

    async def _acquire(
        self,
        *,
        token_mint: str,
        bonding_curve: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
    ) -> None:
        try:
            request_not_before_ns = int(
                observed_t0_wall_ns + SNAPSHOT_REQUEST_NOT_BEFORE_SECONDS * 1_000_000_000
            )
            wait_seconds = max(0.0, (request_not_before_ns - time.time_ns()) / 1_000_000_000.0)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            graduation_ns = self.graduation_wall_ns_by_token.get(token_mint)
            if graduation_ns is not None and graduation_ns <= time.time_ns():
                self.records[token_mint] = {
                    "version": VERSION,
                    "token_mint": token_mint,
                    "bonding_curve": bonding_curve,
                    "observed_t0_wall_ns": observed_t0_wall_ns,
                    "decision_cutoff_wall_ns": decision_cutoff_wall_ns,
                    "status": "GRADUATED_BEFORE_SNAPSHOT",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "graduation_observed_wall_ns": graduation_ns,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                    "retry_count": 0,
                }
                return

            if time.time_ns() >= decision_cutoff_wall_ns:
                self.records[token_mint] = {
                    "version": VERSION,
                    "token_mint": token_mint,
                    "bonding_curve": bonding_curve,
                    "status": "LATE_BEFORE_NATIVE_SNAPSHOT",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                    "retry_count": 0,
                }
                return

            record = await asyncio.to_thread(
                _collect_native_holder_evidence_sync,
                token_mint=token_mint,
                bonding_curve=bonding_curve,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                api_key=self.helius_api_key,
            )
            graduation_ns = self.graduation_wall_ns_by_token.get(token_mint)
            request_before = record.get("snapshot_request_before_wall_ns")
            if (
                record.get("status") == "CAUSAL_AVAILABLE"
                and graduation_ns is not None
                and isinstance(request_before, int)
                and graduation_ns <= request_before
            ):
                record["status"] = "GRADUATED_BEFORE_SNAPSHOT"
                record["feature_value"] = None
                record["graduation_observed_wall_ns"] = graduation_ns
            self.records[token_mint] = record
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.records[token_mint] = {
                "version": VERSION,
                "token_mint": token_mint,
                "bonding_curve": bonding_curve,
                "status": "INTERNAL_ERROR",
                "feature_id": FEATURE_ID,
                "feature_value": None,
                "error": f"{type(exc).__name__}:{exc}"[:700],
                "private_key_used": False,
                "capital_used": False,
                "selector_changed": False,
                "retry_count": 0,
            }

    async def finalize(self) -> None:
        pending = [task for task in self.tasks.values() if not task.done()]
        if pending:
            now_ns = time.time_ns()
            latest_cutoff = max(
                self.decision_cutoff_wall_ns_by_token.get(token, now_ns)
                for token, task in self.tasks.items()
                if not task.done()
            )
            remaining = max(0.0, (latest_cutoff - now_ns) / 1_000_000_000.0)
            if remaining > 0:
                await asyncio.wait(pending, timeout=remaining)

        still_pending = [task for task in self.tasks.values() if not task.done()]
        for task in still_pending:
            task.cancel()
        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)

        for token, task in self.tasks.items():
            if token not in self.records and task.cancelled():
                self.records[token] = {
                    "version": VERSION,
                    "token_mint": token,
                    "status": "TASK_CANCELLED_AFTER_CAPTURE",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                    "retry_count": 0,
                }

    def start(
        self,
        *,
        token_mint: str,
        bonding_curve: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
    ) -> None:
        if token_mint in self.tasks or token_mint in self.records:
            return
        if not bonding_curve:
            self.records[token_mint] = {
                "version": VERSION,
                "token_mint": token_mint,
                "status": "BONDING_CURVE_MISSING",
                "feature_id": FEATURE_ID,
                "feature_value": None,
                "private_key_used": False,
                "capital_used": False,
                "selector_changed": False,
                "retry_count": 0,
            }
            return
        self.decision_cutoff_wall_ns_by_token[token_mint] = int(decision_cutoff_wall_ns)
        loop = asyncio.get_running_loop()
        self.tasks[token_mint] = loop.create_task(
            self._acquire(
                token_mint=token_mint,
                bonding_curve=bonding_curve,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
            )
        )

    def enrich_snapshot(self, token_mint: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        record = self.records.get(token_mint)
        graduation_ns = self.graduation_wall_ns_by_token.get(token_mint)
        if isinstance(record, dict) and record.get("status") == "CAUSAL_AVAILABLE":
            request_before = record.get("snapshot_request_before_wall_ns")
            if (
                graduation_ns is not None
                and isinstance(request_before, int)
                and graduation_ns <= request_before
            ):
                record["status"] = "GRADUATED_BEFORE_SNAPSHOT"
                record["feature_value"] = None
                record["graduation_observed_wall_ns"] = graduation_ns

        enriched = dict(snapshot)
        features = dict(enriched.get("features") or {})
        task = self.tasks.get(token_mint)
        evidence = _compact_evidence(record, pending=bool(task is not None and not task.done()))
        feature_value = (
            record.get("feature_value")
            if isinstance(record, dict) and record.get("status") == "CAUSAL_AVAILABLE"
            else None
        )
        features[FEATURE_ID] = feature_value
        enriched["features"] = features
        external = dict(enriched.get("external_evidence") or {})
        external[EXTERNAL_EVIDENCE_KEY] = evidence
        enriched["external_evidence"] = external
        return enriched

    def artifact_payload(self) -> dict[str, Any]:
        all_tokens = sorted(set(self.records) | set(self.tasks))
        rows: list[dict[str, Any]] = []
        for token in all_tokens:
            task = self.tasks.get(token)
            record = self.records.get(token)
            rows.append(
                record
                or {
                    "version": VERSION,
                    "token_mint": token,
                    "status": (
                        "TASK_CANCELLED_AFTER_CAPTURE"
                        if task is not None and task.cancelled()
                        else "TASK_UNRESOLVED_AFTER_CAPTURE"
                    ),
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                    "retry_count": 0,
                }
            )
        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "type": "holder_ownership_native_evidence_v1",
            "version": VERSION,
            "feature_id": FEATURE_ID,
            "record_count": len(rows),
            "status_counts": status_counts,
            "records": rows,
            "guardrails": {
                "helius_api_key_only": True,
                "gmgn_dependency": False,
                "private_key_used": False,
                "capital_used": False,
                "retry_rescue": False,
                "selector_changed": False,
                "hot_path_blocked_for_external_evidence": False,
                "late_evidence_backfilled": False,
                "snapshot_request_not_before_seconds_from_t0": SNAPSHOT_REQUEST_NOT_BEFORE_SECONDS,
                "decision_cutoff_seconds_from_t0": DECISION_CUTOFF_SECONDS,
                "bonding_curve_excluded": True,
                "graduated_before_snapshot_is_missing": True,
                "tradeable_float_rebase_used": False,
                "page_limit": PAGE_LIMIT,
                "max_pages": MAX_PAGES,
            },
        }

    def write_artifact(self, path: Path) -> None:
        payload = self.artifact_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(path)


@contextmanager
def patched_holder_ownership_native_v1(
    *,
    helius_api_key: str,
) -> Iterator[HolderOwnershipNativeRuntimeV1]:
    runtime = HolderOwnershipNativeRuntimeV1(helius_api_key=helius_api_key)
    original_state = live_v3.OnlinePumpFeatureState
    original_run_live = live_v3.run_live

    class OnlinePumpFeatureStateWithNativeHolderV1(original_state):
        def ingest_processed_chunk(self, chunk_dir: Path) -> None:
            before = set(self.anchors)
            super().ingest_processed_chunk(chunk_dir)

            carbon = chunk_dir / "carbon-canonical.jsonl"
            manifest = chunk_dir / "target-manifest.jsonl"
            create_by_mint: dict[str, str] = {}
            if carbon.exists():
                ordered, errors = paper_v2._paired_rows(carbon, manifest)
                if errors:
                    raise RuntimeError("native holder chunk pairing errors: " + ";".join(errors[:5]))
                for row, manifest_row in ordered:
                    if row.get("status") != "decoded":
                        continue
                    event_type = str(row.get("event_type") or "")
                    observed_wall_ns = int(manifest_row["first_received_wall_ns"])
                    if event_type == "pump_create":
                        mint = str(row.get("mint") or "").strip()
                        curve = str(row.get("bonding_curve") or "").strip()
                        if mint and curve:
                            create_by_mint[mint] = curve
                    elif event_type == "pumpswap_create_pool":
                        base_mint = str(row.get("base_mint") or "").strip()
                        if base_mint:
                            runtime.mark_graduation(
                                token_mint=base_mint,
                                observed_wall_ns=observed_wall_ns,
                            )

            for key in sorted(set(self.anchors) - before):
                token_mint = str(key[0])
                anchor = self.anchors[key]
                runtime.start(
                    token_mint=token_mint,
                    bonding_curve=create_by_mint.get(token_mint, ""),
                    observed_t0_wall_ns=int(anchor["observed_wall_ns"]),
                    decision_cutoff_wall_ns=int(anchor["observed_wall_ns"]) + 5_000_000_000,
                )

        def ready_snapshots(self, *, coverage_through_wall_ns: int) -> list[tuple[str, dict[str, Any]]]:
            ready = super().ready_snapshots(coverage_through_wall_ns=coverage_through_wall_ns)
            return [
                (token_mint, runtime.enrich_snapshot(token_mint, snapshot))
                for token_mint, snapshot in ready
            ]

        def right_censored_snapshots(self) -> list[tuple[str, dict[str, Any]]]:
            rows = super().right_censored_snapshots()
            return [
                (token_mint, runtime.enrich_snapshot(token_mint, snapshot))
                for token_mint, snapshot in rows
            ]

    async def run_live_with_native_holder_finalize(*args, **kwargs):
        try:
            return await original_run_live(*args, **kwargs)
        finally:
            await runtime.finalize()

    live_v3.OnlinePumpFeatureState = OnlinePumpFeatureStateWithNativeHolderV1
    live_v3.run_live = run_live_with_native_holder_finalize
    try:
        yield runtime
    finally:
        live_v3.OnlinePumpFeatureState = original_state
        live_v3.run_live = original_run_live
