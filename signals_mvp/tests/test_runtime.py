"""Worker (recarga a quente) e supervisor (reinicio, stall guard, parar) com processos filhos reais."""

from __future__ import annotations

import io
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

from ..instance_lock import acquire_instance_lock
from ..logging_setup import make_stdout_safe
from ..supervisor import Supervisor, pid_alive, read_pid, request_stop, run_supervisor
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


class ConsoleEncodingTest(unittest.TestCase):
    """BUG PRIORITARIO (2026-10-22, item 6): console do Windows forcado pra UTF-8 -- nao so 'errors=replace'
    (que mantinha o encoding cp1252/etc. do processo, produzindo mojibake como "â€”" pro em-dash sempre que
    o encoding do console e o do arquivo de log, que ja e UTF-8, nao combinavam)."""

    def test_make_stdout_safe_forces_utf8_encoding(self) -> None:
        original_out, original_err = sys.stdout, sys.stderr
        fake_out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        fake_err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        try:
            sys.stdout, sys.stderr = fake_out, fake_err
            make_stdout_safe()
            self.assertEqual(sys.stdout.encoding.lower().replace("_", "-"), "utf-8")
            self.assertEqual(sys.stderr.encoding.lower().replace("_", "-"), "utf-8")
            sys.stdout.write("POS-RUNNER — teste")   # em-dash: nunca pode lancar nem virar "?"
            sys.stdout.flush()
            raw = fake_out.buffer.getvalue()
            self.assertEqual(raw.decode("utf-8"), "POS-RUNNER — teste")
        finally:
            sys.stdout, sys.stderr = original_out, original_err


class HeartbeatTest(unittest.TestCase):
    def test_heartbeat_is_throttled_and_complete(self) -> None:
        path = Path(tempfile.mkdtemp()) / "hb.json"
        beat = Heartbeat(path)
        beat.cycle, beat.state = 7, "ciclo"
        beat.beat(force=True)
        first = json.loads(path.read_text())
        self.assertEqual((first["pid"], first["ciclo_atual"], first["estado"]), (os.getpid(), 7, "ciclo"))
        self.assertIn("ultimo_progresso_ts", first)   # BUG PRIORITARIO item 2: progresso real, nao so `ts`
        self.assertIn("chamadas_gt_total", first)
        beat.cycle = 8
        beat.beat()  # < 1 s depois: nao reescreve
        self.assertEqual(json.loads(path.read_text())["ciclo_atual"], 7)
        beat.beat(force=True)
        self.assertEqual(json.loads(path.read_text())["ciclo_atual"], 8)

    def test_mark_progress_updates_progress_fields_only_on_real_progress(self) -> None:
        path = Path(tempfile.mkdtemp()) / "hb.json"
        beat = Heartbeat(path)
        self.assertEqual(beat.last_progress_ts, 0.0)
        self.assertEqual(beat.gt_calls_total, 0)
        beat.mark_progress(gt_calls=5)
        self.assertGreater(beat.last_progress_ts, 0.0)
        self.assertEqual(beat.gt_calls_total, 5)
        beat.mark_progress(gt_calls=3)
        self.assertEqual(beat.gt_calls_total, 8)   # acumula, nunca reseta sozinho


DUMMY_WORKER = textwrap.dedent(
    """
    import json, os, sys, time, pathlib
    base = pathlib.Path(os.environ["SIGNALS_MVP_HOME"]); dados = base / "dados"; dados.mkdir(exist_ok=True)
    mode = sys.argv[1]
    counter = dados / "spawns.txt"
    counter.write_text((counter.read_text() if counter.exists() else "") + "x")
    def beat():
        (dados / "heartbeat.json").write_text(json.dumps({"ts": time.time(), "pid": os.getpid(), "ciclo": 1, "estado": "ok"}))
    def beat_new(progress_ts):
        (dados / "heartbeat.json").write_text(json.dumps(
            {"ts": time.time(), "pid": os.getpid(), "ciclo_atual": 1, "estado": "ok",
             "ultimo_progresso_ts": progress_ts, "chamadas_gt_total": 0}))
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
    if mode == "slow_progress":
        # BUG PRIORITARIO item 2: ciclos LENTOS mas que TERMINAM (ultimo_progresso_ts avanca a cada ~1s) --
        # nunca pode ser reiniciado so por isso, mesmo que cada "ciclo" individual demore mais que o poll.
        while not (dados / "PARAR").exists():
            beat_new(time.time())
            time.sleep(1.0)
        sys.exit(0)
    if mode == "frozen_progress":
        # processo vivo e escrevendo heartbeat (ts sempre fresco), mas NENHUM ciclo termina de verdade --
        # ultimo_progresso_ts fica parado no valor do 1o beat. So o criterio NOVO (progresso) pega isto.
        progress_ts = time.time()
        while not (dados / "PARAR").exists():
            beat_new(progress_ts)
            time.sleep(0.1)
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

    def test_slow_but_progressing_worker_is_never_restarted(self) -> None:
        """BUG PRIORITARIO item 2: ciclos lentos (cada um demora ~1s, bem mais que o poll de 0.1s) mas que
        TERMINAM (ultimo_progresso_ts avanca) nunca podem ser confundidos com travamento -- antes, so `ts`
        decidia, e um heartbeat so atualizado no fim do ciclo (como o worker real fazia) falso-positivava
        exatamente nesse cenario."""
        self.start("slow_progress", restart_base_s=0.1, stall_limit_s=2.0, startup_grace_s=1.0)
        time.sleep(4.0)   # varias "janelas" de progresso de 1s, bem alem do stall_limit_s=2.0 se fosse `ts` sozinho
        self.assertEqual(self.spawns(), 1, "nunca deveria reiniciar um loop que esta concluindo ciclos")

    def test_frozen_progress_with_fresh_ts_is_still_detected_as_a_stall(self) -> None:
        """O oposto do teste acima: processo vivo e escrevendo heartbeat (ts sempre fresco), mas nenhum ciclo
        termina de verdade (ultimo_progresso_ts nunca avanca) -- so o criterio NOVO de progresso pega isto;
        o `ts` sozinho nunca acusaria, porque ele continua se atualizando."""
        self.start("frozen_progress", restart_base_s=0.1, stall_limit_s=1.0, startup_grace_s=1.0)
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


class RunSupervisorInstanceLockTest(unittest.TestCase):
    """FASE 1 do deploy Linux (item 3): `run_supervisor` tem que recusar quando outra instancia ja
    tem o lock real sobre o banco -- mesmo sem nenhum pid_file (o cenario que o pid_file sozinho NAO
    cobre: outro processo/host com o mesmo banco compartilhado, ou um pid reciclado)."""

    def test_refuses_to_start_when_the_db_lock_is_already_held(self) -> None:
        env = Env()
        try:
            env.paths.dados.mkdir(parents=True, exist_ok=True)
            held = acquire_instance_lock(env.paths.db)
            self.assertIsNotNone(held)
            try:
                self.assertEqual(run_supervisor(env.paths), 1, "nao pode subir um 2o supervisor com o lock ocupado")
                self.assertFalse(env.paths.pid_file.exists(), "recusado antes de sequer escrever o pid_file")
            finally:
                held.release()
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
