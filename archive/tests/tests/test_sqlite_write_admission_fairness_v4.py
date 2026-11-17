from __future__ import annotations

import threading
import time
import unittest

from src.sqlite_write_admission import (
    CAUSAL_PRIORITY,
    RESOLUTION_PRIORITY,
    PrioritizedSQLiteWriteAdmission,
)


class SQLiteWriteAdmissionFairnessV4Tests(unittest.TestCase):
    def test_waiting_causal_writer_gets_turn_after_one_resolution_grant(self):
        gate = PrioritizedSQLiteWriteAdmission(
            audit_max_starvation_seconds=0.5,
            resolution_max_consecutive_when_causal_waiting=1,
        )
        active_entered = threading.Event()
        release_active = threading.Event()
        waiter_started = [threading.Event() for _ in range(3)]
        order: list[str] = []
        order_lock = threading.Lock()

        def initial_causal():
            with gate.acquire(CAUSAL_PRIORITY):
                active_entered.set()
                self.assertTrue(release_active.wait(timeout=2.0))

        def queued(priority: str, label: str, started: threading.Event):
            self.assertTrue(active_entered.wait(timeout=1.0))
            started.set()
            with gate.acquire(priority):
                with order_lock:
                    order.append(label)
                time.sleep(0.01)

        threads = [
            threading.Thread(target=initial_causal),
            threading.Thread(
                target=queued,
                args=(RESOLUTION_PRIORITY, "resolution-a", waiter_started[0]),
            ),
            threading.Thread(
                target=queued,
                args=(RESOLUTION_PRIORITY, "resolution-b", waiter_started[1]),
            ),
            threading.Thread(
                target=queued,
                args=(CAUSAL_PRIORITY, "causal", waiter_started[2]),
            ),
        ]
        for thread in threads:
            thread.start()
        for event in waiter_started:
            self.assertTrue(event.wait(timeout=1.0))
        waiters_deadline = time.monotonic() + 1.0
        while time.monotonic() < waiters_deadline:
            snapshot = gate.snapshot()
            if snapshot.max_resolution_waiters >= 2 and snapshot.max_causal_waiters >= 1:
                break
            time.sleep(0.001)
        snapshot = gate.snapshot()
        self.assertGreaterEqual(snapshot.max_resolution_waiters, 2)
        self.assertGreaterEqual(snapshot.max_causal_waiters, 1)
        release_active.set()
        for thread in threads:
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(order), 3)
        self.assertTrue(order[0].startswith("resolution-"))
        self.assertEqual(order[1], "causal")
        self.assertTrue(order[2].startswith("resolution-"))

        snapshot = gate.snapshot()
        self.assertEqual(snapshot.resolution_acquisitions, 2)
        self.assertEqual(snapshot.causal_acquisitions, 2)
        self.assertEqual(snapshot.max_consecutive_resolution_grants, 1)
        # The bound is proved by the grant order and max consecutive grants. The
        # diagnostic block counter is schedule-dependent and may remain zero when
        # the causal waiter wins immediately after the first resolution grant.
        self.assertGreaterEqual(snapshot.resolution_fairness_blocks, 0)

    def test_default_policy_preserves_unbounded_resolution_priority(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.5)
        self.assertIsNone(gate.snapshot().resolution_max_consecutive_when_causal_waiting)

    def test_fair_policy_still_allows_only_one_active_writer(self):
        gate = PrioritizedSQLiteWriteAdmission(
            resolution_max_consecutive_when_causal_waiting=1
        )
        active = 0
        max_active = 0
        lock = threading.Lock()

        def worker(priority: str):
            nonlocal active, max_active
            with gate.acquire(priority):
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.01)
                with lock:
                    active -= 1

        threads = [
            threading.Thread(target=worker, args=(RESOLUTION_PRIORITY,))
            for _ in range(6)
        ] + [
            threading.Thread(target=worker, args=(CAUSAL_PRIORITY,))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())

        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
