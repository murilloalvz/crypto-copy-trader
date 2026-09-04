from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time


CAUSAL_PRIORITY = "causal"
AUDIT_PRIORITY = "audit"


@dataclass(frozen=True)
class SQLiteWriteAdmissionSnapshot:
    causal_acquisitions: int
    audit_acquisitions: int
    audit_forced_after_starvation: int
    max_causal_waiters: int
    max_audit_waiters: int
    causal_wait_seconds: tuple[float, ...]
    audit_wait_seconds: tuple[float, ...]


class PrioritizedSQLiteWriteAdmission:
    """Serialize SQLite writers while giving causal work bounded priority.

    SQLite/WAL still has one physical writer. Letting several independent writer threads race for
    that lock turns queueing into opaque ``busy_timeout`` latency. This gate makes that queueing
    explicit in-process instead:

    * causal market persistence / episode-opening work always enters before a fresh audit waiter;
    * append-only audit work may enter after a bounded starvation interval even while causal work
      remains queued, so a long collection cannot grow audit memory without bound;
    * readers never touch this gate and remain concurrent under WAL.

    The gate protects *admission*, not transaction semantics. Each existing store still owns its
    transaction and replay rules.
    """

    def __init__(self, *, audit_max_starvation_seconds: float = 0.5) -> None:
        if audit_max_starvation_seconds <= 0:
            raise ValueError("audit_max_starvation_seconds must be positive")
        self.audit_max_starvation_seconds = float(audit_max_starvation_seconds)
        self._condition = threading.Condition()
        self._active = False
        self._causal_waiters = 0
        self._audit_waiters = 0
        self._causal_acquisitions = 0
        self._audit_acquisitions = 0
        self._audit_forced_after_starvation = 0
        self._max_causal_waiters = 0
        self._max_audit_waiters = 0
        self._causal_wait_seconds: deque[float] = deque(maxlen=100_000)
        self._audit_wait_seconds: deque[float] = deque(maxlen=100_000)

    @contextmanager
    def acquire(self, priority: str):
        normalized = str(priority).strip().lower()
        if normalized not in {CAUSAL_PRIORITY, AUDIT_PRIORITY}:
            raise ValueError("unsupported sqlite write priority")

        started = time.perf_counter()
        forced_after_starvation = False
        with self._condition:
            if normalized == CAUSAL_PRIORITY:
                self._causal_waiters += 1
                self._max_causal_waiters = max(
                    self._max_causal_waiters,
                    self._causal_waiters,
                )
                try:
                    while self._active:
                        self._condition.wait()
                    self._active = True
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
                        if not self._active and (self._causal_waiters == 0 or starved):
                            forced_after_starvation = starved and self._causal_waiters > 0
                            self._active = True
                            break
                        timeout = None
                        if self._causal_waiters > 0 and not starved:
                            timeout = max(
                                0.001,
                                self.audit_max_starvation_seconds - waited,
                            )
                        self._condition.wait(timeout=timeout)
                finally:
                    self._audit_waiters -= 1

            wait_seconds = max(0.0, time.perf_counter() - started)
            if normalized == CAUSAL_PRIORITY:
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
            if self._active or self._causal_waiters or self._audit_waiters:
                raise RuntimeError("cannot reset sqlite write admission while work is active")
            self._causal_acquisitions = 0
            self._audit_acquisitions = 0
            self._audit_forced_after_starvation = 0
            self._max_causal_waiters = 0
            self._max_audit_waiters = 0
            self._causal_wait_seconds.clear()
            self._audit_wait_seconds.clear()

    def snapshot(self) -> SQLiteWriteAdmissionSnapshot:
        with self._condition:
            return SQLiteWriteAdmissionSnapshot(
                causal_acquisitions=self._causal_acquisitions,
                audit_acquisitions=self._audit_acquisitions,
                audit_forced_after_starvation=self._audit_forced_after_starvation,
                max_causal_waiters=self._max_causal_waiters,
                max_audit_waiters=self._max_audit_waiters,
                causal_wait_seconds=tuple(self._causal_wait_seconds),
                audit_wait_seconds=tuple(self._audit_wait_seconds),
            )


_GLOBAL_WRITE_ADMISSION = PrioritizedSQLiteWriteAdmission()


def sqlite_write_admission(priority: str):
    return _GLOBAL_WRITE_ADMISSION.acquire(priority)


def reset_sqlite_write_admission_metrics() -> None:
    _GLOBAL_WRITE_ADMISSION.reset_metrics()


def sqlite_write_admission_snapshot() -> SQLiteWriteAdmissionSnapshot:
    return _GLOBAL_WRITE_ADMISSION.snapshot()
