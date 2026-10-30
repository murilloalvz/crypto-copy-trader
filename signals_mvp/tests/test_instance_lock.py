"""Trava de instancia unica sobre o banco (FASE 1 do deploy Linux). So leitura/infra -- nunca
muda regra/sinal da estrategia."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ..instance_lock import InstanceLock, InstanceLockError, acquire_instance_lock, lock_path_for


class InstanceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "estado.sqlite"

    def test_second_lock_on_the_same_path_is_refused(self) -> None:
        first = acquire_instance_lock(self.db_path)
        self.assertIsNotNone(first)
        try:
            second = acquire_instance_lock(self.db_path)
            self.assertIsNone(second, "duas instancias nao podem travar o mesmo banco ao mesmo tempo")
        finally:
            first.release()

    def test_lock_is_reacquirable_after_release(self) -> None:
        first = acquire_instance_lock(self.db_path)
        self.assertIsNotNone(first)
        first.release()
        second = acquire_instance_lock(self.db_path)
        self.assertIsNotNone(second, "liberar o lock tem que deixar a proxima instancia travar")
        second.release()

    def test_lock_path_sits_next_to_the_db(self) -> None:
        self.assertEqual(lock_path_for(self.db_path), self.db_path.with_name("estado.sqlite.lock"))

    def test_context_manager_releases_on_exit(self) -> None:
        path = lock_path_for(self.db_path)
        with InstanceLock(path):
            outro = acquire_instance_lock(self.db_path)
            self.assertIsNone(outro)
        depois = acquire_instance_lock(self.db_path)
        self.assertIsNotNone(depois)
        depois.release()

    def test_direct_acquire_raises_with_a_clear_message(self) -> None:
        path = lock_path_for(self.db_path)
        held = InstanceLock(path)
        held.acquire()
        try:
            outro = InstanceLock(path)
            with self.assertRaises(InstanceLockError):
                outro.acquire()
        finally:
            held.release()


if __name__ == "__main__":
    unittest.main()
