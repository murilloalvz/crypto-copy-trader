"""Processo worker: monta os clientes e roda o ciclo para sempre (ate `parar`/Ctrl+C)."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Optional

from .config import Config, ConfigError, Paths, load_config
from .engine import Engine
from .geckoterminal import GtClient
from .goplus import GoPlusClient
from .http import ApiError, HttpClient, RateLimiter
from .logging_setup import setup_logging
from .narrative import MetaSet, load_meta
from .storage import Storage
from .telegram import OperatorHandler, TelegramClient, TelegramError, TelegramPoller
from .util import atomic_write_text, fmt_age, load_env, utc_now

log = logging.getLogger("signals_mvp.worker")
console = logging.getLogger("signals_mvp.console")

EXIT_CONFIG_ERROR = 2


class Heartbeat:
    """Escreve dados/heartbeat.json (no maximo 1x/s). O supervisor usa para detectar travamento."""

    def __init__(self, path: Path):
        self.path = path
        self._last = 0.0
        self.cycle = 0
        self.state = "iniciando"

    def beat(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 1.0:
            return
        self._last = now
        payload = {"ts": utc_now(), "pid": os.getpid(), "ciclo": self.cycle, "estado": self.state}
        try:
            atomic_write_text(self.path, json.dumps(payload))
        except OSError:
            pass  # heartbeat e melhor-esforco


def make_gt(cfg: Config) -> GtClient:
    g = cfg["gt"]
    limiter = RateLimiter(g["req_por_min"], g["burst"], pause_s=g["pausa_429_s"], pause_max_s=g["pausa_429_max_s"])
    wait_s = max(5.0, cfg["ciclo"]["intervalo_s"] / 3.0)  # cada chamada pode esperar ate 1/3 do ciclo por uma ficha
    return GtClient(HttpClient(g["base_url"], limiter, g["timeout_s"], name="GeckoTerminal"), wait_s=wait_s)


def make_goplus(cfg: Config) -> GoPlusClient:
    g = cfg["goplus"]
    limiter = RateLimiter(g["req_por_min"], 3, pause_s=g["pausa_erro_s"], pause_max_s=max(g["pausa_erro_s"], 300))
    http = HttpClient(g["base_url"], limiter, g["timeout_s"], name="GoPlus", error_pause_s=g["pausa_erro_s"])
    return GoPlusClient(http, batch_max=g["lote_max"])


def meta_path(paths: Paths, cfg: Config) -> Path:
    name = Path(cfg["narrativa"]["arquivo"])
    return name if name.is_absolute() else paths.base / name


def validate_networks(engine: Engine, gt: GtClient, telegram: Optional[TelegramClient]) -> None:
    """Confere se cada rede ligada existe no GeckoTerminal; se nao existir, desliga a chain e avisa."""
    try:
        ids = gt.network_ids()
    except ApiError as exc:
        log.warning("nao consegui validar as redes no GeckoTerminal (%s); seguindo com a config", exc)
        return
    for name, chain in list(engine.cfg.enabled_chains().items()):
        if chain["gt_rede"] not in ids:
            engine.disabled_chains.add(name)
            message = f"Rede '{chain['gt_rede']}' ({chain['nome']}) nao existe no GeckoTerminal: chain {name} DESLIGADA nesta execucao."
            log.error(message)
            console.warning(message)
            if telegram:
                try:
                    telegram.notify("\u26a0 " + message)
                except TelegramError:
                    pass


CLOCK_SKEW_WARN_S = 10.0


def clock_skew_message(skew: Optional[float]) -> Optional[str]:
    if skew is None or abs(skew) <= CLOCK_SKEW_WARN_S:
        return None
    side = "ADIANTADO" if skew > 0 else "ATRASADO"
    return (
        f"O relogio do PC esta {side} {abs(skew):.0f}s em relacao a internet: a idade dos pools e a latencia_s ficam ERRADAS. "
        "Sincronize a hora do Windows (Configuracoes > Hora e idioma > Sincronizar agora)."
    )


class Worker:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.stop = threading.Event()
        self._config_mtime = 0
        self._meta_mtime = 0
        self._config_error_mtime = 0

    # -- sinais de parada -------------------------------------------------------------------
    def _install_signals(self) -> None:
        def handler(signum, frame):  # noqa: ANN001, ARG001
            self.stop.set()

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass

    def stop_requested(self) -> bool:
        return self.stop.is_set() or self.paths.stop_flag.exists()

    # -- recarga a quente ---------------------------------------------------------------------
    def _mtime(self, path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    def reload_if_changed(self, engine: Engine, telegram: Optional[TelegramClient]) -> None:
        mtime = self._mtime(self.paths.config)
        if mtime and mtime != self._config_mtime:
            self._config_mtime = mtime
            try:
                new_cfg = load_config(self.paths.config)
            except ConfigError as exc:
                if mtime != self._config_error_mtime:
                    self._config_error_mtime = mtime
                    log.error("config.yaml alterado mas INVALIDO; mantendo a versao %s:\n%s", engine.cfg.version, exc)
                    console.warning("config.yaml invalido (mantendo %s). Veja logs/signals_mvp.log", engine.cfg.version)
                return
            old = engine.cfg.version
            if engine.set_config(new_cfg):
                message = f"CONFIG: nova versao {old} -> {new_cfg.version} (arquivo editado). Linhas novas usam a versao nova."
                log.warning(message)
                console.warning(message)
                if telegram:
                    try:
                        telegram.notify("\u2699 " + message)
                    except TelegramError:
                        pass
        path = meta_path(self.paths, engine.cfg)
        m_mtime = self._mtime(path)
        if m_mtime != self._meta_mtime:
            self._meta_mtime = m_mtime
            meta = load_meta(path)
            if meta.version != engine.meta.version:
                text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
                old_meta = engine.meta.version
                engine.set_meta(meta, text)
                console.info("META atualizado: %s -> %s (%d grupos)", old_meta, meta.version, len(meta.groups))

    # -- principal --------------------------------------------------------------------------------
    def run(self) -> int:
        load_env(self.paths.env)
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        setup_logging(self.paths, secrets=[token], debug=bool(os.environ.get("SIGNALS_MVP_DEBUG")))
        try:
            cfg = load_config(self.paths.config)
        except ConfigError as exc:
            console.error("CONFIG INVALIDA: %s", exc)
            return EXIT_CONFIG_ERROR
        self._install_signals()

        storage = Storage(self.paths)
        heartbeat = Heartbeat(self.paths.heartbeat)
        heartbeat.beat(force=True)
        telegram: Optional[TelegramClient] = None
        if token and chat_id:
            try:
                telegram = TelegramClient(token, chat_id)
            except TelegramError as exc:
                console.warning("Telegram desligado: %s", exc)
        else:
            console.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes no .env: o bot roda, loga os CSVs, mas NAO envia alertas.")

        gt = make_gt(cfg)
        meta = load_meta(meta_path(self.paths, cfg))
        engine = Engine(cfg, meta, storage, gt, make_goplus(cfg), telegram, heartbeat=heartbeat.beat)
        self._config_mtime = self._mtime(self.paths.config)
        self._meta_mtime = self._mtime(meta_path(self.paths, cfg))
        validate_networks(engine, gt, telegram)
        skew_message = clock_skew_message(gt.http.clock_skew_s())
        if skew_message:
            log.error(skew_message)
            console.warning(skew_message)
            if telegram:
                try:
                    telegram.notify("\u26a0 " + skew_message)
                except TelegramError:
                    pass

        poller: Optional[TelegramPoller] = None
        if telegram:
            handler = OperatorHandler(
                telegram, storage, lambda: engine.cfg, utc_now,
                status_provider=engine.status_text, summary_provider=engine.build_daily_summary,
            )
            try:
                telegram.get_me()
            except TelegramError as exc:
                console.warning("Telegram: getMe falhou (%s). Confira o token no .env.", exc)
            poller = TelegramPoller(telegram, handler, storage, self.stop)
            poller.start()
            self._announce_start(engine, storage, telegram)

        chains = ", ".join(c["nome"] for c in engine.enabled_chains().values())
        console.info("Bot de sinais v0 ligado | config %s | meta %s | chains: %s | PAPER/somente leitura", cfg.version, meta.version, chains)
        console.info("CSVs em %s | log em %s | Ctrl+C ou 'parar' para sair", self.paths.dados, self.paths.logs / "signals_mvp.log")

        while not self.stop_requested():
            cycle_started = time.monotonic()
            heartbeat.cycle = engine.cycle_count
            heartbeat.state = "ciclo"
            try:
                self.reload_if_changed(engine, telegram)
                stats = engine.run_cycle()
                p50 = sorted(engine.latencies)[len(engine.latencies) // 2] if engine.latencies else None
                console.info("ciclo %d (%.0fs) | %s", engine.cycle_count, stats.duration_s, stats.line(p50))
                engine.maybe_send_daily_summary()
            except Exception:  # noqa: BLE001 - o worker nao morre por erro de ciclo
                log.exception("erro no loop principal")
                self.stop.wait(5)
            heartbeat.cycle = engine.cycle_count
            heartbeat.state = "dormindo"
            deadline = cycle_started + engine.c["ciclo"]["intervalo_s"]
            if engine.last_stats is not None and engine.last_stats.rate_limited:
                # o ciclo foi cortado por um 429: retoma assim que a pausa acabar, nao depois do intervalo inteiro
                deadline = min(deadline, time.monotonic() + max(5.0, engine.gt_blocked_for()))
            while time.monotonic() < deadline and not self.stop_requested():
                heartbeat.beat()
                self.stop.wait(1.0)

        console.info("parando... (gravando CSVs)")
        self.stop.set()
        if poller is not None:
            poller.join(timeout=3)  # o long-poll pode estar no meio de uma espera; ele sai sozinho no proximo ciclo
        try:
            storage.export_csvs(force=True)
        finally:
            storage.close()
        heartbeat.state = "parado"
        heartbeat.beat(force=True)
        return 0

    @staticmethod
    def _announce_start(engine: Engine, storage: Storage, telegram: TelegramClient) -> None:
        """Avisa no Telegram que ligou (no maximo 1x a cada 10 min, para nao spammar em reinicios)."""
        now = utc_now()
        last = float(storage.get_meta("ultimo_aviso_inicio", "0") or 0)
        if now - last < 600:
            return
        chains = ", ".join(c["nome"] for c in engine.enabled_chains().values())
        try:
            telegram.notify(f"\U0001f916 Bot de sinais ligado (PAPER). config {engine.cfg.version} | meta {engine.meta.version} | chains: {chains}")
            storage.set_meta("ultimo_aviso_inicio", str(now))
        except TelegramError as exc:
            log.warning("aviso de inicio nao enviado: %s", exc)


def run_worker(paths: Paths) -> int:
    return Worker(paths).run()
