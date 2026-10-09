from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import math
from pathlib import Path
import time
from typing import Any, Iterator, Mapping

from benchmarks.holder_ownership_rpc_v2.rpc_endpoint import rpc_once
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3
from benchmarks.launch_burst_prospective_route_paper_v2 import live as paper_v2


VERSION = "holder_ownership_rpc_runtime_v2"
FEATURE_ID = "mf_holder_pump_pregrad_top20_non_curve_owner_supply_hhi_rpc"
EXTERNAL_EVIDENCE_KEY = "holder_ownership_rpc_v2"
SNAPSHOT_REQUEST_NOT_BEFORE_SECONDS = 3.0
DECISION_CUTOFF_SECONDS = 5.0
SNAPSHOT_START_MIN_INTERVAL_SECONDS = 0.5
MAX_CONCURRENT_SNAPSHOTS = 4


def _int_amount(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


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
        "retry_after_present": bool(call.get("retry_after")),
    }


def _collect_rpc_holder_evidence_sync(
    *,
    rpc_url: str,
    token_mint: str,
    bonding_curve: str,
    observed_t0_wall_ns: int,
    decision_cutoff_wall_ns: int,
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
        "retry_count": 0,
    }

    def remaining() -> float:
        return (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0

    if remaining() <= 0:
        base["status"] = "LATE_BEFORE_RPC_SNAPSHOT"
        return base

    supply_call = rpc_once(
        rpc_url=rpc_url,
        method="getTokenSupply",
        params=[token_mint, {"commitment": "processed"}],
        timeout_seconds=min(1.25, max(0.05, remaining())),
    )
    base["token_supply_call"] = supply_call
    if supply_call.get("rate_limited") is True:
        base["status"] = "RPC_RATE_LIMITED"
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

    largest_call = rpc_once(
        rpc_url=rpc_url,
        method="getTokenLargestAccounts",
        params=[token_mint, {"commitment": "processed"}],
        timeout_seconds=min(1.25, max(0.05, remaining())),
    )
    base["largest_accounts_call"] = largest_call
    if largest_call.get("rate_limited") is True:
        base["status"] = "RPC_RATE_LIMITED"
        return base
    if largest_call.get("error") is not None:
        base["status"] = "LARGEST_ACCOUNTS_ERROR"
        return base
    if int(largest_call.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_LARGEST_ACCOUNTS"
        return base
    largest_result = largest_call.get("result")
    largest_rows = largest_result.get("value") if isinstance(largest_result, dict) else None
    if not isinstance(largest_rows, list) or not largest_rows:
        base["status"] = "LARGEST_ACCOUNTS_EMPTY"
        return base

    token_accounts: list[str] = []
    raw_amount_by_account: dict[str, int] = {}
    for row in largest_rows:
        if not isinstance(row, dict):
            base["status"] = "LARGEST_ACCOUNT_ROW_INVALID"
            return base
        address = str(row.get("address") or "").strip()
        amount = _int_amount(row.get("amount"))
        if not address or amount is None:
            base["status"] = "LARGEST_ACCOUNT_ROW_INVALID"
            return base
        token_accounts.append(address)
        raw_amount_by_account[address] = amount

    multiple_call = rpc_once(
        rpc_url=rpc_url,
        method="getMultipleAccounts",
        params=[
            token_accounts,
            {"encoding": "jsonParsed", "commitment": "processed"},
        ],
        timeout_seconds=min(1.25, max(0.05, remaining())),
    )
    base["multiple_accounts_call"] = multiple_call
    if multiple_call.get("rate_limited") is True:
        base["status"] = "RPC_RATE_LIMITED"
        return base
    if multiple_call.get("error") is not None:
        base["status"] = "MULTIPLE_ACCOUNTS_ERROR"
        return base
    if int(multiple_call.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_MULTIPLE_ACCOUNTS"
        return base

    multi_result = multiple_call.get("result")
    account_rows = multi_result.get("value") if isinstance(multi_result, dict) else None
    if not isinstance(account_rows, list) or len(account_rows) != len(token_accounts):
        base["status"] = "MULTIPLE_ACCOUNTS_INVALID_PAYLOAD"
        return base

    owner_amounts: dict[str, int] = {}
    resolved_accounts = 0
    for token_account, account_row in zip(token_accounts, account_rows):
        if not isinstance(account_row, dict):
            base["status"] = "TOKEN_ACCOUNT_INFO_MISSING"
            return base
        data = account_row.get("data")
        parsed = data.get("parsed") if isinstance(data, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        owner = str((info or {}).get("owner") or "").strip() if isinstance(info, dict) else ""
        if not owner:
            base["status"] = "TOKEN_ACCOUNT_OWNER_UNRESOLVED"
            return base
        amount = raw_amount_by_account[token_account]
        owner_amounts[owner] = owner_amounts.get(owner, 0) + amount
        resolved_accounts += 1

    non_curve_owner_amounts = {
        owner: amount
        for owner, amount in owner_amounts.items()
        if owner != bonding_curve and amount > 0
    }
    if not non_curve_owner_amounts:
        base["status"] = "NO_NON_CURVE_TOP20_OWNERS"
        return base

    feature_value = sum(
        (float(amount) / float(total_supply_raw)) ** 2
        for amount in non_curve_owner_amounts.values()
    )
    if not math.isfinite(feature_value) or feature_value < 0.0 or feature_value > 1.0000000001:
        base["status"] = "FEATURE_DERIVATION_INVALID"
        return base

    calls = [supply_call, largest_call, multiple_call]
    base.update(
        {
            "status": "CAUSAL_AVAILABLE",
            "feature_value": feature_value,
            "total_supply_raw": total_supply_raw,
            "top_token_account_count": len(token_accounts),
            "resolved_token_account_count": resolved_accounts,
            "top20_unique_owner_count": len(owner_amounts),
            "top20_non_curve_owner_count": len(non_curve_owner_amounts),
            "bonding_curve_top20_amount_raw": int(owner_amounts.get(bonding_curve, 0)),
            "owner_amounts_raw": owner_amounts,
            "denominator": "total_supply_raw",
            "coverage_scope": "top20_token_accounts",
            "excluded_market_owner": bonding_curve,
            "snapshot_request_before_wall_ns": min(int(call["request_before_wall_ns"]) for call in calls),
            "snapshot_response_after_wall_ns": max(int(call["response_after_wall_ns"]) for call in calls),
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
        "top_token_account_count",
        "resolved_token_account_count",
        "top20_unique_owner_count",
        "top20_non_curve_owner_count",
        "bonding_curve_top20_amount_raw",
        "denominator",
        "coverage_scope",
        "excluded_market_owner",
        "snapshot_request_before_wall_ns",
        "snapshot_response_after_wall_ns",
        "graduation_observed_wall_ns",
        "private_key_used",
        "capital_used",
        "selector_changed",
        "retry_count",
    )
    compact = {key: record.get(key) for key in keys if key in record}
    compact["token_supply_call"] = _compact_call(record.get("token_supply_call"))
    compact["largest_accounts_call"] = _compact_call(record.get("largest_accounts_call"))
    compact["multiple_accounts_call"] = _compact_call(record.get("multiple_accounts_call"))
    return compact


class HolderOwnershipRpcRuntimeV2:
    def __init__(self, *, rpc_url: str, rpc_safe_host: str) -> None:
        self.rpc_url = rpc_url
        self.rpc_safe_host = rpc_safe_host
        self.records: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.decision_cutoff_wall_ns_by_token: dict[str, int] = {}
        self.graduation_wall_ns_by_token: dict[str, int] = {}
        self._start_lock = asyncio.Lock()
        self._last_snapshot_start_monotonic: float | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SNAPSHOTS)

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

    def _missing(
        self,
        *,
        token_mint: str,
        bonding_curve: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
        status: str,
    ) -> dict[str, Any]:
        return {
            "version": VERSION,
            "token_mint": token_mint,
            "bonding_curve": bonding_curve,
            "observed_t0_wall_ns": observed_t0_wall_ns,
            "decision_cutoff_wall_ns": decision_cutoff_wall_ns,
            "status": status,
            "feature_id": FEATURE_ID,
            "feature_value": None,
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
            "retry_count": 0,
        }

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
                self.records[token_mint] = self._missing(
                    token_mint=token_mint,
                    bonding_curve=bonding_curve,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="GRADUATED_BEFORE_SNAPSHOT",
                )
                self.records[token_mint]["graduation_observed_wall_ns"] = graduation_ns
                return

            async with self._start_lock:
                now_mono = time.monotonic()
                pacing_wait = 0.0
                if self._last_snapshot_start_monotonic is not None:
                    pacing_wait = max(
                        0.0,
                        self._last_snapshot_start_monotonic
                        + SNAPSHOT_START_MIN_INTERVAL_SECONDS
                        - now_mono,
                    )
                remaining = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
                if remaining <= pacing_wait:
                    self.records[token_mint] = self._missing(
                        token_mint=token_mint,
                        bonding_curve=bonding_curve,
                        observed_t0_wall_ns=observed_t0_wall_ns,
                        decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                        status="LATE_WAITING_FOR_RPC_RATE_SLOT",
                    )
                    return
                if pacing_wait > 0:
                    await asyncio.sleep(pacing_wait)
                self._last_snapshot_start_monotonic = time.monotonic()

            remaining = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
            if remaining <= 0:
                self.records[token_mint] = self._missing(
                    token_mint=token_mint,
                    bonding_curve=bonding_curve,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="LATE_BEFORE_RPC_SNAPSHOT",
                )
                return

            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=remaining)
            except TimeoutError:
                self.records[token_mint] = self._missing(
                    token_mint=token_mint,
                    bonding_curve=bonding_curve,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="LATE_WAITING_FOR_RPC_CONCURRENCY_SLOT",
                )
                return

            try:
                record = await asyncio.to_thread(
                    _collect_rpc_holder_evidence_sync,
                    rpc_url=self.rpc_url,
                    token_mint=token_mint,
                    bonding_curve=bonding_curve,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                )
            finally:
                self._semaphore.release()

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
            self.records[token_mint] = self._missing(
                token_mint=token_mint,
                bonding_curve=bonding_curve,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                status="INTERNAL_ERROR",
            )
            self.records[token_mint]["error"] = f"{type(exc).__name__}:{exc}"[:700]

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
            self.records[token_mint] = self._missing(
                token_mint=token_mint,
                bonding_curve=bonding_curve,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                status="BONDING_CURVE_MISSING",
            )
            return
        self.decision_cutoff_wall_ns_by_token[token_mint] = int(decision_cutoff_wall_ns)
        self.tasks[token_mint] = asyncio.get_running_loop().create_task(
            self._acquire(
                token_mint=token_mint,
                bonding_curve=bonding_curve,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
            )
        )

    def enrich_snapshot(self, token_mint: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        record = self.records.get(token_mint)
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
        rows = []
        for token in all_tokens:
            task = self.tasks.get(token)
            rows.append(
                self.records.get(token)
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
            "type": "holder_ownership_rpc_evidence_v2",
            "version": VERSION,
            "feature_id": FEATURE_ID,
            "rpc_safe_host": self.rpc_safe_host,
            "record_count": len(rows),
            "status_counts": status_counts,
            "records": rows,
            "guardrails": {
                "helius_holder_dependency": False,
                "gmgn_holder_dependency": False,
                "private_key_used": False,
                "capital_used": False,
                "retry_rescue": False,
                "provider_switch_after_capture_start": False,
                "selector_changed": False,
                "late_evidence_backfilled": False,
                "snapshot_request_not_before_seconds_from_t0": SNAPSHOT_REQUEST_NOT_BEFORE_SECONDS,
                "decision_cutoff_seconds_from_t0": DECISION_CUTOFF_SECONDS,
                "snapshot_start_min_interval_seconds": SNAPSHOT_START_MIN_INTERVAL_SECONDS,
                "top20_scope_explicit": True,
                "bonding_curve_excluded": True,
                "graduated_before_snapshot_is_missing": True,
                "tradeable_float_rebase_used": False,
            },
        }

    def write_artifact(self, path: Path) -> None:
        payload = self.artifact_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(path)


@contextmanager
def patched_holder_ownership_rpc_v2(
    *,
    rpc_url: str,
    rpc_safe_host: str,
) -> Iterator[HolderOwnershipRpcRuntimeV2]:
    runtime = HolderOwnershipRpcRuntimeV2(rpc_url=rpc_url, rpc_safe_host=rpc_safe_host)
    original_state = live_v3.OnlinePumpFeatureState
    original_run_live = live_v3.run_live

    class OnlinePumpFeatureStateWithHolderRpcV2(original_state):
        def ingest_processed_chunk(self, chunk_dir: Path) -> None:
            before = set(self.anchors)
            super().ingest_processed_chunk(chunk_dir)

            carbon = chunk_dir / "carbon-canonical.jsonl"
            manifest = chunk_dir / "target-manifest.jsonl"
            create_by_mint: dict[str, str] = {}
            if carbon.exists():
                ordered, errors = paper_v2._paired_rows(carbon, manifest)
                if errors:
                    raise RuntimeError("holder RPC v2 chunk pairing errors: " + ";".join(errors[:5]))
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

    async def run_live_with_holder_finalize(*args, **kwargs):
        try:
            return await original_run_live(*args, **kwargs)
        finally:
            await runtime.finalize()

    live_v3.OnlinePumpFeatureState = OnlinePumpFeatureStateWithHolderRpcV2
    live_v3.run_live = run_live_with_holder_finalize
    try:
        yield runtime
    finally:
        live_v3.OnlinePumpFeatureState = original_state
        live_v3.run_live = original_run_live
