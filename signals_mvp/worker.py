"""Processo worker: monta os clientes e roda o ciclo para sempre (ate `parar`/Ctrl+C)."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .config import PACKAGE_DIR, Config, ConfigError, Paths, load_config
from .engine import Engine
from .geckoterminal import GtClient
from . import backup, healthchecks
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


def _env_bool(name: str, env: Optional[dict] = None) -> Optional[bool]:
    """None = variavel ausente/vazia (deixa o chamador decidir o padrao); senao, True/False por valor
    (qualquer coisa exceto '0'/'false'/'nao'/'não'/'off' e True)."""
    raw = (env if env is not None else os.environ).get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() not in ("0", "false", "nao", "não", "off")


class Heartbeat:
    """Escreve dados/heartbeat.json (no maximo 1x/s). O supervisor usa para detectar travamento.

    BUG PRIORITARIO (2026-10-22, item 2): `ts` por si so e um falso-positivo em potencial -- antes da
    correcao, so era atualizado dentro do loop de espera DEPOIS de `run_cycle()` terminar; um ciclo mais
    lento que `ciclo.intervalo_s` (ex.: o motor legado em pausa de 429) fazia esse loop nao rodar nenhuma
    vez, entao `ts` ficava parado mesmo com o worker vivo e progredindo. Agora `ts` e escrito por uma
    THREAD SEPARADA (`HeartbeatWriter`), de tempo em tempo, independente do ciclo -- prova so que o
    processo/interpretador ainda responde. `ultimo_progresso_ts`/`chamadas_gt_total` (atualizados so quando
    um ciclo de verdade termina, via `mark_progress`) e que provam PROGRESSO real; o watchdog usa os dois
    (ver `supervisor.py`)."""

    def __init__(self, path: Path):
        self.path = path
        self._last = 0.0
        self.cycle = 0
        self.state = "iniciando"
        self.last_progress_ts: float = 0.0
        self.gt_calls_total: int = 0

    def mark_progress(self, gt_calls: int = 0) -> None:
        """Chamado quando um ciclo de verdade TERMINA (nunca pela thread de escrita, que so repete o que
        ja esta aqui)."""
        self.last_progress_ts = utc_now()
        self.gt_calls_total += max(0, gt_calls)

    def beat(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 1.0:
            return
        self._last = now
        payload = {
            "ts": utc_now(), "pid": os.getpid(), "ciclo_atual": self.cycle, "estado": self.state,
            "ultimo_progresso_ts": self.last_progress_ts, "chamadas_gt_total": self.gt_calls_total,
        }
        try:
            atomic_write_text(self.path, json.dumps(payload))
        except OSError:
            pass  # heartbeat e melhor-esforco


class HeartbeatWriter(threading.Thread):
    """Thread dedicada (BUG PRIORITARIO item 2): grava o heartbeat a cada `interval_s` (padrao 30s) POR
    TEMPO, nunca por ciclo -- continua vivo mesmo que o loop principal esteja ocupado numa chamada de rede
    lenta (I/O de rede libera o GIL; so um ciclo REALMENTE travado no CPython para esta thread tambem, e
    nesse caso faltar o heartbeat e o sinal correto de processo congelado)."""

    def __init__(self, heartbeat: Heartbeat, stop: threading.Event, interval_s: float = 30.0):
        super().__init__(name="heartbeat-writer", daemon=True)
        self.heartbeat = heartbeat
        self.stop_event = stop
        self.interval_s = interval_s

    def run(self) -> None:
        while not self.stop_event.wait(self.interval_s):
            self.heartbeat.beat(force=True)


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
            engine.disabled_chain_reasons[name] = f"sem rede {chain['gt_rede']!r} no GeckoTerminal"
            message = f"Rede '{chain['gt_rede']}' ({chain['nome']}) nao existe no GeckoTerminal: chain {name} DESLIGADA nesta execucao."
            log.error(message)
            console.warning(message)
            if telegram:
                try:
                    telegram.notify("\u26a0 " + message)
                except TelegramError:
                    pass


def _check_fase2_capabilities(http: Any, telegram: Optional[TelegramClient], paths: Paths) -> dict[str, Any]:
    """FASE 2 (prompt, secao 5): so a deteccao de capacidade real (networks + OHLCV de amostra num pool real)
    + log/aviso no Telegram, 1x no startup -- nunca liga descoberta/holders de BSC/Robinhood. `capable()`
    continua False por decisao explicita do operador ("mantendo BSC e Robinhood desligadas por padrao"); isto
    so confirma e registra o estado real (rede existe? tem OHLCV?) em vez de deixar a pergunta em aberto.
    Devolve {nome: Capability} (FASE 3, item 4) para a mensagem de startup mostrar o estado real, nunca um
    texto fixo."""
    from .pos_runner.chain_adapter import BscAdapter, RobinhoodAdapter

    cache_root = paths.dados / "pos_runner"
    adapters = (
        BscAdapter(http, telegram=telegram, cache_dir=cache_root / "bsc_ohlcv"),
        RobinhoodAdapter(http, telegram=telegram, cache_dir=cache_root / "robinhood_ohlcv"),
    )
    capabilities: dict[str, Any] = {}
    for adapter in adapters:
        try:
            capabilities[adapter.name] = adapter.check()
        except Exception:
            log.exception("POS-RUNNER-V1: falha ao verificar capacidade de %s", adapter.name)
    return capabilities


def resolve_chamadas_por_ciclo(settings: Any, raw: dict, sem_v0: bool, env: Optional[dict] = None) -> Any:
    """Orcamento de chamadas/ciclo do POS-RUNNER (FASE 1.1, revisao 2026-10-22). Prioridade:
    `POS_RUNNER_CHAMADAS_POR_CICLO` (env) sempre manda quando setado; senao, V0 desligado troca o padrao de 3
    para 8/ciclo (~10/min: a V1 sozinha, so 1h, precisa de muito menos do que as 3 tfs do V0) -- MAS nunca
    pisa um valor que o operador ja escreveu explicitamente no config.yaml. O backoff adaptativo em 429 e o
    mesmo RateLimiter (AIMD) que toda chamada do GT ja usa (http.py) -- nada novo aqui, so o orcamento."""
    env = os.environ if env is None else env
    chamadas_env = env.get("POS_RUNNER_CHAMADAS_POR_CICLO")
    if chamadas_env is not None:
        return dataclasses.replace(settings, chamadas_por_ciclo=int(chamadas_env))
    if sem_v0 and raw.get("chamadas_por_ciclo") is None:
        return dataclasses.replace(settings, chamadas_por_ciclo=8)
    return settings


def make_pos_runner(cfg: Config, paths: Paths, storage: Storage, engine: Engine, gt: GtClient,
                    telegram: Optional[TelegramClient], stop: threading.Event) -> Optional[object]:
    """POS-RUNNER ao vivo (Parte B): V0 (silencioso ou nao, conforme `pos_runner.alertas.*`) e V1 ("regras do
    professor", sempre com alerta proprio) rodam juntos sobre os MESMOS candles. Sem a secao `pos_runner` no
    config.yaml, ou com o arquivo de parametros do V0 invalido, o bot roda normalmente sem nenhum dos dois
    (avisa no console). A linhagem on-chain roda numa thread propria. Env `POS_RUNNER_SEM_V0=1` desliga o V0
    por completo (a V1 continua)."""
    raw = cfg.raw.get("pos_runner")
    if not raw:
        return None
    from .pos_runner.live import LineageVerifier, LiveSettings, PosRunnerLive
    from .pos_runner.params import load_params
    from .pos_runner.solana_rpc import SolanaRpc, endpoints_from_env, host_of

    settings = LiveSettings.from_config(raw)
    sem_v0 = bool(os.environ.get("POS_RUNNER_SEM_V0"))   # item 0 (regras inegociaveis): flag --sem-v0
    sem_v2 = bool(os.environ.get("SEM_V2"))   # PEDIDO CONSOLIDADO FASE 2: SEM_V2=1 desliga a V2 por completo
    sem_evidencia = bool(os.environ.get("SEM_EVIDENCIA"))   # PEDIDO (PARTE 1 de 2): desliga trajetoria+baseline
    sem_carteiras = bool(os.environ.get("SEM_CARTEIRAS"))   # PEDIDO 2026-10-27 (H9): desliga o snapshot de carteiras pro
    carteiras_max_chamadas_dia = int(os.environ.get("CARTEIRAS_MAX_CHAMADAS_DIA", "600"))
    sem_sombra = bool(os.environ.get("SEM_SOMBRA"))   # PEDIDO (PARTE 2A) FASE 3: desliga a sombra dos filtros
    sombra_max_pools = int(os.environ.get("SOMBRA_MAX_POOLS", "10"))
    settings = resolve_chamadas_por_ciclo(settings, raw, sem_v0)
    path = Path(settings.parametros)
    if not path.is_absolute():
        path = paths.base / path if (paths.base / path).exists() else PACKAGE_DIR / path
    try:
        params = load_params(path)
    except (OSError, ValueError, TypeError) as exc:
        console.warning("POS-RUNNER desligado: parametros invalidos em %s (%s)", path, exc)
        return None
    ctx = engine.ctx.get("solana")
    http = getattr(gt, "http", None)
    if ctx is None or http is None:
        console.warning("POS-RUNNER desligado: falta a chain solana no config.yaml (ou o cliente do GeckoTerminal)")
        return None
    chain = cfg.raw["chains"]["solana"]
    rpc = SolanaRpc(endpoints_from_env(), per_min=40, timeout_s=20, max_attempts=6)
    dexpaprika = make_dexpaprika_provider()
    live = PosRunnerLive(settings, params, storage, http, ctx, telegram, cfg.raw["links"], chain["dexscreener_slug"],
                         paths.dados / "pos_runner", rpc=rpc, sem_v0=sem_v0, terminal=chain["terminal"],
                         chain_name=chain["nome"], dexpaprika=dexpaprika, sem_v2=sem_v2, sem_evidencia=sem_evidencia,
                         sem_carteiras=sem_carteiras, carteiras_max_chamadas_dia=carteiras_max_chamadas_dia,
                         sem_sombra=sem_sombra, sombra_max_pools=sombra_max_pools)
    live.alerts_on = cfg.raw["alertas"]["ligado"]
    live.chain_capabilities = _check_fase2_capabilities(http, telegram, paths)   # FASE 6, item 3: texto de startup real
    verifier = LineageVerifier(storage, rpc)
    threading.Thread(target=verifier.run, args=(stop,), daemon=True, name="pos-runner-linhagem").start()
    dp_status = "desligado"
    if dexpaprika is not None:
        dp_status = "com chave" if os.environ.get("DEXPAPRIKA_API_KEY", "").strip() else "sem chave (keyless)"
    console.info("POS-RUNNER %s | V0 config %s (%s)%s | V1 config %s | V2 config %s%s | %s chamadas/ciclo | "
                 "RPC: %s | DexPaprika: %s",
                 "ligado" if settings.ligado else "DESLIGADO (pos_runner.ligado)",
                 params.version, live.status, " [V0 DESLIGADO: POS_RUNNER_SEM_V0]" if sem_v0 else "",
                 live.version_v1, live.version_v2, " [V2 DESLIGADA: SEM_V2]" if sem_v2 else "",
                 settings.chamadas_por_ciclo, ", ".join(host_of(u) for u in rpc.endpoints), dp_status)
    return live


def _pos_runner_chains_status_text(cfg: Config, live: Any, capabilities: dict[str, Any]) -> str:
    """PEDIDO ADICIONAL FASE 6, item 3: o que a V1 esta fazendo de verdade por chain -- "ativo" so quando
    `live.enabled()` confirma (nunca so porque `pos_runner.ligado: true` no config.yaml). BSC/Robinhood vem
    de `capabilities` (`_check_fase2_capabilities`, deteccao real 1x no startup, nunca um texto fixo):
    "so deteccao" quando a rede+OHLCV foram confirmados (decisao explicita da FASE 2, capable() continua
    False), "desligada (<motivo real>)" quando a deteccao falhou (ex.: rede ausente no GeckoTerminal)."""
    parts = [f"POS-RUNNER V1 ({live.chain_name}): {'ativo' if live.enabled() else 'desligado'}"]
    for name, cap in capabilities.items():
        nome = cfg.raw["chains"].get(name, {}).get("nome", name.upper())
        if cap is None:
            continue
        parts.append(f"{nome}: só detecção" if cap.ok else f"{nome}: desligada ({cap.motivo})")
    return " | ".join(parts)


def _startup_chains_text(engine: Engine) -> str:
    """FASE 6, item 3: corrige "chains ativas: nenhuma" quando o motor legado (V0) esta desligado
    (SEM_LEGADO, padrao com a V1 ligada) -- mostra o estado real da V1/BSC/Robinhood nesse caso, e some
    as 2 informacoes quando os dois motores estao ativos ao mesmo tempo. Sem POS-RUNNER nenhum, comportamento
    IDENTICO ao de antes desta revisao (so `engine.chains_status_text()`)."""
    parts = []
    if engine.legado_ligado:
        parts.append(engine.chains_status_text())
    if engine.pos_runner is not None:
        parts.append(_pos_runner_chains_status_text(
            engine.cfg, engine.pos_runner, getattr(engine.pos_runner, "chain_capabilities", {}) or {}))
    return " | ".join(parts) if parts else engine.chains_status_text()


def _relatorio_v1_ou_v2(pos_runner: Any, args: list[str]) -> str:
    """PEDIDO CONSOLIDADO FASE 2: "/relatorio [v1|v2]" -- padrao v1 (compatibilidade com o comando que
    ja existia). Nunca mistura as estatisticas das 2 versoes."""
    versao = args[0].lower() if args else "v1"
    if versao == "v2":
        return pos_runner.relatorio_semanal_v2()
    if versao == "v1":
        return pos_runner.relatorio_semanal_v1()
    return "uso: /relatorio [v1|v2]"


def _analise_v1_ou_v2(pos_runner: Any, args: list[str]) -> str:
    """PEDIDO (PARTE 1 de 2) FASE 2c: "/analise [v1|v2]" -- mesma convencao do /relatorio. Nunca
    mistura estatistica das 2 versoes; a recusa por amostra insuficiente/plano alterado vem do proprio
    `analise_texto` (signals_mvp/analise/condicional.py)."""
    versao = args[0].lower() if args else "v1"
    if versao not in ("v1", "v2"):
        return "uso: /analise [v1|v2]"
    return pos_runner.analise_texto(versao)


def make_dexpaprika_provider() -> Optional[Any]:
    """PEDIDO CONSOLIDADO FASE 1: `DEXPAPRIKA=0` desliga por completo (zero chamada); chave SO em
    `.env` (`DEXPAPRIKA_API_KEY`, opcional), NUNCA logada/impressa. Os outros ajustes (atraso de
    seguranca, teto de creditos, tolerancia, amostra da conferencia cruzada) tem padrao seguro e so se
    mudam por env, igual ao resto do POS-RUNNER (`POS_RUNNER_RPC_PER_MIN` etc.)."""
    if os.environ.get("DEXPAPRIKA", "1").strip() == "0":
        return None
    from .pos_runner.dexpaprika_v1 import make_provider

    api_key = os.environ.get("DEXPAPRIKA_API_KEY", "").strip() or None
    per_min = os.environ.get("DEXPAPRIKA_REQ_POR_MIN")
    return make_provider(
        api_key, habilitado=True, per_min=float(per_min) if per_min else None,
        atraso_min_s=float(os.environ.get("DEXPAPRIKA_ATRASO_MIN_S", "120")),
        creditos_teto_pct=float(os.environ.get("DEXPAPRIKA_CREDITOS_TETO_PCT", "0.8")),
        tolerancia_pct=float(os.environ.get("DEXPAPRIKA_TOLERANCIA_PCT", "1.0")),
        amostra_cada_n=int(os.environ.get("DEXPAPRIKA_AMOSTRA_CADA_N", "5")),
    )


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
        healthchecks_url = os.environ.get("HEALTHCHECKS_URL", "").strip() or None
        setup_logging(self.paths, secrets=[token, healthchecks_url], debug=bool(os.environ.get("SIGNALS_MVP_DEBUG")))
        try:
            cfg = load_config(self.paths.config)
        except ConfigError as exc:
            console.error("CONFIG INVALIDA: %s", exc)
            return EXIT_CONFIG_ERROR
        self._install_signals()

        storage = Storage(self.paths)
        heartbeat = Heartbeat(self.paths.heartbeat)
        heartbeat.beat(force=True)
        heartbeat_writer = HeartbeatWriter(heartbeat, self.stop)
        heartbeat_writer.start()
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
        engine.pos_runner = make_pos_runner(cfg, self.paths, storage, engine, gt, telegram, self.stop)
        # BUG PRIORITARIO (2026-10-22, item 3): o motor legado (new_pools/OHLCV/token info do `signals_mvp`
        # raiz) compete pelo MESMO limitador/orcamento de GT que o POS-RUNNER-V1 -- com o V1 ligado, o V1 tem
        # prioridade por padrao (SEM_LEGADO=1 implicito); `SEM_LEGADO=0` no .env religa o legado explicitamente
        # (nunca a config da V1, so este liga/desliga operacional). Sem o V1 ligado, nada muda.
        sem_legado_env = _env_bool("SEM_LEGADO")
        v1_ligado = engine.pos_runner is not None and engine.pos_runner.enabled()
        engine.legado_ligado = (not sem_legado_env) if sem_legado_env is not None else (not v1_ligado)
        if not engine.legado_ligado:
            console.info("Motor legado DESLIGADO (%s) -- orcamento de GT todo para o POS-RUNNER-V1",
                         "SEM_LEGADO" if sem_legado_env else "V1 ligado, padrao")
            for name in engine.cfg.enabled_chains():
                engine.disabled_chains.add(name)
                engine.disabled_chain_reasons[name] = "motor legado desligado (SEM_LEGADO)"
        self._config_mtime = self._mtime(self.paths.config)
        self._meta_mtime = self._mtime(meta_path(self.paths, cfg))
        if engine.legado_ligado:
            validate_networks(engine, gt, telegram)
        http = getattr(gt, "http", None)
        skew_message = clock_skew_message(http.clock_skew_s() if http is not None else None)
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
                relatorio_provider=(lambda args: _relatorio_v1_ou_v2(engine.pos_runner, args)
                                    if engine.pos_runner is not None else "POS-RUNNER desligado"),
                # PEDIDO ADICIONAL FASE 5: /abertos, /fechados [n] -- so leitura do estado ja gravado pelo POS-RUNNER.
                abertos_provider=(lambda: engine.pos_runner.abertos_texto()
                                  if engine.pos_runner is not None else "POS-RUNNER desligado"),
                fechados_provider=(lambda n: engine.pos_runner.fechados_texto(n)
                                   if engine.pos_runner is not None else "POS-RUNNER desligado"),
                # PEDIDO (PARTE 1 de 2) FASE 2c: /analise [v1|v2] -- analise condicional pre-registrada.
                analise_provider=(lambda args: _analise_v1_ou_v2(engine.pos_runner, args)
                                  if engine.pos_runner is not None else "POS-RUNNER desligado"),
            )
            try:
                telegram.get_me()
            except TelegramError as exc:
                console.warning("Telegram: getMe falhou (%s). Confira o token no .env.", exc)
            poller = TelegramPoller(telegram, handler, storage, self.stop)
            poller.start()
            self._announce_start(engine, storage, telegram)

        console.info("Bot de sinais v0 ligado | config %s | meta %s | chains %s | PAPER/somente leitura",
                     cfg.version, meta.version, _startup_chains_text(engine))
        console.info("CSVs em %s | log em %s | Ctrl+C ou 'parar' para sair", self.paths.dados, self.paths.logs / "signals_mvp.log")
        if healthchecks_url:
            console.info("Healthchecks: dead man's switch ligado (ping a cada ciclo bem sucedido)")
        healthchecks.ping(healthchecks_url, "start")

        while not self.stop_requested():
            cycle_started = time.monotonic()
            heartbeat.cycle = engine.cycle_count
            heartbeat.state = "ciclo"
            try:
                self.reload_if_changed(engine, telegram)
                stats = engine.run_cycle()
                heartbeat.mark_progress(gt_calls=stats.gt_calls)   # BUG PRIORITARIO item 2: progresso de verdade
                p50 = sorted(engine.latencies)[len(engine.latencies) // 2] if engine.latencies else None
                console.info("ciclo %d (%.0fs) | %s", engine.cycle_count, stats.duration_s, stats.line(p50))
                engine.maybe_send_daily_summary()
                try:
                    backup.maybe_run_backup(storage, self.paths.base / "backups", utc_now(),
                                            retencao_dias=float(os.environ.get("BACKUP_RETENCAO_DIAS", str(backup.RETENCAO_DIAS_PADRAO))))
                except Exception:  # noqa: BLE001 - backup e melhor-esforco, nunca derruba o ciclo
                    log.exception("falha no backup diario do banco")
                healthchecks.ping(healthchecks_url, "ok")
            except Exception:  # noqa: BLE001 - o worker nao morre por erro de ciclo
                log.exception("erro no loop principal")
                healthchecks.ping(healthchecks_url, "fail")
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
        heartbeat_writer.join(timeout=2)
        if poller is not None:
            poller.join(timeout=3)  # o long-poll pode estar no meio de uma espera; ele sai sozinho no proximo ciclo
        if engine.pos_runner is not None:
            engine.pos_runner.shutdown(utc_now())
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
        try:
            telegram.notify(f"\U0001f916 Bot de sinais ligado (PAPER). config {engine.cfg.version} | meta {engine.meta.version} | "
                           f"chains {_startup_chains_text(engine)}")
            storage.set_meta("ultimo_aviso_inicio", str(now))
        except TelegramError as exc:
            log.warning("aviso de inicio nao enviado: %s", exc)


def run_worker(paths: Paths) -> int:
    return Worker(paths).run()
