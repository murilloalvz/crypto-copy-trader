"""Supervisor: sobe o worker, reinicia se cair e aplica o stall guard.

Stall guard: se o worker nao der sinal de vida (heartbeat) por mais de `ciclo.stall_guard_s`,
o supervisor loga ERRO, mata o worker e sobe outro.
Parar: `python -m signals_mvp parar` cria dados/PARAR; supervisor e worker veem a flag e saem.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .config import PACKAGE_DIR, ConfigError, Paths, load_config
from .logging_setup import setup_logging
from .telegram import TelegramClient, TelegramError
from .util import load_env

log = logging.getLogger("signals_mvp.supervisor")
console = logging.getLogger("signals_mvp.console")

DEFAULT_STALL_S = 300.0
STARTUP_GRACE_S = 90.0
RAPID_CRASH_S = 30.0
GRACEFUL_STOP_S = 20.0
EXIT_CONFIG_ERROR = 2


def pid_alive(pid: int) -> bool:
    """Checa se o processo existe SEM sinalizar (os.kill(pid, 0) MATA o processo no Windows)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - na duvida, considera vivo (o operador pode usar --forcar)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(paths: Paths) -> Optional[int]:
    try:
        return int(paths.pid_file.read_text().strip())
    except (OSError, ValueError):
        return None


def read_heartbeat(paths: Paths) -> Optional[dict]:
    try:
        return json.loads(paths.heartbeat.read_text())
    except (OSError, ValueError):
        return None


class Supervisor:
    def __init__(
        self,
        paths: Paths,
        worker_cmd: Optional[list[str]] = None,
        poll_s: float = 1.0,
        restart_base_s: float = 5.0,
        stall_limit_s: Optional[float] = None,
        startup_grace_s: float = STARTUP_GRACE_S,
        graceful_stop_s: float = GRACEFUL_STOP_S,
    ):
        self.paths = paths
        self.poll_s = poll_s
        self.restart_base_s = restart_base_s
        self.stall_limit_override = stall_limit_s
        self.startup_grace_s = startup_grace_s
        self.graceful_stop_s = graceful_stop_s
        self.worker_cmd = worker_cmd or [sys.executable, "-m", "signals_mvp", "worker"]
        self.stop_requested = False
        self._last_notify = 0.0
        self._telegram: Optional[TelegramClient] = None

    # -- util ---------------------------------------------------------------------------------
    def _notify(self, text: str) -> None:
        if self._telegram is None or time.time() - self._last_notify < 120:
            return
        try:
            self._telegram.notify(text)
            self._last_notify = time.time()
        except TelegramError:
            pass

    def _stall_limit(self) -> float:
        if self.stall_limit_override is not None:
            return self.stall_limit_override
        try:
            return float(load_config(self.paths.config)["ciclo"]["stall_guard_s"])
        except (ConfigError, KeyError, OSError):
            return DEFAULT_STALL_S

    def _spawn(self) -> subprocess.Popen:
        env = dict(os.environ)
        env["SIGNALS_MVP_HOME"] = str(self.paths.base)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return subprocess.Popen(self.worker_cmd, cwd=str(PACKAGE_DIR.parent), env=env)

    def _stop_worker(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        deadline = time.time() + self.graceful_stop_s
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            log.warning("worker nao saiu sozinho em %.0fs; terminando", self.graceful_stop_s)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    def _kill_worker(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    # -- principal ------------------------------------------------------------------------------
    def run(self) -> int:
        self.paths.dados.mkdir(parents=True, exist_ok=True)
        self.paths.pid_file.write_text(str(os.getpid()))
        self.paths.stop_flag.unlink(missing_ok=True)  # um 'iniciar' novo vale mais que um 'parar' antigo
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, lambda *_: setattr(self, "stop_requested", True))
                except (ValueError, OSError):
                    pass
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if token and chat:
            try:
                self._telegram = TelegramClient(token, chat)
            except TelegramError:
                self._telegram = None

        crashes = 0
        try:
            while not self._should_stop():
                started = time.time()
                proc = self._spawn()
                console.info("worker iniciado (pid %s)", proc.pid)
                reason = self._watch(proc, started)
                if reason == "stop":
                    self._stop_worker(proc)
                    break
                self._kill_worker(proc)
                if reason == "config":
                    console.warning("config.yaml invalida: corrija o arquivo (o bot tenta de novo sozinho quando ele mudar).")
                    self._wait_config_change()
                    continue
                crashes = crashes + 1 if time.time() - started < RAPID_CRASH_S else 0
                wait = min(60.0, self.restart_base_s * (2 ** min(crashes, 4))) if crashes else self.restart_base_s
                message = f"worker reiniciando em {wait:.0f}s (motivo: {reason})"
                log.error(message)
                console.warning(message)
                self._notify(f"⚠ Bot de sinais: {message}")
                self._sleep(wait)
        finally:
            self.paths.pid_file.unlink(missing_ok=True)
            self.paths.stop_flag.unlink(missing_ok=True)
        console.info("supervisor encerrado.")
        return 0

    def _should_stop(self) -> bool:
        return self.stop_requested or self.paths.stop_flag.exists()

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self._should_stop():
            time.sleep(min(self.poll_s, 0.5))

    def _wait_config_change(self) -> None:
        try:
            before = self.paths.config.stat().st_mtime_ns
        except OSError:
            before = 0
        while not self._should_stop():
            time.sleep(self.poll_s)
            try:
                if self.paths.config.stat().st_mtime_ns != before:
                    return
            except OSError:
                pass

    def _watch(self, proc: subprocess.Popen, started: float) -> str:
        """Bloqueia ate o worker sair, travar ou pedirem para parar. Devolve o motivo."""
        stall_limit = self._stall_limit()
        while True:
            if self._should_stop():
                return "stop"
            code = proc.poll()
            if code is not None:
                if code == EXIT_CONFIG_ERROR:
                    return "config"
                if self._should_stop():
                    return "stop"
                return f"worker saiu com codigo {code}"
            uptime = time.time() - started
            beat = read_heartbeat(self.paths)
            fresh = beat is not None and beat.get("pid") == proc.pid
            last = float(beat["ts"]) if fresh and "ts" in beat else None
            if last is None and uptime > self.startup_grace_s + stall_limit:
                log.error("STALL: worker sem heartbeat desde o inicio (%.0fs)", uptime)
                return f"stall: sem heartbeat ha {uptime:.0f}s"
            if last is not None and time.time() - last > stall_limit:
                log.error("STALL: sem ciclo ha %.0fs (limite %.0fs) — reiniciando o worker", time.time() - last, stall_limit)
                return f"stall: sem ciclo ha {time.time() - last:.0f}s"
            time.sleep(self.poll_s)


def run_supervisor(paths: Paths, force: bool = False) -> int:
    load_env(paths.env)
    # log proprio: no Windows dois processos nao podem rotacionar (renomear) o mesmo arquivo aberto
    setup_logging(paths, secrets=[os.environ.get("TELEGRAM_BOT_TOKEN", "")], filename="supervisor.log")
    existing = read_pid(paths)
    if existing and pid_alive(existing) and not force:
        console.error("O bot ja esta rodando (pid %s). Use 'parar' antes, ou 'iniciar --forcar' se tiver certeza que e um pid velho.", existing)
        return 1
    return Supervisor(paths).run()


def request_stop(paths: Paths, wait_s: float = 40.0) -> int:
    """Comando 'parar': cria a flag e espera o supervisor sair."""
    pid = read_pid(paths)
    paths.dados.mkdir(parents=True, exist_ok=True)
    if pid is None or not pid_alive(pid):
        print("O bot nao parece estar rodando (nenhum supervisor ativo).")
        paths.pid_file.unlink(missing_ok=True)
        paths.stop_flag.unlink(missing_ok=True)
        return 0
    paths.stop_flag.write_text("parar")
    print(f"Pedido de parada enviado (pid {pid}). Aguardando o bot gravar os CSVs e sair...")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if not pid_alive(pid):
            print("Bot parado. CSVs em:", paths.dados)
            paths.stop_flag.unlink(missing_ok=True)
            return 0
        time.sleep(0.5)
    print("O bot ainda nao saiu apos %.0fs. Feche a janela do bot ou finalize o processo python pelo Gerenciador de Tarefas." % wait_s)
    return 1
