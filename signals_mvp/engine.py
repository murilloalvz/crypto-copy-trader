"""Ciclo principal: descoberta -> seguranca (corta) -> metricas -> score -> sinal -> acompanhamento -> log.

Principios:
  * relogio injetavel (`clock`) — testes simulam horas em milissegundos;
  * uma avaliacao por (pool, etiqueta): vale o PRIMEIRO instante em que o gatilho dispara;
  * toda decisao e tomada com a foto do pool (`decision_ts`); nada posterior a ela entra no score;
  * falha de API nunca derruba o ciclo: o dado fica ausente (None) e o motivo vai pro log;
  * so lemos dados publicos. Nenhuma chave, nenhuma transacao, nenhuma ordem.
"""

from __future__ import annotations

import html
import json
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Optional

from . import triggers as trg
from .alerts import AlertData, build_keyboard, delivery_variants, format_alert_text
from .config import Config
from .geckoterminal import GtClient
from .goplus import GoPlusClient
from .http import ApiError, CallBudget, RateLimited
from .metrics import compute_metrics
from .models import ChainCtx, PoolSnap, TokenInfo, TradesSummary, norm_addr
from .narrative import MetaSet, match_meta
from .scoring import score_token
from .security import SecurityResult, evaluate
from .storage import Storage
from .summary import build_summary, local_day_bounds
from .telegram import TelegramError
from .tracker import WINDOW_MIN, Plan, compute_outcome, plan_from_config
from .util import fmt_age, iso_utc, utc_now

log = logging.getLogger("signals_mvp.engine")
console = logging.getLogger("signals_mvp.console")

INFO_FLAGS = {"descricao s/d", "acel s/d", "top10 s/d"}  # dado ausente: ja aparece nos proprios campos
INFO_CACHE_S = 1800.0


@dataclass
class CycleStats:
    started: float
    discovered: int = 0
    refreshed: int = 0
    candidates: int = 0
    evaluated: int = 0
    alerts: int = 0
    discarded: int = 0
    postponed: int = 0
    followed_up: int = 0
    errors: int = 0
    throttled: int = 0          # chamadas adiadas pelo limitador LOCAL (esperado quando o IP e apertado; nao e erro)
    rate_limited: bool = False
    gt_calls: int = 0
    duration_s: float = 0.0
    etapas: Counter = field(default_factory=Counter)

    def line(self, latency_p50: Optional[float] = None) -> str:
        parts = [
            f"novos {self.discovered}",
            f"cand {self.candidates}",
            f"aval {self.evaluated}",
            f"alertas {self.alerts}",
            f"cortes {self.discarded}",
            f"acomp {self.followed_up}",
            f"GT {self.gt_calls}",
        ]
        if self.rate_limited:
            parts.append("429!")
        if self.throttled:
            parts.append(f"limitado {self.throttled}")
        if self.errors:
            parts.append(f"erros {self.errors}")
        if latency_p50 is not None:
            parts.append(f"lat p50 {latency_p50:.0f}s")
        return " | ".join(parts)


@dataclass
class Candidate:
    snap: PoolSnap
    label: str
    result: trg.TriggerResult


class Engine:
    def __init__(
        self,
        cfg: Config,
        meta: MetaSet,
        storage: Storage,
        gt: GtClient,
        goplus: GoPlusClient,
        telegram: Any = None,
        clock: Callable[[], float] = utc_now,
        heartbeat: Callable[[], None] = lambda: None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.sleep = sleep
        self.started_at = clock()
        self.disabled_chains: set[str] = set()
        self._carry: set[tuple[str, str]] = set()   # candidatos adiados: sao os primeiros do proximo ciclo
        self._attempts: dict[tuple[str, str, str], int] = {}
        self._last_prune = 0.0
        self.storage = storage
        self.gt = gt
        self.goplus = goplus
        self.tg = telegram
        self.clock = clock
        self.heartbeat = heartbeat
        self.cycle_count = 0
        self.last_stats: Optional[CycleStats] = None
        self.latencies: deque[float] = deque(maxlen=200)
        self._info_cache: dict[tuple[str, str], tuple[float, TokenInfo]] = {}
        self.cfg = cfg
        self.meta = meta
        self.ctx: dict[str, ChainCtx] = {}
        self.set_config(cfg)
        self.set_meta(meta, "")

    # ------------------------------------------------------------------ configuracao
    def set_config(self, cfg: Config) -> bool:
        """Troca a config (recarga a quente). True se a versao mudou."""
        changed = cfg.version != getattr(self.cfg, "version", None) or not self.ctx
        self.cfg = cfg
        liq_unreliable = frozenset(cfg.raw["filtros"]["dex_liquidez_nao_confiavel"])
        self.ctx = {}
        for name, chain in cfg.raw["chains"].items():
            reference = frozenset(norm_addr(chain["plataforma"], a) for a in chain["ativos_referencia"])
            self.ctx[name] = ChainCtx(name, chain["plataforma"], chain["gt_rede"], reference, liq_unreliable)
        self.storage.register_config_version(cfg.version, cfg.raw, self.clock())
        return changed

    def set_meta(self, meta: MetaSet, text: str) -> None:
        self.meta = meta
        self.storage.register_meta_version(meta.version, text, self.clock())

    @property
    def c(self) -> dict:
        return self.cfg.raw

    def gt_blocked_for(self) -> float:
        """Segundos que o GeckoTerminal ainda fica em pausa por causa de um 429 (0 = livre)."""
        limiter = getattr(getattr(self.gt, "http", None), "limiter", None)
        return 0.0 if limiter is None else limiter.blocked_for()

    def enabled_chains(self) -> dict[str, dict]:
        """Chains ligadas no config, menos as desligadas em tempo de execucao (rede inexistente no GT)."""
        return {k: v for k, v in self.cfg.enabled_chains().items() if k not in self.disabled_chains}

    # ------------------------------------------------------------------ ciclo
    def _cycle_budget(self) -> int:
        """Chamadas ao GeckoTerminal neste ciclo: o menor entre o config e o que o ritmo ATUAL do limitador sustenta
        (apos 429 o limitador reduz o ritmo e o orcamento encolhe junto)."""
        configured = self.c["gt"]["orcamento_por_ciclo"]
        limiter = getattr(getattr(self.gt, "http", None), "limiter", None)
        if limiter is None:
            return configured
        sustainable = limiter.available_within(self.c["ciclo"]["intervalo_s"])
        return max(3, min(configured, sustainable))

    def run_cycle(self) -> CycleStats:
        """Ordem de prioridade (o que ja comecou vem antes do que e novo):
        1. re-checar e enriquecer os candidatos ADIADOS no ciclo anterior;
        2. descoberta (pagina 1 de cada chain) e re-checagem dos pools jovens, mais ativos primeiro;
        3. paginas extras de descoberta com a sobra;
        4. acompanhamento (OHLCV) dos sinais vencidos.
        Reservas no orcamento garantem que descoberta/refresh nunca deixem o enriquecimento e o acompanhamento sem chamadas.
        """
        self.cycle_count += 1
        started = self.clock()
        stats = CycleStats(started=started)
        t0 = time.monotonic()
        limit = self._cycle_budget()
        budget = CallBudget(limit)
        due = len(self.storage.signals_due(started, limit=5))
        keep_follow = 1 if due else 0
        keep_early = keep_follow + min(4, limit // 3)
        seen: dict[tuple[str, str], PoolSnap] = {}
        decided: set[tuple[str, str]] = set()
        carry, self._carry = self._carry, set()
        try:
            if carry:
                self._refresh(started, budget, keep_follow, stats, seen, only=carry)
                self._decide(seen, decided, budget, keep_follow, stats)
            self._discover(budget, keep_early, stats, seen, first_pages=True)
            self._refresh(started, budget, keep_early, stats, seen)
            self._discover(budget, keep_early, stats, seen, first_pages=False)
            self._expire(self.clock(), stats)
            self._decide(seen, decided, budget, keep_follow, stats)
            self._followups(self.clock(), budget, stats)
            self._late_security(self.clock(), stats)
            self._maybe_prune(self.clock())
        except RateLimited:
            stats.rate_limited = True
        except Exception:  # noqa: BLE001 - nunca derrubar o worker por um erro de ciclo
            stats.errors += 1
            log.exception("erro inesperado no ciclo %s", self.cycle_count)
        stats.gt_calls = budget.used
        stats.duration_s = time.monotonic() - t0
        try:
            self.storage.export_csvs()
        except Exception:  # noqa: BLE001
            log.exception("falha ao exportar CSVs")
        self.last_stats = stats
        return stats

    def _decide(self, seen: dict, decided: set, budget: CallBudget, keep: int, stats: CycleStats) -> None:
        """Gatilhos + candidatos para as fotos ainda nao decididas neste ciclo."""
        fresh = {k: v for k, v in seen.items() if k not in decided}
        decided.update(fresh)
        candidates = self._evaluate_triggers(fresh, stats)
        stats.candidates += len(candidates)
        self._process_candidates(candidates, budget, keep, stats)

    # ------------------------------------------------------------------ descoberta
    def _gt(self, budget: CallBudget, stats: CycleStats, fn: Callable[..., Any], *args: Any, keep: int = 0, **kwargs: Any) -> Any:
        """Uma chamada ao GeckoTerminal sob orcamento. Devolve None se nao houve chamada ou falhou."""
        if not budget.take(1, keep=keep):
            return None
        try:
            result = fn(*args, **kwargs)
        except RateLimited:
            stats.rate_limited = True
            budget.exhaust()
            return None
        except ApiError as exc:
            if exc.kind == "budget":  # limitador local: sem ficha neste ciclo; a chain entra primeiro no proximo (rodizio)
                stats.throttled += 1
                budget.exhaust()
                return None
            stats.errors += 1
            log.warning("GeckoTerminal %s falhou: %s", getattr(fn, "__name__", "?"), exc)
            return None
        self.heartbeat()
        return result

    def _rotated(self, items: dict) -> list:
        """Rodizio: a chain que comeca muda a cada ciclo, para nenhuma passar fome quando o orcamento e curto."""
        keys = list(items)
        if not keys:
            return keys
        shift = self.cycle_count % len(keys)
        return keys[shift:] + keys[:shift]

    def _discover(self, budget: CallBudget, keep: int, stats: CycleStats, seen: dict, first_pages: bool) -> None:
        """`first_pages`: pagina 1 de cada chain. Senao: paginas 2..N (so com a sobra do orcamento)."""
        chains = self.enabled_chains()
        for chain in self._rotated(chains):
            ccfg = chains[chain]
            pages = [1] if first_pages else list(range(2, ccfg["paginas_new_pools"] + 1))
            for page in pages:
                snaps = self._gt(budget, stats, self.gt.new_pools, self.ctx[chain], page, keep=keep)
                if snaps is None:
                    break
                for snap in snaps:
                    self._ingest(snap, stats, seen)

    def _refresh(self, now: float, budget: CallBudget, keep: int, stats: CycleStats, seen: dict, only: Optional[set] = None) -> None:
        """Re-checa (em lotes de 30 por chamada) os pools com etiqueta aberta na janela. Mais ativos primeiro."""
        g = self.c["gatilhos"]
        rows = self.storage.pools_to_refresh(
            now, g["novo"]["idade_max_min"] * 60.0, g["sobrevivente20"]["idade_min_min"] * 60.0, g["sobrevivente20"]["idade_max_min"] * 60.0
        )
        wanted: dict[str, list[str]] = {}
        for row in rows:
            key = (row["chain"], row["pool"])
            if key in seen or row["chain"] not in self.enabled_chains() or (only is not None and key not in only):
                continue
            pools = wanted.setdefault(row["chain"], [])
            if row["pool"] not in pools:
                pools.append(row["pool"])
        for chain in self._rotated(wanted):
            pools = wanted[chain]
            for start in range(0, len(pools), 30):
                snaps = self._gt(budget, stats, self.gt.pools_multi, self.ctx[chain], pools[start : start + 30], keep=keep)
                if snaps is None:
                    break
                for snap in snaps:
                    if (snap.chain, snap.pool) not in seen:
                        stats.refreshed += 1
                        self._ingest(snap, stats, seen)

    def _ingest(self, snap: PoolSnap, stats: CycleStats, seen: dict) -> None:
        key = (snap.chain, snap.pool)
        if key in seen:
            return
        seen[key] = snap
        is_new = self.storage.add_pool_if_new(snap, trg.LABELS, snap.observed_ts)
        if not is_new:
            self.storage.touch_pool(snap.chain, snap.pool, snap.vol.get("m5"), snap.observed_ts)
            return
        stats.discovered += 1
        reason = None
        if snap.both_reference:
            reason = "par de ativos de referencia (sem memecoin)"
        elif snap.dex in set(self.c["filtros"]["dex_ignorar"]):
            reason = f"dex ignorada ({snap.dex})"
        elif snap.created_ts is None:
            reason = "sem data de criacao do pool"
        if reason:
            self._discard_pool(snap, "filtro", reason, "", None)
            stats.discarded += 1
            stats.etapas["filtro"] += 1

    # ------------------------------------------------------------------ descartes / expiracao
    def _discard_pool(self, snap: PoolSnap, etapa: str, motivo: str, valor: str, label: Optional[str]) -> None:
        """Descarta o pool (todas as etiquetas abertas, ou so `label`) e loga UMA linha."""
        now = self.clock()
        labels = [label] if label else self.storage.open_labels(snap.chain, snap.pool)
        self.storage.add_discard(now, snap.chain, snap.symbol, snap.token, etapa, motivo, valor, self.cfg.version, snap.pool, label or "")
        for item in labels:
            self.storage.finalize_label(snap.chain, snap.pool, item, "descartado", now)

    def _expire(self, now: float, stats: CycleStats) -> None:
        g = self.c["gatilhos"]
        for row in self.storage.expired_labels(now, g["novo"]["idade_max_min"] * 60.0, g["sobrevivente20"]["idade_max_min"] * 60.0):
            seen_before = row["last_etapa"] is not None
            if row["etiqueta"] == trg.NOVO or seen_before:
                etapa = row["last_etapa"] or "filtro"
                motivo = f"expirou ({row['etiqueta']}): {row['last_motivo'] or 'nunca avaliado'}"
                self.storage.add_discard(now, row["chain"], row["symbol"], row["token"], etapa, motivo, row["last_valor"] or "", self.cfg.version, row["pool"], row["etiqueta"])
                stats.discarded += 1
                stats.etapas[etapa] += 1
            self.storage.finalize_label(row["chain"], row["pool"], row["etiqueta"], "expirado", now)

    # ------------------------------------------------------------------ gatilhos
    def _evaluate_triggers(self, seen: dict, stats: CycleStats) -> list[Candidate]:
        g = self.c["gatilhos"]
        novo_max = g["novo"]["idade_max_min"] * 60.0
        s_min, s_max = g["sobrevivente20"]["idade_min_min"] * 60.0, g["sobrevivente20"]["idade_max_min"] * 60.0
        out: list[Candidate] = []
        for snap in seen.values():
            open_labels = self.storage.open_labels(snap.chain, snap.pool)
            age = snap.age_s()
            if not open_labels or age is None or snap.chain not in self.enabled_chains():
                continue
            min_liq = self.c["chains"][snap.chain]["liquidez_min_usd"]
            for label in open_labels:
                if label == trg.NOVO and age <= novo_max:
                    result = trg.check_novo(snap, self.c["filtros"], g["novo"], min_liq)
                elif label == trg.SOBREVIVENTE20 and s_min <= age <= s_max:
                    pool_row = self.storage.get_pool(snap.chain, snap.pool)
                    result = trg.check_sobrevivente20(
                        snap, self.c["filtros"], g["sobrevivente20"], min_liq,
                        None if pool_row is None else pool_row["first_price"],
                        None if pool_row is None else pool_row["first_seen_age_s"],
                    )
                else:
                    continue
                if result.fired:
                    out.append(Candidate(snap, label, result))
                else:
                    self.storage.note_label(snap.chain, snap.pool, label, result.etapa, result.reason_text, self._etapa_value(result.etapa, snap))
        out.sort(key=lambda cand: cand.snap.vol_window("m5") or 0.0, reverse=True)
        return out

    @staticmethod
    def _etapa_value(etapa: str, snap: PoolSnap) -> str:
        if etapa == "liquidez_minima":
            return "" if snap.liq_usd is None else f"{snap.liq_usd:.0f}"
        if etapa == "filtro":
            return "" if snap.mc_usd is None else f"{snap.mc_usd:.0f}"
        vol = snap.vol_window("m5")
        return "" if vol is None else f"vol_m5={vol:.0f}"

    # ------------------------------------------------------------------ candidatos
    MAX_TRANSIENT_ATTEMPTS = 3

    def _postpone(self, snap: PoolSnap, label: str, why: str, stats: CycleStats) -> None:
        """Candidato que disparou o gatilho mas nao pode ser avaliado AGORA (orcamento/API): fica aberto, vira o
        primeiro do proximo ciclo e, se expirar assim, o descartados.csv diz exatamente isso (nao 'nunca avaliado')."""
        stats.postponed += 1
        self._carry.add((snap.chain, snap.pool))
        self.storage.note_label(snap.chain, snap.pool, label, "adiado", f"gatilho disparou mas nao foi avaliado: {why}", "")

    def _token_info(self, cand: Candidate, budget: CallBudget, reserve: int, stats: CycleStats) -> tuple[Optional[TokenInfo], bool]:
        """(info, pulado_por_orcamento). Cache em memoria por 30 min."""
        key = (cand.snap.chain, cand.snap.token)
        cached = self._info_cache.get(key)
        now = self.clock()
        if cached and now - cached[0] < INFO_CACHE_S:
            return cached[1], False
        if not budget.take(1, keep=reserve):
            return None, True
        try:
            info = self.gt.token_info(self.ctx[cand.snap.chain], cand.snap.token)
        except RateLimited:
            stats.rate_limited = True
            budget.exhaust()
            return None, True
        except ApiError as exc:
            if exc.kind == "budget":  # limitador LOCAL sem ficha: nao e falha do token — tenta no proximo ciclo
                return None, True
            stats.errors += 1
            log.warning("token info falhou (%s): %s", cand.snap.symbol, exc)
            return None, False
        self.heartbeat()
        self._info_cache[key] = (now, info)
        return info, False

    def _query_goplus(self, candidates: list[Candidate]) -> dict[tuple[str, str], tuple[Optional[dict], Optional[ApiError]]]:
        """(chain, token) -> (registro ou None, erro da chamada ou None). Pula quem ja tem veredito em cache.

        Token ausente do resultado = nao foi consultado neste ciclo (limite por consulta).
        """
        out: dict[tuple[str, str], tuple[Optional[dict], Optional[ApiError]]] = {}
        cache_s = self.c["seguranca"]["cache_min"] * 60.0
        per_chain: dict[str, list[str]] = {}
        cap = self.c["goplus"]["lote_max"] * 2
        for cand in candidates:
            key = (cand.snap.chain, cand.snap.token)
            if key in out or self.storage.cached_security(cand.snap.chain, cand.snap.token, self.clock(), cache_s) is not None:
                continue
            tokens = per_chain.setdefault(cand.snap.chain, [])
            if len(tokens) < cap and cand.snap.token not in tokens:
                tokens.append(cand.snap.token)
        for chain, tokens in per_chain.items():
            ccfg = self.c["chains"][chain]
            results, error = self.goplus.security(ccfg["plataforma"], ccfg["goplus_id"], tokens)
            self.heartbeat()
            for token in tokens:
                out[(chain, token)] = (results[token], None) if token in results else (None, error)
        return out

    def _process_candidates(self, candidates: list[Candidate], budget: CallBudget, reserve: int, stats: CycleStats) -> None:
        if not candidates:
            return
        raw = self._query_goplus(candidates)
        for cand in candidates:
            try:
                self._process_candidate(cand, raw, budget, reserve, stats)
            except RateLimited:
                stats.rate_limited = True
                budget.exhaust()
            except Exception:  # noqa: BLE001 - um token ruim nao derruba os outros
                stats.errors += 1
                log.exception("erro ao avaliar %s %s", cand.snap.chain, cand.snap.symbol)

    def _process_candidate(self, cand: Candidate, raw: dict, budget: CallBudget, reserve: int, stats: CycleStats) -> None:  # noqa: C901
        snap, label = cand.snap, cand.label
        cfg = self.c
        ccfg = cfg["chains"][snap.chain]
        platform = ccfg["plataforma"]
        decision_ts = snap.observed_ts

        # duplicata: mesmo token, mesma DEX, mesma etiqueta (ex.: clones em varias faixas de taxa)
        if self.storage.token_dex_label_exists(snap.chain, snap.token, snap.dex, label):
            self._discard_pool(snap, "duplicado", "token ja avaliado nesta DEX com a mesma etiqueta", "", label)
            stats.discarded += 1
            stats.etapas["duplicado"] += 1
            return

        # seguranca: cache -> senao registro cru da GoPlus
        cache_s = cfg["seguranca"]["cache_min"] * 60.0
        cached = self.storage.cached_security(snap.chain, snap.token, self.clock(), cache_s)
        record, goplus_error = (None, None)
        if cached is None:
            if (snap.chain, snap.token) not in raw:
                self._postpone(snap, label, "nao coube na consulta de seguranca deste ciclo", stats)
                return
            record, goplus_error = raw[(snap.chain, snap.token)]
            if goplus_error is not None:
                # throttling LOCAL (limitador/429) nao e propriedade do token: espera. Outros erros (timeout...) ganham poucas tentativas.
                key = (snap.chain, snap.pool, label)
                self._attempts[key] = self._attempts.get(key, 0) + 1
                if goplus_error.kind in ("budget", "rate_limited") or self._attempts[key] < self.MAX_TRANSIENT_ATTEMPTS:
                    self._postpone(snap, label, f"GoPlus indisponivel ({goplus_error.kind})", stats)
                    return

        # token info (descricao + fallback de mint/freeze na Solana)
        solana_fallback = platform == "solana" and cfg["seguranca"]["solana"]["usar_gt_para_mint_freeze"] and cached is None and record is None
        need_info = cfg["narrativa"]["buscar_descricao"] or solana_fallback
        info, info_skipped = (None, False)
        if need_info:
            info, info_skipped = self._token_info(cand, budget, reserve, stats)
        if info_skipped:
            self._postpone(snap, label, "sem chamadas disponiveis para enriquecer (token info)", stats)
            return

        if cached is not None:
            sec = SecurityResult.from_dict(cached)
        else:
            sec = evaluate(platform, record, snap, cfg["seguranca"], info, goplus_error)
            if sec.status in ("ok", "falhou"):
                self.storage.cache_security(snap.chain, snap.token, self.clock(), sec.status, sec.to_dict())

        if sec.status == "falhou":
            self._discard_pool(snap, "seguranca", sec.failure_reason(), "", label)
            stats.discarded += 1
            stats.etapas["seguranca"] += 1
            return
        if sec.status in ("sem_dado", "parcial") and self.cfg.sem_dado_acao(snap.chain) == "descartar":
            missing = ", ".join(c.name for c in sec.nodata() if c.name in ("honeypot", "taxas", "open_source", "lp", "top10", "mint_authority", "freeze_authority"))
            self._discard_pool(snap, "seguranca", f"{sec.status}: {missing or 'sem dado'} (modo estrito)", "", label)
            stats.discarded += 1
            stats.etapas["seguranca"] += 1
            return

        # valor de compras/vendas (opcional, melhor esforco)
        trades: Optional[TradesSummary] = None
        if cfg["enriquecimento"]["buscar_trades"] and budget.take(1, keep=reserve):
            try:
                trades = self.gt.trades(self.ctx[snap.chain], snap.pool, snap.token, decision_ts, 300.0)
                self.heartbeat()
            except RateLimited:
                stats.rate_limited = True
                budget.exhaust()
            except ApiError as exc:
                if exc.kind != "budget":  # sem ficha local: o valor de trades e opcional, segue sem ele
                    stats.errors += 1
                    log.warning("trades falhou (%s): %s", snap.symbol, exc)

        plan = plan_from_config(cfg["plano"], ccfg["fee_rede_usd"])
        metrics = compute_metrics(snap, plan.posicao_usd, trades)
        description = (info.description if info and info.description else sec.description) or ""
        name = snap.token_name or (info.name if info else "")
        match = match_meta(self.meta, name, snap.symbol, description, cfg["narrativa"]["substring_min_len"])
        scored = score_token(metrics, match, sec.top10_pct, sec.status, cfg["score"], cfg["seguranca"]["top10_max_pct"])

        features = {
            "gatilho": cand.result.reasons,
            "metricas": metrics.to_dict(),
            "score_partes": scored.parts,
            "flags": scored.flags,
            "narrativa": {"nome_ticker": match.name_hits, "descricao": match.desc_hits, "descricao_conhecida": match.description_known},
            "pool": {
                "dex": snap.dex, "nome": snap.name, "vol": snap.vol, "price_change": snap.price_change,
                "tx": {w: [t.buys, t.sells, t.buyers, t.sellers] for w, t in snap.tx.items()},
                "locked_liq_pct": snap.locked_liq_pct, "launchpad": snap.launchpad, "fee_pct": snap.fee_pct,
                "target_side": snap.target_side, "mcap_usd": snap.mcap_usd, "fdv_usd": snap.fdv_usd,
            },
            "token_info": None if info is None else {
                "mint": info.mint_authority, "freeze": info.freeze_authority, "honeypot": info.is_honeypot,
                "holders": info.holders_count, "top10_gt_inclui_pool": info.top10_pct_gt, "dev_pct": info.dev_holding_pct,
                "gt_score": info.gt_score,
            },
            "trades": None if trades is None else {
                "n": trades.n_trades, "compra_usd": trades.buy_usd, "venda_usd": trades.sell_usd,
                "carteiras_compra": trades.unique_buy_wallets, "carteiras_venda": trades.unique_sell_wallets,
                "completa": trades.complete, "coberto_s": trades.covered_s,
            },
        }
        decided_at = self.clock()
        row = {
            "chain": snap.chain, "pool": snap.pool, "token": snap.token, "symbol": snap.symbol, "token_name": name,
            "etiqueta": label, "dex": snap.dex, "decision_ts": decision_ts, "created_ts": snap.created_ts,
            "score": scored.total, "componentes": scored.components_text, "entry_price": snap.price_usd,
            "mc": metrics.mc, "liq": metrics.liq, "vol_m5": metrics.vol_m5, "acel_vol": metrics.acel,
            "compras": metrics.buys, "vendas": metrics.sells, "top10": sec.top10_pct, "seguranca": sec.status,
            "seguranca_json": json.dumps(sec.to_dict(), ensure_ascii=False), "narrativa": match.label_text,
            "enviado": 0, "latencia_s": None if snap.created_ts is None else decided_at - snap.created_ts,
            "versao_config": self.cfg.version, "versao_meta": self.meta.version,
            "plano_json": json.dumps(plan.to_dict()), "features_json": json.dumps(features, ensure_ascii=False, default=str),
            "fin_proxima_ts": decision_ts + WINDOW_MIN * 60.0 + cfg["acompanhamento"]["espera_pos_janela_s"],
        }
        signal_id = self.storage.insert_signal(row)
        self.storage.finalize_label(snap.chain, snap.pool, label, "avaliado", decided_at)
        if signal_id is None:
            return
        stats.evaluated += 1

        # alerta
        reason = self._maybe_alert(signal_id, snap, label, scored, metrics, sec, match, plan, decision_ts, stats)
        if reason:
            self.storage.update_signal(signal_id, motivo_nao_enviado=reason)

    # ------------------------------------------------------------------ alerta
    def _maybe_alert(self, signal_id: int, snap: PoolSnap, label: str, scored: Any, metrics: Any, sec: SecurityResult,
                     match: Any, plan: Plan, decision_ts: float, stats: CycleStats) -> Optional[str]:
        cfg = self.c
        if scored.total < cfg["score"]["minimo_alerta"]:
            return "abaixo_do_minimo"
        if not cfg["alertas"]["ligado"] or self.tg is None:
            return "alertas_desligados"
        waited = self.clock() - decision_ts
        if waited > cfg["alertas"]["max_atraso_s"]:
            return f"atraso_{waited:.0f}s"
        ccfg = cfg["chains"][snap.chain]
        latency = None if snap.created_ts is None else self.clock() - snap.created_ts
        data = AlertData(
            signal_id=signal_id, chain_key=snap.chain, chain_name=ccfg["nome"], terminal=ccfg["terminal"], symbol=snap.symbol,
            token=snap.token, pool=snap.pool, etiqueta=label, score=scored.total, mc=metrics.mc, age_s=metrics.age_s,
            narrative_labels=match.label_text, vol_m5=metrics.vol_m5, acel=metrics.acel, buys=metrics.buys, sells=metrics.sells,
            buy_usd=metrics.buy_usd, sell_usd=metrics.sell_usd, trades_partial=metrics.trades_complete is False, liq=metrics.liq,
            top10=sec.top10_pct, security_status=sec.status, security_via_gt=any(c.source == "gt" and c.status == "ok" for c in sec.checks),
            alerts=list(sec.warnings) + [f for f in scored.flags if f not in INFO_FLAGS], latency_s=latency,
            gmgn_slug=ccfg["gmgn_slug"], dexscreener_slug=ccfg["dexscreener_slug"],
        )
        text = format_alert_text(data, plan.to_dict(), cfg["score"]["verde_min"])
        keyboard = build_keyboard(data, cfg["links"], cfg["alertas"]["botoes"])
        message_id, last_error = self._deliver(text, keyboard)
        if message_id is not None:
            alert_ts = self.clock()
            real_latency = None if snap.created_ts is None else alert_ts - snap.created_ts
            self.storage.update_signal(signal_id, enviado=1, alert_ts=alert_ts, tg_message_id=message_id, latencia_s=real_latency)
            stats.alerts += 1
            if real_latency is not None:
                self.latencies.append(real_latency)
            console.info("ALERTA %s %s $%s score %.0f (lat %s)", ccfg["nome"], label, snap.symbol, scored.total, fmt_age(real_latency))
            return None
        log.error("falha ao enviar alerta do sinal %s: %s", signal_id, last_error)
        return f"falha_telegram: {last_error[:80]}"

    def _deliver(self, text: str, keyboard: dict) -> tuple[Optional[int], str]:
        """Envia o alerta. Telegram 400 (ex.: link de botao invalido, entidade HTML) => tenta uma variante mais simples,
        para o alerta NUNCA deixar de sair por causa de enfeite. Erro de rede/429/5xx: 1 nova tentativa e desiste."""
        last_error = ""
        for variant_text, variant_keyboard, parse_mode in delivery_variants(text, keyboard):
            bad_request = False
            for attempt in range(2):
                try:
                    return self.tg.send_message(variant_text, variant_keyboard, parse_mode=parse_mode), ""
                except TelegramError as exc:
                    last_error = str(exc)
                    if exc.status == 400:
                        bad_request = True
                        log.warning("Telegram recusou o alerta (%s); tentando uma variante mais simples", exc)
                        break
                    if attempt == 0:
                        self.sleep(min(2.0, exc.retry_after or 1.0))
            if not bad_request:
                break
        return None, last_error

    # ------------------------------------------------------------------ acompanhamento
    def _followups(self, now: float, budget: CallBudget, stats: CycleStats) -> None:
        limit_s = self.c["acompanhamento"]["desistir_apos_min"] * 60.0
        for row in self.storage.signals_due(now, limit=30):
            if not budget.take(1):
                break
            pool_row = self.storage.get_pool(row["chain"], row["pool"])
            side = pool_row["target_side"] if pool_row else "base"
            ctx = self.ctx.get(row["chain"])
            if ctx is None:  # chain removida do config
                continue
            try:
                candles = self.gt.ohlcv(ctx, row["pool"], side, row["decision_ts"] - 300.0, row["decision_ts"] + (WINDOW_MIN + 1) * 60.0)
                self.heartbeat()
            except RateLimited:
                stats.rate_limited = True
                budget.exhaust()
                break
            except ApiError as exc:
                if exc.kind == "budget":  # limitador local: tenta de novo no proximo ciclo, sem contar tentativa
                    break
                stats.errors += 1
                log.warning("OHLCV falhou (%s): %s", row["symbol"], exc)
                self._followup_retry(row, now, limit_s)
                continue
            plan = Plan.from_dict(json.loads(row["plano_json"]))
            outcome = compute_outcome(candles, row["entry_price"], row["mc"], row["decision_ts"], plan)
            if outcome.tp1_antes_sl == "sem_dado":
                self._followup_retry(row, now, limit_s)
                continue
            self.storage.update_signal(
                row["id"], status="finalizado", mc_5m=outcome.mc_5m, mc_15m=outcome.mc_15m, mc_1h=outcome.mc_1h,
                max_mc=outcome.max_mc, min_mc=outcome.min_mc, tp1_antes_sl=outcome.tp1_antes_sl,
                resultado_liq=outcome.resultado_liq_pct, finalizado_ts=now, fin_proxima_ts=None,
                outcome_json=json.dumps(outcome.detail, ensure_ascii=False, default=str),
            )
            stats.followed_up += 1

    def _followup_retry(self, row: Any, now: float, limit_s: float) -> None:
        attempts = row["fin_tentativas"] + 1
        if now - row["decision_ts"] > limit_s:
            self.storage.update_signal(
                row["id"], status="sem_dado", tp1_antes_sl="sem_dado", finalizado_ts=now, fin_proxima_ts=None, fin_tentativas=attempts
            )
            return
        wait = min(900.0, 60.0 * (2 ** min(attempts, 4)))
        self.storage.update_signal(row["id"], fin_tentativas=attempts, fin_proxima_ts=now + wait)

    # ------------------------------------------------------------------ recheck tardio da seguranca
    def _late_security(self, now: float, stats: CycleStats) -> None:
        """Re-consulta a GoPlus (1x) dos sinais que sairam sem verificacao completa, depois do acompanhamento.

        Serve para MEDIR se a populacao 'sem dado' era perigosa. Nao altera o score nem o `seguranca`
        da hora da decisao (isso seria olhar o futuro); o resultado fica em `seguranca_tardia`.
        """
        if not self.c["seguranca"]["recheck_tardio"]:
            return
        rows = self.storage.signals_needing_late_security(40)
        by_chain: dict[str, list[Any]] = {}
        for row in rows:
            if row["chain"] in self.enabled_chains():
                by_chain.setdefault(row["chain"], []).append(row)
        for chain, items in by_chain.items():
            ccfg = self.c["chains"][chain]
            tokens = list(dict.fromkeys(r["token"] for r in items))[: self.c["goplus"]["lote_max"]]
            results, error = self.goplus.security(ccfg["plataforma"], ccfg["goplus_id"], tokens)
            if error is not None and not results:
                continue
            for row in items:
                if row["token"] not in results:
                    continue
                stand_in = SimpleNamespace(pool=row["pool"], dex=row["dex"])
                late = evaluate(ccfg["plataforma"], results[row["token"]], stand_in, self.c["seguranca"])  # type: ignore[arg-type]
                payload = {"status": late.status, "motivo": late.failure_reason(), "top10": late.top10_pct, "ts": iso_utc(now)}
                self.storage.update_signal(row["id"], seguranca_tardia=json.dumps(payload, ensure_ascii=False))

    def _maybe_prune(self, now: float) -> None:
        """1x por hora apaga do banco o que ja nao serve (pools antigos sem sinal, cache velho)."""
        if now - self._last_prune < 3600:
            return
        self._last_prune = now
        removed = self.storage.prune(now, keep_days=3)
        if removed:
            log.info("poda do banco: %s", removed)
        if len(self._attempts) > 5000:  # so importam dentro da janela de 10-25 min do pool
            self._attempts.clear()
        self._info_cache = {k: v for k, v in self._info_cache.items() if now - v[0] < INFO_CACHE_S}

    # ------------------------------------------------------------------ resumo / status
    def build_daily_summary(self, now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        start, end = local_day_bounds(now)
        names = {k: v["nome"] for k, v in self.c["chains"].items()}
        title = datetime.fromtimestamp(now).strftime("%d/%m/%Y")
        return build_summary(self.storage, start, min(end, now + 1), names, title)

    def maybe_send_daily_summary(self, now: Optional[float] = None) -> bool:
        cfg = self.c["resumo_diario"]
        if not cfg["ligado"] or self.tg is None:
            return False
        now = self.clock() if now is None else now
        local = datetime.fromtimestamp(now)
        hh, mm = (int(x) for x in cfg["hora_local"].split(":"))
        today = local.strftime("%Y-%m-%d")
        if (local.hour, local.minute) < (hh, mm) or self.storage.get_meta("ultimo_resumo") == today:
            return False
        start, _ = local_day_bounds(now)
        has_data = bool(self.storage.signals_between(start, now + 1) or self.storage.discards_between(start, now + 1))
        if not has_data and now - self.started_at < 1800:
            return False  # recem-ligado e sem nada hoje: nao manda resumo vazio
        try:
            self.tg.send_message(html.escape(self.build_daily_summary(now), quote=False))
        except TelegramError as exc:
            log.warning("falha ao enviar o resumo diario: %s", exc)
            return False
        self.storage.set_meta("ultimo_resumo", today)
        return True

    def status_text(self) -> str:
        counts = self.storage.counts()
        stats = self.last_stats
        p50 = sorted(self.latencies)[len(self.latencies) // 2] if self.latencies else None
        chains = ", ".join(f"{c['nome']}" for c in self.enabled_chains().values())
        lines = [
            f"Bot de sinais v0 | config {self.cfg.version} | meta {self.meta.version}",
            f"Chains: {chains}",
            f"Ciclos: {self.cycle_count}" + (f" | ultimo: {stats.line(p50)}" if stats else ""),
            f"Pools vistos {counts['pools']} | sinais {counts['sinais']} (enviados {counts['enviados']}) | acompanhando {counts['acompanhando']} | cortes {counts['descartados']}",
        ]
        if p50 is not None:
            lines.append(f"Latencia evento->alerta p50: {fmt_age(p50)} (n={len(self.latencies)})")
        return "\n".join(lines)
