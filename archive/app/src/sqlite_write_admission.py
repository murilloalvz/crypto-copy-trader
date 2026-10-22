from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time


RESOLUTION_PRIORITY = "resolution"
CAUSAL_PRIORITY = "causal"
AUDIT_PRIORITY = "audit"


@dataclass(frozen=True)
class SQLiteWriteAdmissionSnapshot:
    resolution_acquisitions: int
    causal_acquisitions: int
    audit_acquisitions: int
    audit_forced_after_starvation: int
    max_resolution_waiters: int
    max_causal_waiters: int
    max_audit_waiters: int
    resolution_wait_seconds: tuple[float, ...]
    causal_wait_seconds: tuple[float, ...]
    audit_wait_seconds: tuple[float, ...]
    resolution_fairness_blocks: int
    max_consecutive_resolution_grants: int
    resolution_max_consecutive_when_causal_waiting: int | None


class PrioritizedSQLiteWriteAdmission:
    """Serialize SQLite writers with explicit priority and optional bounded fairness.

    SQLite/WAL still has one physical writer. Letting independent writer threads race for that lock
    turns queueing into opaque ``busy_timeout`` latency. This gate makes writer ownership explicit:

    * ``resolution`` is reserved for durable pool identity needed before normalization can finish;
    * ordinary causal market persistence / episode-opening work follows;
    * append-only audit work yields to both, but may enter after a bounded starvation interval so a
      long collection cannot grow audit memory without bound;
    * readers never touch this gate and remain concurrent under WAL.

    ``resolution_max_consecutive_when_causal_waiting`` is disabled by default so historical v28/v3
    behavior stays unchanged. A later systems-only profile may set a positive value to prevent an
    unbounded stream of high-priority identity writes from starving the causal observation writer.
    The option changes only admission order: there is still exactly one active SQLite writer and no
    transaction, replay, as-of, detector or FIFO semantics change.
    """

    def __init__(
        self,
        *,
        audit_max_starvation_seconds: float = 0.5,
        resolution_max_consecutive_when_causal_waiting: int | None = None,
    ) -> None:
        if audit_max_starvation_seconds <= 0:
            raise ValueError("audit_max_starvation_seconds must be positive")
        if (
            resolution_max_consecutive_when_causal_waiting is not None
            and resolution_max_consecutive_when_causal_waiting <= 0
        ):
            raise ValueError(
                "resolution_max_consecutive_when_causal_waiting must be positive or None"
            )
        self.audit_max_starvation_seconds = float(audit_max_starvation_seconds)
        self.resolution_max_consecutive_when_causal_waiting = (
            int(resolution_max_consecutive_when_causal_waiting)
            if resolution_max_consecutive_when_causal_waiting is not None
            else None
        )
        self._condition = threading.Condition()
        self._active = False
        self._resolution_waiters = 0
        self._causal_waiters = 0
        self._audit_waiters = 0
        self._resolution_acquisitions = 0
        self._causal_acquisitions = 0
        self._audit_acquisitions = 0
        self._audit_forced_after_starvation = 0
        self._max_resolution_waiters = 0
        self._max_causal_waiters = 0
        self._max_audit_waiters = 0
        self._resolution_wait_seconds: deque[float] = deque(maxlen=100_000)
        self._causal_wait_seconds: deque[float] = deque(maxlen=100_000)
        self._audit_wait_seconds: deque[float] = deque(maxlen=100_000)
        self._consecutive_resolution_grants = 0
        self._max_consecutive_resolution_grants = 0
        self._resolution_fairness_blocks = 0

    def _resolution_must_yield_to_causal(self) -> bool:
        limit = self.resolution_max_consecutive_when_causal_waiting
        return (
            limit is not None
            and self._causal_waiters > 0
            and self._consecutive_resolution_grants >= limit
        )

    @contextmanager
    def acquire(self, priority: str):
        normalized = str(priority).strip().lower()
        if normalized not in {RESOLUTION_PRIORITY, CAUSAL_PRIORITY, AUDIT_PRIORITY}:
            raise ValueError("unsupported sqlite write priority")

        started = time.perf_counter()
        forced_after_starvation = False
        fairness_block_recorded = False
        with self._condition:
            if normalized == RESOLUTION_PRIORITY:
                self._resolution_waiters += 1
                self._max_resolution_waiters = max(
                    self._max_resolution_waiters,
                    self._resolution_waiters,
                )
                try:
                    while self._active or self._resolution_must_yield_to_causal():
                        if (
                            not self._active
                            and self._resolution_must_yield_to_causal()
                            and not fairness_block_recorded
                        ):
                            self._resolution_fairness_blocks += 1
                            fairness_block_recorded = True
                        self._condition.wait()
                    self._active = True
                    # If no causal writer was waiting when this grant became available, old
                    # resolution-only traffic must not accumulate a stale fairness debt.
                    if self._causal_waiters == 0:
                        self._consecutive_resolution_grants = 0
                    self._consecutive_resolution_grants += 1
                    self._max_consecutive_resolution_grants = max(
                        self._max_consecutive_resolution_grants,
                        self._consecutive_resolution_grants,
                    )
                finally:
                    self._resolution_waiters -= 1
            elif normalized == CAUSAL_PRIORITY:
                self._causal_waiters += 1
                self._max_causal_waiters = max(
                    self._max_causal_waiters,
                    self._causal_waiters,
                )
                try:
                    while True:
                        resolution_has_priority = (
                            self._resolution_waiters > 0
                            and not self._resolution_must_yield_to_causal()
                        )
                        if not self._active and not resolution_has_priority:
                            self._active = True
                            self._consecutive_resolution_grants = 0
                            break
                        self._condition.wait()
                finally:
                    self._causal_waiters -= 1
            else:
                self._audit_waiters += 1
                self._max_audit_waiters = max(
                    self._max_audit_waiters,
                    self._audit_waiters,
                )
                try:
                    while True:
                        waited = time.perf_counter() - started
                        starved = waited >= self.audit_max_starvation_seconds
                        higher_priority_waiting = (
                            self._resolution_waiters > 0 or self._causal_waiters > 0
                        )
                        if not self._active and (not higher_priority_waiting or starved):
                            forced_after_starvation = starved and higher_priority_waiting
                            self._active = True
                            break
                        timeout = None
                        if higher_priority_waiting and not starved:
                            timeout = max(
                                0.001,
                                self.audit_max_starvation_seconds - waited,
                            )
                        self._condition.wait(timeout=timeout)
                finally:
                    self._audit_waiters -= 1

            wait_seconds = max(0.0, time.perf_counter() - started)
            if normalized == RESOLUTION_PRIORITY:
                self._resolution_acquisitions += 1
                self._resolution_wait_seconds.append(wait_seconds)
            elif normalized == CAUSAL_PRIORITY:
                self._causal_acquisitions += 1
                self._causal_wait_seconds.append(wait_seconds)
            else:
                self._audit_acquisitions += 1
                self._audit_wait_seconds.append(wait_seconds)
                if forced_after_starvation:
                    self._audit_forced_after_starvation += 1

        try:
            yield
        finally:
            with self._condition:
                if not self._active:
                    raise RuntimeError("sqlite write admission released while inactive")
                self._active = False
                self._condition.notify_all()

    def reset_metrics(self) -> None:
        with self._condition:
            if (
                self._active
                or self._resolution_waiters
                or self._causal_waiters
                or self._audit_waiters
            ):
                raise RuntimeError("cannot reset sqlite write admission while work is active")
            self._resolution_acquisitions = 0
            self._causal_acquisitions = 0
            self._audit_acquisitions = 0
            self._audit_forced_after_starvation = 0
            self._max_resolution_waiters = 0
            self._max_causal_waiters = 0
            self._max_audit_waiters = 0
            self._resolution_wait_seconds.clear()
            self._causal_wait_seconds.clear()
            self._audit_wait_seconds.clear()
            self._consecutive_resolution_grants = 0
            self._max_consecutive_resolution_grants = 0
            self._resolution_fairness_blocks = 0

    def is_idle(self) -> bool:
        with self._condition:
            return not (
                self._active
                or self._resolution_waiters
                or self._causal_waiters
                or self._audit_waiters
            )

    def snapshot(self) -> SQLiteWriteAdmissionSnapshot:
        with self._condition:
            return SQLiteWriteAdmissionSnapshot(
                resolution_acquisitions=self._resolution_acquisitions,
                causal_acquisitions=self._causal_acquisitions,
                audit_acquisitions=self._audit_acquisitions,
                audit_forced_after_starvation=self._audit_forced_after_starvation,
                max_resolution_waiters=self._max_resolution_waiters,
                max_causal_waiters=self._max_causal_waiters,
                max_audit_waiters=self._max_audit_waiters,
                resolution_wait_seconds=tuple(self._resolution_wait_seconds),
                causal_wait_seconds=tuple(self._causal_wait_seconds),
                audit_wait_seconds=tuple(self._audit_wait_seconds),
                resolution_fairness_blocks=self._resolution_fairness_blocks,
                max_consecutive_resolution_grants=self._max_consecutive_resolution_grants,
                resolution_max_consecutive_when_causal_waiting=(
                    self.resolution_max_consecutive_when_causal_waiting
                ),
            )


_GLOBAL_WRITE_ADMISSION = PrioritizedSQLiteWriteAdmission()


def sqlite_write_admission(priority: str):
    return _GLOBAL_WRITE_ADMISSION.acquire(priority)


def reset_sqlite_write_admission_metrics() -> None:
    _GLOBAL_WRITE_ADMISSION.reset_metrics()


def sqlite_write_admission_snapshot() -> SQLiteWriteAdmissionSnapshot:
    return _GLOBAL_WRITE_ADMISSION.snapshot()
