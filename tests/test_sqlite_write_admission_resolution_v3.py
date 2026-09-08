from __future__ import annotations

import threading
import time
import unittest

from src.sqlite_write_admission import (
    CAUSAL_PRIORITY,
    RESOLUTION_PRIORITY,
    PrioritizedSQLiteWriteAdmission,
)


class SQLiteWriteAdmissionResolutionV3Tests(unittest.TestCase):
    def test_resolution_waiter_precedes_waiting_causal_writer(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.5)
        active_entered = threading.Event()
        release_active = threading.Event()
        causal_started = threading.Event()
        resolution_started = threading.Event()
        release_resolution = threading.Event()
        order = []
        lock = threading.Lock()

        def active():
            with gate.acquire(CAUSAL_PRIORITY):
                active_entered.set()
                self.assertTrue(release_active.wait(timeout=1.0))

        def causal():
            self.assertTrue(active_entered.wait(timeout=1.0))
            causal_started.set()
            with gate.acquire(CAUSAL_PRIORITY):
                with lock:
                    order.append("causal")

        def resolution():
            self.assertTrue(active_entered.wait(timeout=1.0))
            resolution_started.set()
            with gate.acquire(RESOLUTION_PRIORITY):
                with lock:
                    order.append("resolution")
                self.assertTrue(release_resolution.wait(timeout=1.0))

        threads = [
            threading.Thread(target=active),
            threading.Thread(target=causal),
            threading.Thread(target=resolution),
        ]
        for thread in threads:
            thread.start()
        self.assertTrue(causal_started.wait(timeout=1.0))
        self.assertTrue(resolution_started.wait(timeout=1.0))
        time.sleep(0.02)
        release_active.set()

        deadline = time.time() + 1.0
        while time.time() < deadline:
            with lock:
                if order:
                    break
            time.sleep(0.005)
        with lock:
            self.assertEqual(order[:1], ["resolution"])

        release_resolution.set()
        for thread in threads:
            thread.join(timeout=1.0)
        with lock:
            self.assertEqual(order, ["resolution", "causal"])

        snapshot = gate.snapshot()
        self.assertEqual(snapshot.resolution_acquisitions, 1)
        self.assertEqual(snapshot.causal_acquisitions, 2)
        self.assertGreaterEqual(snapshot.max_resolution_waiters, 1)

    def test_resolution_priority_is_still_single_writer(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.5)
        active = 0
        max_active = 0
        guard = threading.Lock()

        def work(priority):
            nonlocal active, max_active
            with gate.acquire(priority):
                with guard:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.02)
                with guard:
                    active -= 1

        threads = [
            threading.Thread(target=work, args=(RESOLUTION_PRIORITY,)),
            threading.Thread(target=work, args=(CAUSAL_PRIORITY,)),
            threading.Thread(target=work, args=(RESOLUTION_PRIORITY,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
