import threading
import time
import unittest

from src.sqlite_write_admission import (
    AUDIT_PRIORITY,
    CAUSAL_PRIORITY,
    PrioritizedSQLiteWriteAdmission,
)


class PrioritizedSQLiteWriteAdmissionTests(unittest.TestCase):
    def test_causal_writers_are_serialized(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.2)
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first():
            with gate.acquire(CAUSAL_PRIORITY):
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=1.0))

        def second():
            self.assertTrue(first_entered.wait(timeout=1.0))
            with gate.acquire(CAUSAL_PRIORITY):
                second_entered.set()

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        self.assertTrue(first_entered.wait(timeout=1.0))
        time.sleep(0.02)
        self.assertFalse(second_entered.is_set())
        release_first.set()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)
        self.assertTrue(second_entered.is_set())

        snapshot = gate.snapshot()
        self.assertEqual(snapshot.causal_acquisitions, 2)
        self.assertEqual(snapshot.audit_acquisitions, 0)
        self.assertGreaterEqual(snapshot.max_causal_waiters, 1)

    def test_fresh_audit_waiter_yields_to_waiting_causal_writer(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.5)
        active_entered = threading.Event()
        release_active = threading.Event()
        causal_waiting = threading.Event()
        release_second_causal = threading.Event()
        audit_entered = threading.Event()
        order = []
        order_lock = threading.Lock()

        def active_causal():
            with gate.acquire(CAUSAL_PRIORITY):
                active_entered.set()
                self.assertTrue(release_active.wait(timeout=1.0))

        def audit():
            self.assertTrue(active_entered.wait(timeout=1.0))
            with gate.acquire(AUDIT_PRIORITY):
                with order_lock:
                    order.append("audit")
                audit_entered.set()

        def second_causal():
            self.assertTrue(active_entered.wait(timeout=1.0))
            causal_waiting.set()
            with gate.acquire(CAUSAL_PRIORITY):
                with order_lock:
                    order.append("causal")
                self.assertTrue(release_second_causal.wait(timeout=1.0))

        t_active = threading.Thread(target=active_causal)
        t_audit = threading.Thread(target=audit)
        t_causal = threading.Thread(target=second_causal)
        t_active.start()
        self.assertTrue(active_entered.wait(timeout=1.0))
        t_audit.start()
        time.sleep(0.01)
        t_causal.start()
        self.assertTrue(causal_waiting.wait(timeout=1.0))
        time.sleep(0.02)
        release_active.set()

        deadline = time.time() + 1.0
        while time.time() < deadline:
            with order_lock:
                if order:
                    break
            time.sleep(0.005)
        with order_lock:
            self.assertEqual(order[:1], ["causal"])
        self.assertFalse(audit_entered.is_set())

        release_second_causal.set()
        for thread in (t_active, t_causal, t_audit):
            thread.join(timeout=1.0)
        self.assertTrue(audit_entered.is_set())
        with order_lock:
            self.assertEqual(order, ["causal", "audit"])

    def test_gate_releases_after_exception(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.2)
        with self.assertRaises(RuntimeError):
            with gate.acquire(CAUSAL_PRIORITY):
                raise RuntimeError("boom")

        with gate.acquire(AUDIT_PRIORITY):
            pass
        snapshot = gate.snapshot()
        self.assertEqual(snapshot.causal_acquisitions, 1)
        self.assertEqual(snapshot.audit_acquisitions, 1)

    def test_reset_metrics_requires_idle_gate(self):
        gate = PrioritizedSQLiteWriteAdmission(audit_max_starvation_seconds=0.2)
        with gate.acquire(CAUSAL_PRIORITY):
            with self.assertRaises(RuntimeError):
                gate.reset_metrics()
        gate.reset_metrics()
        snapshot = gate.snapshot()
        self.assertEqual(snapshot.causal_acquisitions, 0)
        self.assertEqual(snapshot.audit_acquisitions, 0)
        self.assertEqual(snapshot.causal_wait_seconds, ())
        self.assertEqual(snapshot.audit_wait_seconds, ())


if __name__ == "__main__":
    unittest.main()
