"""Ciclo de vida completo do worker (ligar -> ciclos -> parar) com APIs e Telegram falsos, sem rede."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

from ..config import PACKAGE_DIR, make_paths
from ..pos_runner.live import LiveSettings
from ..worker import Worker, resolve_chamadas_por_ciclo
from .fakes import FakeClock, FakeGoPlus, FakeGt, FakeTelegram
from .helpers import read_csv


class FakeTgClient(FakeTelegram):
    """Mesma interface do TelegramClient real para o worker/poller."""

    def __init__(self, token: str, chat_id: str, *a, **kw) -> None:
        super().__init__()
        self.token, self.chat_id = token, str(chat_id)

    def get_me(self) -> dict:
        return {"username": "bot_de_teste"}

    def get_updates(self, offset: int, timeout: int = 25) -> list:
        time.sleep(0.1)
        return []


class WorkerLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="signals_mvp_worker_"))
        raw = yaml.safe_load((PACKAGE_DIR / "config.yaml").read_text(encoding="utf-8"))
        raw["ciclo"]["intervalo_s"] = 5
        raw["ciclo"]["stall_guard_s"] = 60
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        (self.tmp / "meta.txt").write_text("IA: ai\n", encoding="utf-8")
        (self.tmp / ".env").write_text("TELEGRAM_BOT_TOKEN=123456789:AAH-fake_token_for_unit_tests_0123\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
        self.paths = make_paths(self.tmp)

    def tearDown(self) -> None:
        root = logging.getLogger("signals_mvp")  # o worker reconfigura o logging global
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_cycle_stop(self) -> None:
        gt = FakeGt(FakeClock(time.time()))
        fake_tg: list[FakeTgClient] = []

        def make_tg(token: str, chat_id: str) -> FakeTgClient:
            client = FakeTgClient(token, chat_id)
            fake_tg.append(client)
            return client

        result: list[int] = []
        with mock.patch("signals_mvp.worker.make_gt", lambda cfg: gt), \
             mock.patch("signals_mvp.worker.make_goplus", lambda cfg: FakeGoPlus()), \
             mock.patch("signals_mvp.worker.TelegramClient", make_tg):
            worker = Worker(self.paths)
            thread = threading.Thread(target=lambda: result.append(worker.run()), daemon=True)
            thread.start()
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    beat = json.loads(self.paths.heartbeat.read_text())
                    if beat.get("ciclo", 0) >= 1 and beat.get("estado") == "dormindo":
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            self.assertTrue(self.paths.sinais_csv.exists(), "o primeiro ciclo deveria ter exportado os CSVs")
            self.paths.stop_flag.write_text("parar")  # igual ao comando `parar`
            thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [0])
        beat = json.loads(self.paths.heartbeat.read_text())
        self.assertEqual(beat["estado"], "parado")
        self.assertEqual(read_csv(self.paths.sinais_csv), [])
        self.assertTrue(self.paths.descartados_csv.exists() and self.paths.trades_csv.exists())
        self.assertTrue(any("Bot de sinais ligado" in text for text in fake_tg[0].notified))   # avisou no Telegram que ligou
        self.assertTrue((self.paths.logs / "signals_mvp.log").exists())
        # o token do Telegram nunca aparece no log
        self.assertNotIn("AAH-fake", (self.paths.logs / "signals_mvp.log").read_text(encoding="utf-8"))

    def test_invalid_config_exits_with_code_2(self) -> None:
        (self.tmp / "config.yaml").write_text("modo: paper\n", encoding="utf-8")
        with mock.patch("signals_mvp.worker.TelegramClient", FakeTgClient):
            self.assertEqual(Worker(self.paths).run(), 2)

    def test_network_missing_from_geckoterminal_disables_the_chain(self) -> None:
        gt = FakeGt(FakeClock(time.time()))
        gt.network_ids = lambda max_pages=4: {"solana", "bsc"}  # type: ignore[method-assign]  # robinhood sumiu
        fake_tg: list[FakeTgClient] = []
        with mock.patch("signals_mvp.worker.make_gt", lambda cfg: gt), \
             mock.patch("signals_mvp.worker.make_goplus", lambda cfg: FakeGoPlus()), \
             mock.patch("signals_mvp.worker.TelegramClient", lambda t, c: fake_tg.append(FakeTgClient(t, c)) or fake_tg[-1]):
            worker = Worker(self.paths)
            self.paths.stop_flag.parent.mkdir(parents=True, exist_ok=True)
            self.paths.stop_flag.write_text("parar")   # sobe, valida as redes e sai sem rodar ciclo
            self.assertEqual(worker.run(), 0)
        self.assertTrue(any("robinhood" in text and "DESLIGADA" in text for text in fake_tg[0].notified))


class ChamadasPorCicloTests(unittest.TestCase):
    """FASE 1.1 (revisao 2026-10-22): orcamento de chamadas/ciclo do POS-RUNNER configuravel por env."""

    def test_env_var_always_wins(self) -> None:
        settings = LiveSettings(chamadas_por_ciclo=3)
        out = resolve_chamadas_por_ciclo(settings, {}, sem_v0=False, env={"POS_RUNNER_CHAMADAS_POR_CICLO": "5"})
        self.assertEqual(out.chamadas_por_ciclo, 5)

    def test_env_var_wins_even_over_an_explicit_config_value_with_sem_v0(self) -> None:
        settings = LiveSettings(chamadas_por_ciclo=20)
        out = resolve_chamadas_por_ciclo(settings, {"chamadas_por_ciclo": 20}, sem_v0=True,
                                         env={"POS_RUNNER_CHAMADAS_POR_CICLO": "5"})
        self.assertEqual(out.chamadas_por_ciclo, 5)

    def test_sem_v0_defaults_to_8_when_the_operator_never_set_it(self) -> None:
        settings = LiveSettings(chamadas_por_ciclo=3)   # default do dataclass (V0 ligado)
        out = resolve_chamadas_por_ciclo(settings, {}, sem_v0=True, env={})
        self.assertEqual(out.chamadas_por_ciclo, 8)

    def test_sem_v0_never_overrides_an_explicit_operator_value_in_the_config(self) -> None:
        settings = LiveSettings(chamadas_por_ciclo=12)
        out = resolve_chamadas_por_ciclo(settings, {"chamadas_por_ciclo": 12}, sem_v0=True, env={})
        self.assertEqual(out.chamadas_por_ciclo, 12)

    def test_with_v0_ligado_and_no_env_the_config_value_is_untouched(self) -> None:
        settings = LiveSettings(chamadas_por_ciclo=3)
        out = resolve_chamadas_por_ciclo(settings, {}, sem_v0=False, env={})
        self.assertEqual(out.chamadas_por_ciclo, 3)


class EnvBoolTests(unittest.TestCase):
    """BUG PRIORITARIO (2026-10-22, item 3): `_env_bool` decide o `SEM_LEGADO`."""

    def test_absent_or_blank_is_none(self) -> None:
        from ..worker import _env_bool
        self.assertIsNone(_env_bool("SEM_LEGADO", env={}))
        self.assertIsNone(_env_bool("SEM_LEGADO", env={"SEM_LEGADO": "  "}))

    def test_falsy_spellings(self) -> None:
        from ..worker import _env_bool
        for value in ("0", "false", "False", "nao", "NAO", "não", "off"):
            with self.subTest(value):
                self.assertFalse(_env_bool("SEM_LEGADO", env={"SEM_LEGADO": value}))

    def test_anything_else_is_true(self) -> None:
        from ..worker import _env_bool
        for value in ("1", "true", "sim", "on", "qualquer coisa"):
            with self.subTest(value):
                self.assertTrue(_env_bool("SEM_LEGADO", env={"SEM_LEGADO": value}))


class _FakeLive:
    def __init__(self, chain_name: str, ligado: bool) -> None:
        self.chain_name = chain_name
        self._ligado = ligado
        self.chain_capabilities: dict = {}

    def enabled(self) -> bool:
        return self._ligado


class _FakeCapability:
    def __init__(self, ok: bool, motivo: str = "") -> None:
        self.ok = ok
        self.motivo = motivo


class _FakeEngineForStartupText:
    def __init__(self, legado_ligado: bool, pos_runner: Any, cfg_raw: dict) -> None:
        self.legado_ligado = legado_ligado
        self.pos_runner = pos_runner
        self.cfg = type("_Cfg", (), {"raw": cfg_raw})()

    def chains_status_text(self) -> str:
        return "ativas: nenhuma"


class PosRunnerStartupTextTests(unittest.TestCase):
    """PEDIDO ADICIONAL FASE 6, item 3: "Bot ligado" nunca pode mostrar "chains ativas: nenhuma" so
    porque o motor legado (V0) foi desligado para a V1 assumir o orcamento de GT -- tem que mostrar o
    estado real da V1 (e de BSC/Robinhood, via a deteccao de capacidade real do startup)."""

    CFG_RAW = {"chains": {"solana": {"nome": "SOL"}, "bsc": {"nome": "BSC"}, "robinhood": {"nome": "ROBINHOOD"}}}

    def test_pos_runner_chains_status_text_shows_the_real_v1_and_adapter_state(self) -> None:
        from ..worker import _pos_runner_chains_status_text

        live = _FakeLive("SOL", ligado=True)
        capabilities = {"bsc": _FakeCapability(True), "robinhood": _FakeCapability(False, "sem rede no GeckoTerminal")}
        text = _pos_runner_chains_status_text(type("_Cfg", (), {"raw": self.CFG_RAW})(), live, capabilities)
        self.assertEqual(text, "POS-RUNNER V1 (SOL): ativo | BSC: só detecção | ROBINHOOD: desligada (sem rede no GeckoTerminal)")

    def test_pos_runner_chains_status_text_shows_desligado_when_not_enabled(self) -> None:
        from ..worker import _pos_runner_chains_status_text

        live = _FakeLive("SOL", ligado=False)
        text = _pos_runner_chains_status_text(type("_Cfg", (), {"raw": self.CFG_RAW})(), live, {})
        self.assertEqual(text, "POS-RUNNER V1 (SOL): desligado")

    def test_startup_text_uses_pos_runner_alone_when_legado_is_off(self) -> None:
        from ..worker import _startup_chains_text

        live = _FakeLive("SOL", ligado=True)
        live.chain_capabilities = {"bsc": _FakeCapability(True)}
        engine = _FakeEngineForStartupText(legado_ligado=False, pos_runner=live, cfg_raw=self.CFG_RAW)
        text = _startup_chains_text(engine)
        self.assertNotIn("nenhuma", text)
        self.assertIn("POS-RUNNER V1 (SOL): ativo", text)
        self.assertIn("BSC: só detecção", text)

    def test_startup_text_shows_both_when_legado_and_pos_runner_are_both_on(self) -> None:
        from ..worker import _startup_chains_text

        live = _FakeLive("SOL", ligado=True)
        engine = _FakeEngineForStartupText(legado_ligado=True, pos_runner=live, cfg_raw=self.CFG_RAW)
        text = _startup_chains_text(engine)
        self.assertIn("ativas: nenhuma", text)   # texto do V0 (fake), nunca escondido
        self.assertIn("POS-RUNNER V1 (SOL): ativo", text)

    def test_startup_text_falls_back_to_the_legacy_text_without_any_pos_runner(self) -> None:
        from ..worker import _startup_chains_text

        engine = _FakeEngineForStartupText(legado_ligado=False, pos_runner=None, cfg_raw=self.CFG_RAW)
        self.assertEqual(_startup_chains_text(engine), "ativas: nenhuma")


_ = shutil

if __name__ == "__main__":
    unittest.main()
