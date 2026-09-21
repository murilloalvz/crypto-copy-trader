from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Iterator, Mapping

from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3


VERSION = "holder_ownership_structure_runtime_v0"
FEATURE_ID = "mf_holder_top100_regular_wallet_supply_hhi"
EXTERNAL_EVIDENCE_KEY = "holder_ownership_structure_v0"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 4.5
MAX_CONCURRENT_ACQUISITIONS = 1


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "<redacted>") if secret else value


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cli_environment(api_key: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("GMGN_API_KEY is required for Holder Ownership Structure acquisition")
    env = dict(base_env if base_env is not None else os.environ)
    env["GMGN_API_KEY"] = api_key.strip()
    env.pop("GMGN_PRIVATE_KEY", None)
    return env


def _resolve_gmgn_cli() -> str:
    for candidate in ("gmgn-cli.cmd", "gmgn-cli"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("gmgn-cli is not available on PATH")


def _run_cli_command(
    *,
    args: list[str],
    api_key: str,
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    cli = _resolve_gmgn_cli()
    env = _cli_environment(api_key)
    request_before_wall_ns = time.time_ns()
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            [cli, *args],
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
        exit_code = int(completed.returncode)
        stdout = _redact((completed.stdout or b"").decode("utf-8", errors="replace"), api_key)
        stderr = _redact((completed.stderr or b"").decode("utf-8", errors="replace"), api_key)
        error = None
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        raw_stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        raw_stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        stdout = _redact(raw_stdout, api_key)
        stderr = _redact(raw_stderr, api_key)
        error = "TIMEOUT"

    response_after_wall_ns = time.time_ns()
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    payload = None
    if exit_code == 0:
        try:
            payload = json.loads(stdout.strip())
        except json.JSONDecodeError:
            error = "INVALID_JSON"
            exit_code = -2

    return {
        "args": list(args),
        "request_before_wall_ns": request_before_wall_ns,
        "response_after_wall_ns": response_after_wall_ns,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "error": error,
        "rate_limited": "RATE_LIMIT_" in stderr or "HTTP 429" in stderr,
        "stdout_sha256": _sha256_text(stdout),
        "raw_stdout": stdout,
        "raw_stderr": stderr,
        "payload": payload,
        "private_key_used": False,
        "capital_used": False,
        "retry_count": 0,
    }


def _compact_call(call: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(call, Mapping):
        return None
    return {
        "args": list(call.get("args") or []),
        "request_before_wall_ns": call.get("request_before_wall_ns"),
        "response_after_wall_ns": call.get("response_after_wall_ns"),
        "duration_ms": call.get("duration_ms"),
        "exit_code": call.get("exit_code"),
        "error": call.get("error"),
        "rate_limited": call.get("rate_limited") is True,
        "stdout_sha256": call.get("stdout_sha256"),
        "private_key_used": False,
        "capital_used": False,
        "retry_count": int(call.get("retry_count") or 0),
    }


def _holder_rows(payload: Any) -> list[Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        return None
    rows = payload.get("list")
    return rows if isinstance(rows, list) else None


def _collect_holder_evidence_sync(
    *,
    token_mint: str,
    observed_t0_wall_ns: int,
    decision_cutoff_wall_ns: int,
    api_key: str,
    command_runner: Callable[..., dict[str, Any]] = _run_cli_command,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": VERSION,
        "token_mint": token_mint,
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
    }

    remaining_seconds = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
    if remaining_seconds <= 0:
        base["status"] = "LATE_BEFORE_HOLDERS"
        return base

    holders = command_runner(
        args=[
            "token",
            "holders",
            "--chain",
            "sol",
            "--address",
            token_mint,
            "--limit",
            "100",
            "--order-by",
            "amount_percentage",
            "--direction",
            "desc",
            "--raw",
        ],
        api_key=api_key,
        timeout_seconds=min(DEFAULT_COMMAND_TIMEOUT_SECONDS, remaining_seconds),
    )
    base["holders"] = holders
    if int(holders.get("exit_code") or 0) != 0:
        base["status"] = "RATE_LIMITED_HOLDERS" if holders.get("rate_limited") is True else "HOLDERS_ERROR"
        return base

    rows = _holder_rows(holders.get("payload"))
    if rows is None:
        base["status"] = "HOLDERS_INVALID_PAYLOAD"
        return base
    if not rows:
        base["status"] = "HOLDERS_EMPTY"
        return base

    regular_shares: list[float] = []
    type_counts = {"regular": 0, "burn_dead": 0, "dex_pool": 0}
    for row in rows:
        if not isinstance(row, dict):
            base["status"] = "HOLDER_ROW_INVALID"
            return base
        addr_type = _int_or_none(row.get("addr_type"))
        if addr_type not in (0, 1, 2):
            base["status"] = "AMBIGUOUS_ADDR_TYPE"
            return base
        if addr_type == 0:
            share = _float_or_none(row.get("amount_percentage"))
            if share is None or share < 0.0 or share > 1.0:
                base["status"] = "REGULAR_WALLET_SHARE_INVALID"
                return base
            regular_shares.append(share)
            type_counts["regular"] += 1
        elif addr_type == 1:
            type_counts["burn_dead"] += 1
        else:
            type_counts["dex_pool"] += 1

    if not regular_shares:
        base["status"] = "NO_REGULAR_WALLETS"
        return base

    feature_value = sum(share * share for share in regular_shares)
    base.update(
        {
            "returned_holder_row_count": len(rows),
            "regular_wallet_count": type_counts["regular"],
            "burn_dead_count": type_counts["burn_dead"],
            "dex_pool_count": type_counts["dex_pool"],
            "regular_wallet_supply_share_top100": sum(regular_shares),
            "largest_regular_wallet_supply_share": max(regular_shares),
            "denominator": "total_supply",
            "excluded_addr_types": [1, 2],
        }
    )

    if int(holders.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_HOLDERS"
        return base

    base["status"] = "CAUSAL_AVAILABLE"
    base["feature_value"] = feature_value
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
        "returned_holder_row_count",
        "regular_wallet_count",
        "burn_dead_count",
        "dex_pool_count",
        "regular_wallet_supply_share_top100",
        "largest_regular_wallet_supply_share",
        "denominator",
        "excluded_addr_types",
        "private_key_used",
        "capital_used",
        "selector_changed",
        "threshold_search_performed",
        "automatic_entry_rule_created",
    )
    compact = {key: record.get(key) for key in keys if key in record}
    compact["holders"] = _compact_call(record.get("holders"))
    return compact


class HolderOwnershipRuntimeV0:
    def __init__(self, *, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("GMGN_API_KEY is required for Holder Ownership Structure V0")
        self.api_key = api_key.strip()
        self.records: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.decision_cutoff_wall_ns_by_token: dict[str, int] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self.max_concurrent_acquisitions = MAX_CONCURRENT_ACQUISITIONS

    def _terminal_missing_record(
        self,
        *,
        token_mint: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
        status: str,
    ) -> dict[str, Any]:
        return {
            "version": VERSION,
            "token_mint": token_mint,
            "observed_t0_wall_ns": int(observed_t0_wall_ns),
            "decision_cutoff_wall_ns": int(decision_cutoff_wall_ns),
            "status": status,
            "feature_id": FEATURE_ID,
            "feature_value": None,
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
        }

    async def _acquire(
        self,
        *,
        token_mint: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
    ) -> None:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_acquisitions)

        acquired = False
        try:
            remaining_seconds = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
            if remaining_seconds <= 0:
                self.records[token_mint] = self._terminal_missing_record(
                    token_mint=token_mint,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="LATE_BEFORE_SLOT",
                )
                return
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=remaining_seconds)
                acquired = True
            except TimeoutError:
                self.records[token_mint] = self._terminal_missing_record(
                    token_mint=token_mint,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="LATE_WAITING_FOR_SLOT",
                )
                return

            if time.time_ns() > decision_cutoff_wall_ns:
                self.records[token_mint] = self._terminal_missing_record(
                    token_mint=token_mint,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="LATE_BEFORE_HOLDERS",
                )
                return

            self.records[token_mint] = await asyncio.to_thread(
                _collect_holder_evidence_sync,
                token_mint=token_mint,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                api_key=self.api_key,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.records[token_mint] = {
                **self._terminal_missing_record(
                    token_mint=token_mint,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                    status="INTERNAL_ERROR",
                ),
                "error": f"{type(exc).__name__}:{_redact(str(exc), self.api_key)}"[:700],
            }
        finally:
            if acquired and self._semaphore is not None:
                self._semaphore.release()

    async def finalize(self) -> None:
        pending_by_token = {token: task for token, task in self.tasks.items() if not task.done()}
        if pending_by_token:
            now_wall_ns = time.time_ns()
            latest_cutoff_wall_ns = max(
                self.decision_cutoff_wall_ns_by_token.get(token, now_wall_ns)
                for token in pending_by_token
            )
            remaining_causal_seconds = max(
                0.0,
                (latest_cutoff_wall_ns - now_wall_ns) / 1_000_000_000.0,
            )
            if remaining_causal_seconds > 0:
                await asyncio.wait(pending_by_token.values(), timeout=remaining_causal_seconds)

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
                }

    def start(
        self,
        *,
        token_mint: str,
        observed_t0_wall_ns: int,
        decision_cutoff_wall_ns: int,
    ) -> None:
        if token_mint in self.tasks or token_mint in self.records:
            return
        self.decision_cutoff_wall_ns_by_token[token_mint] = int(decision_cutoff_wall_ns)
        loop = asyncio.get_running_loop()
        self.tasks[token_mint] = loop.create_task(
            self._acquire(
                token_mint=token_mint,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
            )
        )

    def enrich_snapshot(self, token_mint: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        enriched = dict(snapshot)
        features = dict(enriched.get("features") or {})
        task = self.tasks.get(token_mint)
        record = self.records.get(token_mint)
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
            if record is None and task is not None and task.cancelled():
                record = {
                    "version": VERSION,
                    "token_mint": token,
                    "status": "TASK_CANCELLED_AFTER_CAPTURE",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                }
            rows.append(
                record
                or {
                    "version": VERSION,
                    "token_mint": token,
                    "status": "TASK_UNRESOLVED_AFTER_CAPTURE",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                }
            )

        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "type": "holder_ownership_structure_evidence_v0",
            "version": VERSION,
            "feature_id": FEATURE_ID,
            "record_count": len(rows),
            "status_counts": status_counts,
            "records": rows,
            "guardrails": {
                "gmgn_api_key_only": True,
                "gmgn_private_key_used": False,
                "capital_used": False,
                "retry_spam": False,
                "selector_changed": False,
                "hot_path_blocked_for_external_evidence": False,
                "late_evidence_backfilled": False,
                "max_concurrent_acquisitions": self.max_concurrent_acquisitions,
                "slot_wait_bounded_by_decision_cutoff": True,
                "command_timeout_bounded_by_remaining_cutoff": True,
                "subprocess_output_decoding": "utf8_replace",
                "addr_type_0_regular_only": True,
                "addr_type_1_burn_dead_excluded": True,
                "addr_type_2_dex_pool_excluded": True,
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
def patched_holder_ownership_structure_v0(*, api_key: str) -> Iterator[HolderOwnershipRuntimeV0]:
    runtime = HolderOwnershipRuntimeV0(api_key=api_key)
    original_state = live_v3.OnlinePumpFeatureState
    original_run_live = live_v3.run_live

    class OnlinePumpFeatureStateWithHolderV0(original_state):
        def ingest_processed_chunk(self, chunk_dir: Path) -> None:
            before = set(self.anchors)
            super().ingest_processed_chunk(chunk_dir)
            for key in sorted(set(self.anchors) - before):
                token_mint = str(key[0])
                anchor = self.anchors[key]
                observed_t0_wall_ns = int(anchor["observed_wall_ns"])
                runtime.start(
                    token_mint=token_mint,
                    observed_t0_wall_ns=observed_t0_wall_ns,
                    decision_cutoff_wall_ns=observed_t0_wall_ns + 5_000_000_000,
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

    live_v3.OnlinePumpFeatureState = OnlinePumpFeatureStateWithHolderV0
    live_v3.run_live = run_live_with_holder_finalize
    try:
        yield runtime
    finally:
        live_v3.OnlinePumpFeatureState = original_state
        live_v3.run_live = original_run_live
