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


VERSION = "deployer_prior_quality_runtime_v0"
FEATURE_ID = "mf_deployer_created_count_snapshot_ex_current"
EXTERNAL_EVIDENCE_KEY = "deployer_prior_quality_v0"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 4.5
MAX_CONCURRENT_ACQUISITIONS = 2


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "<redacted>") if secret else value


def _unwrap_data(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _cli_environment(api_key: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("GMGN_API_KEY is required for Deployer Prior Quality acquisition")
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
        raw_stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        raw_stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
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


def _prior_best_ath_from_rows(rows: list[Any], current_token: str) -> float | None:
    values: list[float] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("token_address") or "") == current_token:
            continue
        value = _float_or_none(item.get("token_ath_mc"))
        if value is not None:
            values.append(value)
    return max(values) if values else None


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


def _collect_deployer_evidence_sync(
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

    if time.time_ns() > decision_cutoff_wall_ns:
        base["status"] = "LATE_BEFORE_TOKEN_INFO"
        return base

    remaining_seconds = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
    if remaining_seconds <= 0:
        base["status"] = "LATE_BEFORE_TOKEN_INFO"
        return base

    token_info = command_runner(
        args=["token", "info", "--chain", "sol", "--address", token_mint, "--raw"],
        api_key=api_key,
        timeout_seconds=min(DEFAULT_COMMAND_TIMEOUT_SECONDS, remaining_seconds),
    )
    base["token_info"] = token_info
    if int(token_info.get("exit_code") or 0) != 0:
        base["status"] = (
            "RATE_LIMITED_TOKEN_INFO"
            if token_info.get("rate_limited") is True
            else "TOKEN_INFO_ERROR"
        )
        return base
    if int(token_info.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_TOKEN_INFO"
        return base

    info_payload = _unwrap_data(token_info.get("payload"))
    dev = info_payload.get("dev") if isinstance(info_payload, dict) else None
    creator = str((dev or {}).get("creator_address") or "").strip()
    if not creator:
        base["status"] = "CREATOR_MISSING"
        return base
    base["creator_address"] = creator

    remaining_seconds = (decision_cutoff_wall_ns - time.time_ns()) / 1_000_000_000.0
    if remaining_seconds <= 0:
        base["status"] = "LATE_BEFORE_CREATED_TOKENS"
        return base

    created = command_runner(
        args=[
            "portfolio",
            "created-tokens",
            "--chain",
            "sol",
            "--wallet",
            creator,
            "--order-by",
            "token_ath_mc",
            "--direction",
            "desc",
            "--raw",
        ],
        api_key=api_key,
        timeout_seconds=min(DEFAULT_COMMAND_TIMEOUT_SECONDS, remaining_seconds),
    )
    base["created_tokens"] = created
    if int(created.get("exit_code") or 0) != 0:
        base["status"] = (
            "RATE_LIMITED_CREATED_TOKENS"
            if created.get("rate_limited") is True
            else "CREATED_TOKENS_ERROR"
        )
        return base

    created_payload = _unwrap_data(created.get("payload"))
    if not isinstance(created_payload, dict):
        base["status"] = "CREATED_TOKENS_INVALID_PAYLOAD"
        return base

    inner_count = _int_or_none(created_payload.get("inner_count"))
    open_count = _int_or_none(created_payload.get("open_count"))
    if inner_count is None or open_count is None:
        base["status"] = "CREATED_COUNTS_MISSING"
        return base

    total_created = inner_count + open_count
    rows = created_payload.get("tokens")
    rows = rows if isinstance(rows, list) else []
    current_token_present = any(
        isinstance(item, dict) and str(item.get("token_address") or "") == token_mint
        for item in rows
    )

    stat = info_payload.get("stat") if isinstance(info_payload, dict) else None
    token_info_created_count = _int_or_none((stat or {}).get("creator_created_count"))
    if token_info_created_count is None and isinstance(dev, dict):
        token_info_created_count = _int_or_none(dev.get("creator_open_count"))

    feature_value = max(total_created - 1, 0)
    base.update(
        {
            "inner_count": inner_count,
            "open_count": open_count,
            "open_ratio": _float_or_none(created_payload.get("open_ratio")),
            "total_created_snapshot": total_created,
            "creator_created_count_from_token_info": token_info_created_count,
            "creator_created_count_crosscheck": (
                token_info_created_count == total_created
                if token_info_created_count is not None
                else None
            ),
            "current_token_present_in_returned_rows": current_token_present,
            "returned_token_row_count": len(rows),
            "returned_list_may_be_truncated": total_created > len(rows),
            "prior_best_ath_mc_returned_rows": _prior_best_ath_from_rows(rows, token_mint),
        }
    )

    if int(created.get("response_after_wall_ns") or 0) > decision_cutoff_wall_ns:
        base["status"] = "LATE_CREATED_TOKENS"
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
        "creator_address",
        "inner_count",
        "open_count",
        "open_ratio",
        "total_created_snapshot",
        "creator_created_count_from_token_info",
        "creator_created_count_crosscheck",
        "current_token_present_in_returned_rows",
        "returned_token_row_count",
        "returned_list_may_be_truncated",
        "prior_best_ath_mc_returned_rows",
        "private_key_used",
        "capital_used",
        "selector_changed",
        "threshold_search_performed",
        "automatic_entry_rule_created",
    )
    compact = {key: record.get(key) for key in keys if key in record}
    compact["token_info"] = _compact_call(record.get("token_info"))
    compact["created_tokens"] = _compact_call(record.get("created_tokens"))
    return compact


class DeployerEvidenceRuntimeV0:
    def __init__(self, *, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("GMGN_API_KEY is required for Deployer Prior Quality V0")
        self.api_key = api_key.strip()
        self.records: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
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
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=remaining_seconds,
                )
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
                    status="LATE_BEFORE_TOKEN_INFO",
                )
                return

            record = await asyncio.to_thread(
                _collect_deployer_evidence_sync,
                token_mint=token_mint,
                observed_t0_wall_ns=observed_t0_wall_ns,
                decision_cutoff_wall_ns=decision_cutoff_wall_ns,
                api_key=self.api_key,
            )
            self.records[token_mint] = record
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
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
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
        rows = []
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
            rows.append(record or {
                "version": VERSION,
                "token_mint": token,
                "status": "TASK_UNRESOLVED_AFTER_CAPTURE",
                "feature_id": FEATURE_ID,
                "feature_value": None,
                "private_key_used": False,
                "capital_used": False,
                "selector_changed": False,
            })
        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "type": "deployer_prior_quality_evidence_v0",
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
            },
        }

    def write_artifact(self, path: Path) -> None:
        payload = self.artifact_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(path)


@contextmanager
def patched_deployer_prior_quality_v0(*, api_key: str) -> Iterator[DeployerEvidenceRuntimeV0]:
    runtime = DeployerEvidenceRuntimeV0(api_key=api_key)
    original_state = live_v3.OnlinePumpFeatureState
    original_run_live = live_v3.run_live

    class OnlinePumpFeatureStateWithDeployerV0(original_state):
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

    async def run_live_with_deployer_finalize(*args, **kwargs):
        try:
            return await original_run_live(*args, **kwargs)
        finally:
            await runtime.finalize()

    live_v3.OnlinePumpFeatureState = OnlinePumpFeatureStateWithDeployerV0
    live_v3.run_live = run_live_with_deployer_finalize
    try:
        yield runtime
    finally:
        live_v3.OnlinePumpFeatureState = original_state
        live_v3.run_live = original_run_live
