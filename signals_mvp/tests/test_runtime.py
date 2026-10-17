"""Worker (recarga a quente) e supervisor (reinicio, stall guard, parar) com processos filhos reais."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import yaml

from ..supervisor import Supervisor, pid_alive, read_pid, request_stop
from ..worker import Heartbeat, Worker
from .helpers import TEST_META, Env, config_with


class HotReloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        self.paths = self.env.paths
        self.write_config(self.env.cfg.raw)
        self.paths.meta.write_text(TEST_META, encoding="utf-8")
        self.worker = Worker(self.paths)

    def tearDown(self) -> None:
        self.env.close()

    def write_config(self, raw: dict) -> None:
        self.paths.config.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        stat = self.paths.config.stat()
        os.utime(self.paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))  # garante mtime diferente

    def test_unchanged_files_keep_the_version(self) -> None:
        before = self.env.engine.cfg.version
        self.worker.reload_if_changed(self.env.engine, None)
        self.assertEqual(self.env.engine.cfg.version, before)

    def test_edited_config_creates_a_new_version_and_notifies(self) -> None:
        old = self.env.engine.cfg.version
        self.worker.reload_if_changed(self.env.engine, self.env.tg)  # primeira leitura
        raw = config_with({"score": {"minimo_alerta": 70}}).raw
        self.write_config(raw)
        self.worker.reload_if_changed(self.env.engine, self.env.tg)
        new = self.env.engine.cfg.version
        self.assertNotEqual(old, new)
        self.assertEqual(self.env.engine.c["score"]["minimo_alerta"], 70)
        self.assertTrue(any(old in text and new in text for text in self.env.tg.notified))
        self.assertIsNotNone(self.env.storage.config_snapshot(new))
        self.assertTrue((self.paths.config_versions / f"{new}.json").exists())

    def test_broken_edit_keeps_running_with_the_previous_version(self) -> None:
        self.worker.reload_if_changed(self.env.engine, None)
        good = self.env.engine.cfg.version
        self.paths.config.write_text("modo: [quebrado\n", encoding="utf-8")
        stat = self.paths.config.stat()
        os.utime(self.paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 20_000_000))
        self.worker.reload_if_changed(self.env.engine, None)  # nao levanta
        self.assertEqual(self.env.engine.cfg.version, good)
        bad_values = config_with().raw
        bad_values["plano"]["sl_pct"] = 0
        self.write_config(bad_values)
        self.worker.reload_if_changed(self.env.engine, None)
        self.assertEqual(self.env.engine.cfg.version, good)

    def test_meta_edit_changes_meta_version_only(self) -> None:
        self.worker.reload_if_changed(self.env.engine, None)
        cfg_version, meta_version = self.env.engine.cfg.version, self.env.engine.meta.version
        self.paths.meta.write_text(TEST_META + "ANIME: naruto\n", encoding="utf-8")
        stat = self.paths.meta.stat()
        os.utime(self.paths.meta, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        self.worker.reload_if_changed(self.env.engine, None)
        self.assertEqual(self.env.engine.cfg.version, cfg_version)
        self.assertNotEqual(self.env.engine.meta.version, meta_version)
        self.assertIn("ANIME", self.env.engine.meta.groups)


class HeartbeatTest(unittest.TestCase):
    def test_heartbeat_is_throttled_and_complete(self) -> None:
        path = Path(tempfile.mkdtemp()) / "hb.json"
        beat = Heartbeat(path)
        beat.cycle, beat.state = 7, "ciclo"
        beat.beat(force=True)
        first = json.loads(path.read_text())
        self.assertEqual((first["pid"], first["ciclo"], first["estado"]), (os.getpid(), 7, "ciclo"))
        beat.cycle = 8
        beat.beat()  # < 1 s depois: nao reescreve
        self.assertEqual(json.loads(path.read_text())["ciclo"], 7)
        beat.beat(force=True)
        self.assertEqual(json.loads(path.read_text())["ciclo"], 8)


DUMMY_WORKER = textwrap.dedent(
    """
    import json, os, sys, time, pathlib
    base = pathlib.Path(os.environ["SIGNALS_MVP_HOME"]); dados = base / "dados"; dados.mkdir(exist_ok=True)
    mode = sys.argv[1]
    counter = dados / "spawns.txt"
    counter.write_text((counter.read_text() if counter.exists() else "") + "x")
    def beat():
        (dados / "heartbeat.json").write_text(json.dumps({"ts": time.time(), "pid": os.getpid(), "ciclo": 1, "estado": "ok"}))
    if mode == "crash":
        sys.exit(1)
    if mode == "config":
        sys.exit(2)
    if mode == "stall":
        beat(); time.sleep(120)
    if mode == "good":
        while not (dados / "PARAR").exists():
            beat(); time.sleep(0.1)
        sys.exit(0)
    """
)


class SupervisorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        self.paths = self.env.paths
        self.script = self.paths.base / "dummy_worker.py"
        self.script.write_text(DUMMY_WORKER, encoding="utf-8")
        self.paths.dados.mkdir(parents=True, exist_ok=True)
        self.supervisors: list[tuple[Supervisor, threading.Thread]] = []

    def tearDown(self) -> None:
        self.paths.stop_flag.write_text("x")
        for supervisor, thread in self.supervisors:
            supervisor.stop_requested = True
            thread.join(timeout=15)
        self.env.close()

    def start(self, mode: str, **kw) -> Supervisor:
        kw.setdefault("graceful_stop_s", 1.0)
        supervisor = Supervisor(self.paths, worker_cmd=[sys.executable, str(self.script), mode], poll_s=0.1, **kw)
        thread = threading.Thread(target=supervisor.run, daemon=True)
        thread.start()
        self.supervisors.append((supervisor, thread))
        return supervisor

    def spawns(self) -> int:
        counter = self.paths.dados / "spawns.txt"
        return len(counter.read_text()) if counter.exists() else 0

    def wait_for(self, predicate, timeout: float = 15.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_crashing_worker_is_restarted(self) -> None:
        self.start("crash", restart_base_s=0.1)
        self.assertTrue(self.wait_for(lambda: self.spawns() >= 3), f"spawns={self.spawns()}")

    def test_stalled_worker_is_killed_and_restarted(self) -> None:
        self.start("stall", restart_base_s=0.1, stall_limit_s=1.0, startup_grace_s=1.0)
        self.assertTrue(self.wait_for(lambda: self.spawns() >= 2, timeout=20), f"spawns={self.spawns()}")

    def test_healthy_worker_runs_until_stop_flag_then_everything_is_cleaned(self) -> None:
        supervisor = self.start("good", restart_base_s=0.1, stall_limit_s=5.0)
        self.assertTrue(self.wait_for(lambda: self.paths.heartbeat.exists()))
        self.assertTrue(self.wait_for(lambda: read_pid(self.paths) == os.getpid()))
        self.assertEqual(self.spawns(), 1)
        self.paths.stop_flag.write_text("parar")
        thread = self.supervisors[-1][1]
        thread.join(timeout=20)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.paths.pid_file.exists())
        self.assertFalse(self.paths.stop_flag.exists())
        self.assertEqual(self.spawns(), 1)  # nao reiniciou
        _ = supervisor

    def test_invalid_config_waits_for_the_file_to_change(self) -> None:
        self.paths.config.write_text("x: 1\n", encoding="utf-8")
        self.start("config", restart_base_s=0.1)
        self.assertTrue(self.wait_for(lambda: self.spawns() == 1))
        time.sleep(1.0)
        self.assertEqual(self.spawns(), 1)  # nao fica em loop reiniciando
        stat = self.paths.config.stat()
        os.utime(self.paths.config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 50_000_000))
        self.assertTrue(self.wait_for(lambda: self.spawns() == 2))


class StopCommandTest(unittest.TestCase):
    def test_stop_without_a_running_bot(self) -> None:
        env = Env()
        try:
            self.assertEqual(request_stop(env.paths, wait_s=1), 0)
            self.assertFalse(env.paths.stop_flag.exists())
            env.paths.dados.mkdir(parents=True, exist_ok=True)
            env.paths.pid_file.write_text("99999999")  # pid inexistente = arquivo velho
            self.assertEqual(request_stop(env.paths, wait_s=1), 0)
            self.assertFalse(env.paths.pid_file.exists())
        finally:
            env.close()

    def test_pid_alive(self) -> None:
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(99999999))
        self.assertFalse(pid_alive(0))


if __name__ == "__main__":
    unittest.main()
