"""Trava de instancia unica sobre o arquivo do banco (item 3 do deploy Linux).

Diferente de um arquivo de PID (ja existente em `supervisor.py` -- bom para a mensagem de erro, mas
sofre de PID reciclado pelo SO depois de uma queda), este lock usa a primitiva de lock de arquivo do
proprio SO (`flock` no POSIX, `msvcrt.locking` no Windows): o SO libera o lock automaticamente quando
o processo morre, mesmo sem saida limpa (kill -9, queda de energia) -- nunca fica "travado" sozinho.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


class InstanceLockError(RuntimeError):
    """Já existe outra instância com o lock -- nunca sobe um segundo supervisor/worker no mesmo banco."""


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> None:
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise InstanceLockError(
                f"já existe outra instância rodando (lock ocupado: {self.path}) -- pare-a antes "
                "('parar' ou 'systemctl stop'), ou confirme que não é um lock órfão de outro sistema."
            ) from exc
        self._fh = fh

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        self._fh = None
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            fh.close()

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def lock_path_for(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".lock")


def acquire_instance_lock(db_path: Path) -> Optional[InstanceLock]:
    """Tenta travar; devolve None (sem levantar) se já tiver outra instância -- quem chama decide a
    mensagem/código de saída."""
    lock = InstanceLock(lock_path_for(db_path))
    try:
        lock.acquire()
    except InstanceLockError:
        return None
    return lock
