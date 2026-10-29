"""POS-RUNNER-V0 ao vivo no bot (Parte B): o MESMO detector, simulador, custos e conversao para USD do backtest.

A cada ciclo do bot, dentro de uma fatia reservada do orcamento de chamadas do GeckoTerminal:
  1. descoberta: pools de graduacao (PumpSwap, Raydium CPMM, Meteora DAMM v2) com MC >= piso do runner, vindos das
     listas do GT (trending e top por volume de cada DEX) e das fotos de pools novos que o bot v0 ja busca;
  2. linhagem on-chain (RPC, numa thread propria): o pool tem de ter nascido da instrucao de migracao do launchpad
     da sua DEX, com o mesmo mint e o mesmo pool (metodo da enumeracao da Parte A). Sem isso nao entra (falha fechada).
     Na mesma thread sai a data de CRIACAO do token (a idade do sinal e contada dela): sem ela o pool tambem nao entra;
  3. candles 5m/1h/4h em token de cotacao x cotacao/USD (igual a Parte A), consumidos so depois de FECHADOS (+ folga de
     indexacao do GT) e CONGELADOS no banco: o detector ve cada candle uma vez, em ordem; reiniciar o bot refaz o mesmo
     estado a partir dos candles congelados (nada e reescrito com dado posterior);
  4. alertas: 👀 zona madura (fase 2 com S, R e teste de suporte), 🟢 entrada com mini-grafico, 🔴 invalidado,
     ⚪ nao entrar (candle absurdo), 🟡 saida sugerida (pernas do paper) e 📊 resultado do paper;
  5. paper A/B de TODA entrada decidida com a config em uso (custo 1x e 2x) e linha de base pareada (mesma idade desde
     a criacao, mesmo colchete), nos CSVs `pos_runner.csv` (colunas do handoff) e `pos_runner_detalhe.csv`. Decisao
     anterior ao 1o ciclo de uma `versao_config` (refeita a partir dos candles congelados) nunca vira sinal dela, e o
     paper aberto de outra versao vira `descontinuado`.
Somente leitura: nenhuma chave, nenhuma assinatura, nenhuma ordem.
"""

from __future__ import annotations

import html
import json
import logging
import os
import random
import re
import threading
import time
import dataclasses
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..alerts import delivery_variants
from ..geckoterminal import INCLUDE, parse_iso, parse_pools_response
from ..http import ApiError, CallBudget, RateLimited
from ..models import ChainCtx, PoolSnap
from ..telegram import TelegramError
from ..util import clean_text, fmt_usd, iso_utc, to_float, utc_now
from . import carteiras_pro, charts, telegram_v1
from .bankroll import BankrollLedger, BankrollParams, BankrollState
from .bankroll_v1 import BankrollLedgerV1, tamanho_posicao_usd
from .brt import dia_semana_brt, hora_brt, na_janela_ouro
from .candles import Bar, OhlcvStore, fill_gaps, tf_seconds
from .chain_adapter import HolderCheck, SolanaAdapter
from .costs import CostModel
from .detector import PHASE_PULLBACK, PHASE_RUNNER, Detector, Event
from .detector_v1 import DetectorV1, EventV1
from .dexpaprika_v1 import DexPaprikaProvider
from .evidencia import N_CONTROLES_MINIMO, calcular_trajetoria, candidatos_elegiveis, simular_controle, sortear_controles
from .enumerate import LAUNCHPADS as MIGRATIONS, resolve_graduation
from .lineage import creation_time
from .params import Params, is_preregistered
from .params_v1 import load_params_v1
from .params_v2 import load_params_v2
from .parte_a.baseline import K_BASELINE, runner_by_age
from .parte_a.pipeline import DEX_OF_LAUNCHPAD
from .parte_a.quotebook import QuoteBook
from . import qualidade_candle
from .qualidade_v1 import avaliar_qualidade
from .quotes import SOL_MINT, STABLES, UsdSeries, stable_series, to_mc_bars
from .simulate import TradeResult, simulate
from .simulate_v1 import TradeResultV1, simulate_v1
from .solana_rpc import SIGNATURES_PAGE_SIZE, RpcError, anchor_at_or_after

log = logging.getLogger("signals_mvp.pos_runner.live")
console = logging.getLogger("signals_mvp.console")

TFS = ("5m", "1h", "4h")
LAG_S = 90.0                 # folga depois do fechamento do candle para o GT indexar as ultimas trades
QUOTE_REFRESH_S = 900.0      # cotacao/USD (1h) renovada no maximo a cada 15 min
# PEDIDO (PARTE 2A) FASE 4: "mao de US$10" citada no pedido -- modelo PROPRIO/simples de slippage
# estimado (impacto linear de uma mao fixa contra a liquidez do pool, `mao_usd / liquidez_usd`),
# NUNCA o modelo oficial de custo (`CostModel`, intocado) -- so diagnostico/analise futura.
MAO_SIMULADA_USD = 10.0
LINEAGE_MARGIN_S = 600       # janela da linhagem: +-10 min em volta da criacao informada pelo GT
VERIFY_MAX_ATTEMPTS = 8      # falha de RPC repetida (espera 4, 8, 16, 30 min...): o pool sai (nunca entra sem linhagem)
CREATION_MAX_PAGES = 100     # data de criacao: ate 100 mil assinaturas do mint antes da migracao (o SOLCAT teve ~10 mil)
QUEUE_MAX = 60               # pools pendentes/verificados esperando vaga
# listas do GeckoTerminal usadas na descoberta ("novos e top pools Solana" do handoff)
SOURCES: dict[str, tuple[str, dict[str, Any]]] = {
    "trending": ("networks/solana/trending_pools", {"page": 1, "include": INCLUDE}),
    "pumpswap": ("networks/solana/dexes/pumpswap/pools", {"page": 1, "sort": "h24_volume_usd_desc", "include": INCLUDE}),
    "meteora-damm-v2": ("networks/solana/dexes/meteora-damm-v2/pools", {"page": 1, "sort": "h24_volume_usd_desc", "include": INCLUDE}),
    "raydium": ("networks/solana/dexes/raydium/pools", {"page": 1, "sort": "h24_volume_usd_desc", "include": INCLUDE}),
}
# DEX (id do GeckoTerminal) onde nasce o pool de graduacao de cada launchpad; a linhagem on-chain confirma
GRAD_DEX = {"pumpswap": "pumpfun", "raydium": "raydium_launchlab", "meteora-damm-v2": "meteora_dbc"}
LAUNCHPAD_NAME = {"pumpfun": "pump.fun", "raydium_launchlab": "Raydium LaunchLab", "meteora_dbc": "Meteora DBC"}
PREREG = Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v0-preregistration-DRAFT-2026-10-15.md"


# ---------------------------------------------------------------------------
# configuracao (secao `pos_runner` do config.yaml)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveSettings:
    ligado: bool = False
    parametros: str = "pos_runner/pos_runner_v0.yaml"
    timeframes: tuple[str, ...] = TFS
    max_pools: int = 15
    chamadas_por_ciclo: int = 3
    descoberta_min: float = 3.0
    fontes: tuple[str, ...] = tuple(SOURCES)
    mc_max_usd: float = 50_000_000.0
    idade_max_dias: float = 14.0
    alerta_watchlist: bool = True
    alerta_entrada: bool = True
    alerta_invalidado: bool = True
    alerta_saida: bool = True
    so_primario: bool = True
    grafico: bool = True

    @classmethod
    def from_config(cls, raw: Optional[dict]) -> "LiveSettings":
        """Sem a secao no config.yaml o POS-RUNNER fica desligado (a validacao do formato e do config.py)."""
        if not raw:
            return cls()
        alerts = raw.get("alertas") or {}
        d = cls()
        return cls(
            ligado=bool(raw.get("ligado", d.ligado)),
            parametros=str(raw.get("parametros", d.parametros)),
            timeframes=tuple(tf for tf in TFS if tf in (raw.get("timeframes") or d.timeframes)),
            max_pools=int(raw.get("max_pools", d.max_pools)),
            chamadas_por_ciclo=int(raw.get("chamadas_por_ciclo", d.chamadas_por_ciclo)),
            descoberta_min=float(raw.get("descoberta_min", d.descoberta_min)),
            fontes=tuple(raw.get("fontes", d.fontes)),
            mc_max_usd=float(raw.get("mc_max_usd", d.mc_max_usd)),
            idade_max_dias=float(raw.get("idade_max_dias", d.idade_max_dias)),
            alerta_watchlist=bool(alerts.get("watchlist", d.alerta_watchlist)),
            alerta_entrada=bool(alerts.get("entrada", d.alerta_entrada)),
            alerta_invalidado=bool(alerts.get("invalidado", d.alerta_invalidado)),
            alerta_saida=bool(alerts.get("saida", d.alerta_saida)),
            so_primario=bool(alerts.get("so_primario", d.so_primario)),
            grafico=bool(raw.get("grafico", d.grafico)),
        )


def config_status(version: str, prereg: Path = PREREG) -> str:
    """'pre-registrada' se o pre-registro esta congelado com este hash; senao 'rascunho' (aparece nos alertas)."""
    try:
        text = prereg.read_text(encoding="utf-8")
    except OSError:
        return "rascunho"
    return "pre-registrada" if is_preregistered(text, version) else "rascunho"


# ---------------------------------------------------------------------------
# linhagem on-chain (RPC)
# ---------------------------------------------------------------------------


@dataclass
class Lineage:
    status: str                       # ok | rejeitado | erro (erro = tenta de novo depois)
    motivo: str = ""
    launchpad: Optional[str] = None
    grad_ts: Optional[float] = None
    quote: Optional[str] = None
    supply: Optional[float] = None
    signature: Optional[str] = None
    instruction: Optional[str] = None


def verify_lineage(rpc: Any, pool: str, mint: str, created_ts: float, launchpad: Optional[str],
                   anchor_fn: Callable[..., Any] = anchor_at_or_after, margin_s: int = LINEAGE_MARGIN_S,
                   max_fetch: int = 12, max_pages: int = 20) -> Lineage:
    """O pool tem de ter nascido de uma instrucao de migracao do launchpad da sua DEX, para ESTE mint — o mesmo criterio
    da enumeracao da Parte A (`resolve_graduation` sobre as transacoes da conta-chave do launchpad), numa janela de
    +-`margin_s` em volta da criacao informada pelo GT. As transacoes da janela sao abertas da mais proxima da criacao
    para a mais distante (a migracao e o proprio instante da criacao): em geral 1 ou 2 `getTransaction`, que e o metodo
    mais limitado do RPC publico. Nunca pagina o historico do pool: pool quente tem centenas de transacoes por segundo
    (medido em 2026-10-16: ~500/s no DOPE logo depois da graduacao)."""
    spec = MIGRATIONS.get(launchpad or "")
    if spec is None:
        return Lineage("rejeitado", f"DEX sem launchpad de graduacao conhecido ({launchpad})")
    lo, hi = int(created_ts) - margin_s, int(created_ts) + margin_s
    try:
        anchor, _slot, _bt = anchor_fn(rpc, hi)
        rows: list[dict] = []
        for account in spec.accounts:
            before = anchor
            for _ in range(max_pages):
                page = rpc.signatures(account, before=before, limit=SIGNATURES_PAGE_SIZE)
                if not page:
                    break
                rows += [r for r in page if r.get("blockTime") is not None and lo <= r["blockTime"] < hi and r.get("err") is None]
                if len(page) < SIGNATURES_PAGE_SIZE or any((r.get("blockTime") or hi) < lo for r in page):
                    break
                before = page[-1]["signature"]
            else:
                return Lineage("erro", f"conta-chave {account[:8]} com transacoes demais na janela")
        rows.sort(key=lambda r: (abs(r["blockTime"] - created_ts), r["signature"]))
        seen = 0
        for row in rows[:max_fetch]:
            tx = rpc.call("getTransaction", [row["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            seen += 1
            g = resolve_graduation(tx, spec, row["signature"]) if tx else None
            if g is None or g.pool != pool:
                continue
            if g.mint != mint:
                return Lineage("rejeitado", f"a migracao deste pool e de outro token ({g.mint})")
            supply = rpc.token_supply(mint)
            if not supply:
                return Lineage("erro", "supply do token indisponivel no RPC")
            return Lineage("ok", "", spec.name, float(g.block_time) if g.block_time else None, g.quote_mint, float(supply),
                           g.signature, g.instruction)
        return Lineage("rejeitado", f"nenhuma migracao {spec.name} criou este pool em +-{margin_s // 60} min da criacao "
                                    f"({seen} de {len(rows)} transacoes da conta-chave abertas, das mais proximas)")
    except (RpcError, RuntimeError) as exc:
        return Lineage("erro", f"{type(exc).__name__}: {str(exc)[:160]}")


class LineageVerifier:
    """Confere os pools `pendente` um por vez: linhagem e depois a data de criacao do token. O RPC publico e lento, entao
    roda numa thread propria (`run`) para nao atrasar o ciclo do bot; os testes chamam `step()` direto. Pool verificado
    por uma versao anterior do bot (sem a data de criacao) passa so pela busca da criacao."""

    def __init__(self, storage: Any, rpc: Any, clock: Callable[[], float] = utc_now, verify: Callable[..., Lineage] = verify_lineage,
                 creation: Callable[..., tuple] = creation_time):
        self.storage = storage
        self.rpc = rpc
        self.clock = clock
        self.verify = verify
        self.creation = creation

    @staticmethod
    def _info(row: Any) -> dict:
        try:
            value = json.loads(row["info"] or "{}")
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    def _ready(self, row: Any, now: float) -> bool:
        if row["checked_ts"] is None:
            return True
        tries = self._info(row).get("tentativas", 0)
        return now - row["checked_ts"] >= min(1800.0, 120.0 * (2 ** tries))

    def _lineage(self, row: Any, info: dict) -> Lineage:
        res = self.verify(self.rpc, row["pool"], row["mint"], float(info.get("created_ts") or 0.0), GRAD_DEX.get(row["dex"]))
        info["linhagem"] = asdict(res)
        if res.status == "ok" and GRAD_DEX.get(row["dex"]) != res.launchpad:
            res = Lineage("rejeitado", f"DEX {row['dex']} nao e a de graduacao de {res.launchpad}")
        if res.status == "ok" and res.quote and row["quote"] and res.quote != row["quote"]:
            res = Lineage("rejeitado", f"cotacao on-chain ({res.quote}) difere da do GT ({row['quote']})")
        if res.status == "ok" and not res.grad_ts:
            res = Lineage("erro", "migracao sem horario de bloco")
        return res

    def _creation(self, row: Any, res: Lineage, info: dict) -> Lineage:
        """Criacao do token = transacao bem-sucedida mais antiga do mint antes da migracao (a idade do sinal parte dela).
        Teto de paginas = criacao desconhecida = sem idade = nenhum sinal primario possivel: o pool nao entra."""
        if not res.signature:
            return Lineage("erro", "sem a assinatura da migracao para buscar a data de criacao")
        try:
            created, seen, _complete = self.creation(self.rpc, row["mint"], res.signature, max_pages=CREATION_MAX_PAGES)
        except (RpcError, RuntimeError) as exc:
            return Lineage("erro", f"data de criacao: {type(exc).__name__}: {str(exc)[:120]}")
        if created is None:
            return Lineage("rejeitado", f"data de criacao do token desconhecida ({seen} assinaturas do mint antes da migracao, "
                                        f"teto de {CREATION_MAX_PAGES} paginas): sem idade nao ha sinal primario")
        if res.grad_ts and created > res.grad_ts:
            return Lineage("rejeitado", "data de criacao depois da migracao (dado inconsistente)")
        info["criado_ts"] = float(created)
        return res

    def step(self) -> bool:
        now = self.clock()
        ready = [r for r in self.storage.pr_pools("pendente", "verificado")
                 if (r["status"] == "pendente" or "criado_ts" not in self._info(r)) and self._ready(r, now)]
        if not ready:
            return False
        row = min(ready, key=lambda r: (r["checked_ts"] or 0.0, -(r["mc_found"] or 0.0)))
        info = self._info(row)
        info["tentativas"] = info.get("tentativas", 0) + 1
        if row["status"] == "pendente":
            res = self._lineage(row, info)
        else:                      # linhagem ja conferida por uma versao anterior do bot: falta so a data de criacao
            res = Lineage("ok", "", row["launchpad"], row["grad_ts"], row["quote"], row["supply"],
                          (info.get("linhagem") or {}).get("signature"))
        if res.status == "ok":
            res = self._creation(row, res, info)
        fields: dict[str, Any] = {"checked_ts": self.clock(), "info": json.dumps(info, ensure_ascii=False)}
        if res.status == "ok":
            fields.update(status="verificado", launchpad=res.launchpad, grad_ts=res.grad_ts, supply=res.supply, motivo="")
            log.info("POS-RUNNER: linhagem ok %s (%s, %s, criado em %s)", row["symbol"], res.launchpad, row["pool"][:8],
                     iso_utc(info["criado_ts"]))
        elif res.status == "rejeitado" or info["tentativas"] >= VERIFY_MAX_ATTEMPTS:
            fields.update(status="rejeitado", motivo=res.motivo[:200])
            log.info("POS-RUNNER: %s fora (%s)", row["symbol"], res.motivo[:120])
        else:
            fields.update(motivo=res.motivo[:200])
        self.storage.pr_upsert_pool(row["pool"], **fields)
        return True

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                worked = self.step()
            except Exception:  # noqa: BLE001 - a thread nunca morre por um pool
                log.exception("POS-RUNNER: erro na verificacao de linhagem")
                worked = False
            stop.wait(1.0 if worked else 15.0)


# ---------------------------------------------------------------------------
# orcamento compartilhado com o bot e cotacoes
# ---------------------------------------------------------------------------


class BudgetedHttp:
    """O HttpClient do GeckoTerminal do bot, mas cada GET gasta 1 chamada do orcamento do ciclo (o limite do GT e por
    IP: o POS-RUNNER divide o mesmo limitador com o bot v0). Fora de um ciclo armado nao ha chamada."""

    def __init__(self, http: Any, max_wait_s: float = 15.0):
        self.http = http
        self.headers = http.headers
        self.limiter = http.limiter
        self.max_wait_s = max_wait_s
        self._budget: Optional[CallBudget] = None
        self._keep = 0
        self._cap = 0
        self.used = 0

    def arm(self, budget: CallBudget, keep: int, cap: int) -> None:
        self._budget, self._keep, self._cap, self.used = budget, keep, cap, 0

    def disarm(self) -> int:
        self._budget = None
        return self.used

    def get_json(self, path: str, params: Any = None, max_wait_s: float = 5.0) -> Any:
        if self._budget is None or self.used >= self._cap or not self._budget.take(1, keep=self._keep):
            raise ApiError("budget", "POS-RUNNER: sem chamada no orcamento deste ciclo")
        self.used += 1
        return self.http.get_json(path, params, max_wait_s=min(max_wait_s, self.max_wait_s))


class LiveQuotes:
    """Cotacao/USD de 1h de cada moeda de cotacao (estavel = 1; SOL = Orca SOL/USDC; outra = pool de referencia
    escolhido e REGISTRADO como na Parte A), renovada no maximo a cada `refresh_s`. So usa horas fechadas."""

    def __init__(self, ohlcv: OhlcvStore, registry: Path, refresh_s: float = QUOTE_REFRESH_S):
        self.ohlcv = ohlcv
        self.refresh_s = refresh_s
        self.book = QuoteBook(ohlcv, registry, fetch_pools=lambda mint: ohlcv.http.get_json(
            f"networks/{ohlcv.network}/tokens/{mint}/pools", {"page": 1}, max_wait_s=15.0))
        self._cache: dict[str, tuple[float, int, UsdSeries]] = {}

    def no_reference(self, quote: str) -> bool:
        """True quando a busca ja concluiu que a cotacao NAO tem referencia em USD (o pool sai, nunca e convertido no chute)."""
        return quote not in STABLES and quote in self.book.registry and self.book.registry[quote] is None

    def peek(self, quote: str) -> Optional[UsdSeries]:
        if quote in STABLES:
            return stable_series()
        hit = self._cache.get(quote)
        return hit[2] if hit else None

    def series(self, quote: str, since_ts: float, now: float) -> Optional[UsdSeries]:
        if quote in STABLES:
            return stable_series()
        hit = self._cache.get(quote)
        if hit and now - hit[0] < self.refresh_s and hit[1] <= since_ts:
            return hit[2]
        ref = self.book.reference(quote, int(now))
        if ref is None:
            return None
        start = int(min(since_ts, hit[1] if hit else since_ts)) - 3 * 3600
        # so horas FECHADAS da referencia: a hora em andamento vale o ultimo fechamento (estritamente causal; a cotacao
        # anda < ~1% numa hora, perto do movimento de uma memecoin). A Parte A interpola dentro da hora ja fechada.
        bars = [b for b in self.ohlcv.history(ref[0], "1h", start, int(now), currency="usd", side=ref[1]) if b.ts + 3600 <= now]
        series = UsdSeries([b.ts for b in bars], [b.open for b in bars], [b.close for b in bars])
        self._cache[quote] = (now, start, series)
        return series


# ---------------------------------------------------------------------------
# textos
# ---------------------------------------------------------------------------


def _esc(value: Any, limit: int = 40) -> str:
    return html.escape(clean_text(value, limit), quote=False)


def _pct(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "s/d"
    text = f"{value:+.{digits}f}%".replace("-", "−")
    return text.replace(".", ",")


def _num(value: Optional[float], digits: int = 1) -> str:
    return "s/d" if value is None else f"{value:.{digits}f}".replace(".", ",")


def _head(emoji: str, title: str, tf: str, symbol: str, launchpad: Optional[str]) -> str:
    lp = LAUNCHPAD_NAME.get(launchpad or "", launchpad or "?")
    return f"{emoji} {title} [{tf}] | ${_esc(symbol, 20)} | {_esc(lp)}"


def _yes(value: Any) -> str:
    return "s/d" if value is None else ("sim" if value else "não")


def watch_text(symbol: str, launchpad: Optional[str], tf: str, mint: str, d: dict, on_arrival: bool) -> str:
    lines = [
        _head("👀", "WATCHLIST POS-RUNNER", tf, symbol, launchpad),
        f"Pico {fmt_usd(d['P_peak'])} ({d['faixa_pico']}) → queda {_num(d['queda_pct'], 0)}% | L_bc {fmt_usd(d['L_bc'])} | "
        f"idade {_num(d['idade_dias'])} d desde a criação",
        f"Zona S {fmt_usd(d['S'])} – R {fmt_usd(d['R'])} (R/S {_num(d['R'] / d['S'] if d['S'] else None)}) | "
        f"{d['n_testes']} teste(s) de suporte | {d['box_len']} candles",
        f"Entrada se FECHAR acima de R (sem exigência de volume) | morre se fechar abaixo de {fmt_usd(d['morre_abaixo'])}",
    ]
    if on_arrival:
        lines.append("(a zona ja estava madura quando o token entrou no radar)")
    lines.append(f"<code>{_esc(mint, 60)}</code>")
    return "\n".join(lines)


def entry_text(symbol: str, launchpad: Optional[str], tf: str, mint: str, d: dict, version: str, status: str) -> str:
    entry, stop, tp = d["close"], d["stop"], d["tp"]
    rr = (tp - entry) / (entry - stop) if entry > stop else None
    n = d.get("n_entrada", 1)
    kind = "primário" if d.get("primario") else "reentrada ou fora da idade: diagnóstico, fora da métrica primária"
    lines = [
        _head("🟢", "ENTRADA POS-RUNNER", tf, symbol, launchpad),
        f"Entrada ~MC {fmt_usd(entry)} (open do próximo candle) | Stop {fmt_usd(stop)} ({_pct(100 * (stop / entry - 1))}) | "
        f"Alvo {fmt_usd(tp)} ({_pct(100 * (tp / entry - 1))}) | R:R {_num(rr)}",
        f"{d['n_testes']} teste(s) de suporte | volume do rompimento {_num(d.get('vol_ratio'))}× a média da zona (só atributo)",
    ]
    if d.get("power_candle"):
        lines.append("⚡ Power candle saudável no rompimento (atributo positivo)")
    lines += [
        f"Pico {fmt_usd(d['P_peak'])} ({d.get('faixa_pico', '?')}) | queda {_num(d.get('queda_pct'), 0)}% | L_bc {fmt_usd(d['L_bc'])} | "
        f"S {fmt_usd(d['S'])} (≥ 100k: {_yes(d.get('S_acima_100k'))}) | R {fmt_usd(d['R'])} | "
        f"idade {_num(d.get('idade_dias'))} d desde a criação",
        f"Sinal #{n} ({kind}) · paper A/B automático · config {version} ({status})",
        f"<code>{_esc(mint, 60)}</code>",
    ]
    return "\n".join(lines)


EXIT_TEXT = {
    "stop": "STOP atingido",
    "alvo": "ALVO (perto do último topo) atingido — A vende tudo",
    "alvo_parcial": "ALVO atingido — B vende metade e o resto segue com trailing",
    "trailing": "B: trailing atingido — vende o resto",
    "stop_na_entrada": "B: voltou ao preço de entrada — vende o resto",
    "exaustao": "power candle de EXAUSTÃO perto do último topo — sair no próximo candle",
    "tempo": "stop de TEMPO (sem alvo nem stop) — sair a mercado",
}


def exit_text(symbol: str, launchpad: Optional[str], tf: str, reasons: list[str], variants: str, price: float, entry: float) -> str:
    if set(reasons) == {"alvo", "alvo_parcial"}:
        what = "ALVO (perto do último topo) atingido — A vende tudo; B vende metade e segue com trailing"
    else:
        what = "; ".join(EXIT_TEXT.get(r, r) for r in reasons)
    return (f"{_head('🟡', 'SAÍDA SUGERIDA', tf, symbol, launchpad)}\n{what}\n"
            f"MC ~{fmt_usd(price)} ({_pct(100 * (price / entry - 1))} desde a entrada) · vale para: {variants}")


# ---------------------------------------------------------------------------
# o modulo ao vivo
# ---------------------------------------------------------------------------


def event_to_json(ev: Event) -> str:
    return json.dumps({"kind": ev.kind, "idx": ev.idx, "ts": ev.ts, "decision_ts": ev.decision_ts, "data": ev.data}, default=float)


def event_from_json(text: str) -> Event:
    d = json.loads(text)
    return Event(d["kind"], int(d["idx"]), int(d["ts"]), int(d["decision_ts"]), d.get("data") or {})


def event_v1_to_json(ev: EventV1) -> str:
    return json.dumps({"kind": ev.kind, "idx": ev.idx, "ts": ev.ts, "decision_ts": ev.decision_ts, "data": ev.data}, default=float)


def event_v1_from_json(text: str) -> EventV1:
    d = json.loads(text)
    return EventV1(d["kind"], int(d["idx"]), int(d["ts"]), int(d["decision_ts"]), d.get("data") or {})


class PosRunnerLive:
    def __init__(
        self,
        settings: LiveSettings,
        params: Params,
        storage: Any,
        gt_http: Any,
        ctx: ChainCtx,
        telegram: Any,
        links: dict,
        dexscreener_slug: str,
        work_dir: Path,
        clock: Callable[[], float] = utc_now,
        costs: CostModel = CostModel(),
        rpc: Any = None,
        sem_v0: bool = False,
        terminal: str = "axiom",
        chain_name: str = "Solana",
        dexpaprika: Optional[DexPaprikaProvider] = None,
        sem_v2: bool = False,
        sem_evidencia: bool = False,
        sem_carteiras: bool = False,
        carteiras_max_chamadas_dia: int = 200,
        sem_sombra: bool = False,
        sombra_max_pools: int = 10,
    ):
        self.settings = settings
        self.params = params
        self.storage = storage
        self.ctx = ctx
        self.tg = telegram
        self.links = links
        self.dexscreener_slug = dexscreener_slug
        self.clock = clock
        self.costs = costs
        self.costs2 = CostModel(costs.position_sol, costs.terminal_pct, costs.network_sol, multiplier=2.0)
        self.alerts_on = True
        self.http = BudgetedHttp(gt_http)
        self.work_dir = Path(work_dir)
        self.ohlcv = OhlcvStore(self.http, self.work_dir / "ohlcv", network=ctx.gt_network, sleep=lambda s: None,
                                patient=False, wait_s=15.0)
        self.quotes = LiveQuotes(self.ohlcv, self.work_dir / "referencias_cotacao.json")
        self.chart_dir = self.work_dir / "graficos"
        self.status = config_status(params.version)
        self.sem_v0 = sem_v0          # item 0 (regras inegociaveis): flag --sem-v0 desliga o V0 por completo
        self.chain_name = chain_name
        self.dets: dict[tuple[str, str], Detector] = {}
        # EMENDA 2026-10-16 (grade de 24 combinacoes): 2a medida da queda ("fechamentos"), MESMOS candles, so
        # paper/CSV -- nunca alerta (a combinacao primaria original, extremos, continua a unica com alerta).
        self.dets_fecham: dict[tuple[str, str], Detector] = {}
        self.params_fecham = dataclasses.replace(params, queda_medida="fechamentos")
        # PEDIDO 2026-10-28: alem de "next"/"erros", agora tambem guarda diagnostico (nunca influencia
        # deteccao/sinal, so o texto do alerta operacional de fila atrasada) -- "ultimo_erro" (None |
        # "429" | "timeout" | "network" | "http" | "not_found" | "bad_json" | "sem_cotacao_usd" |
        # "sem_cotacao_no_fim" | "sem_candle_novo" | "erro_inesperado"), "ultima_tentativa" (ts) e
        # "fonte" ("gt" | "dexpaprika_fallback").
        self.sched: dict[tuple[str, str], dict[str, Any]] = {}
        self.next_discovery = 0.0
        self.source_idx = 0
        self.last_prune = 0.0
        self.last_baselines = 0.0
        self.last_tick: dict[str, Any] = {}
        self.version = params.version
        self.version_start: Optional[float] = None     # 1o ciclo desta versao_config (decisao anterior nao vira sinal)
        self._bankroll: dict[tuple[str, str], BankrollLedger] = {}  # (tf, variante) desta versao_config -> ledger
        self._bankroll_params = BankrollParams()
        # -- POS-RUNNER-V1 ("regras do professor"): estrategia independente, MESMOS candles (pr_bars) do V0 --
        self.params_v1 = load_params_v1()
        self.version_v1 = self.params_v1.version
        self.version_v1_start: Optional[float] = None
        self.adapter = SolanaAdapter(self.http, ctx, self.ohlcv, rpc, links, terminal=terminal)
        self.dets_v1: dict[tuple[str, str], DetectorV1] = {}
        self._v1_invalid: set[tuple[str, str]] = set()      # dado_invalido definitivo (nunca re-tenta)
        self._v1_mc_baixo_logged: set[str] = set()          # filtrado_mc_baixo: loga 1x por pool (nao reabre a cada ciclo)
        self._v1_suspeito: dict[tuple[str, str], bool] = {}        # l_bc_suspeito (FASE 1.1): tag suave, nunca bloqueia
        self._v1_suspeito_logged: set[tuple[str, str]] = set()     # conta 1x por pool/tf (nao reabre a cada ciclo)
        self._bankroll_v1: dict[str, BankrollLedgerV1] = {}  # tf desta versao_config_v1 -> ledger
        self._uptime_id: Optional[int] = None
        # PEDIDO 2026-10-29, item 2: ts de inicio da SESSAO atual (este processo, desde o ultimo
        # restart) -- separado do acumulado (`pr1_uptime_hours`, soma TODAS as sessoes da versao
        # congelada atual, que pode abranger varios restarts sem troca de config).
        self._uptime_sessao_inicio: Optional[float] = None
        # heartbeat periodico (revisao da FASE 1, 2026-10-22: nao existia -- telegram_v1.heartbeat_text
        # ficava morto; revisao da FASE 1.1: sai ja no startup -- nao espera a 1a janela -- e a cada 6h, nao
        # 4h). Janela rolante: zera a cada envio, nunca acumula indefinidamente.
        self.heartbeat_interval_s: float = 6 * 3600.0
        self._heartbeat_calls = 0
        self._heartbeat_429 = 0
        self._heartbeat_window_start: Optional[float] = None
        self._heartbeat_sent_at: float = 0.0
        # PEDIDO CONSOLIDADO FASE 1 (DexPaprika): None = recurso inteiro desligado, zero chamada extra.
        self.dexpaprika = dexpaprika
        self._fonte_candle_atual = "gt"   # lido por `_entry_v1` ao montar o sinal (nunca persiste entre chamadas)
        # PEDIDO CONSOLIDADO FASE 2: POS-RUNNER-V2 -- MESMO detector/simulador/banca da V1 (ver
        # params_v2.py), roda EM PARALELO sobre os MESMOS candles, tabelas/CSV/banca PROPRIAS (nunca
        # mistura estatistica com a V1). `sem_v2` (flag --sem-v2/env SEM_V2=1) desliga por completo.
        self.sem_v2 = sem_v2
        self.params_v2 = load_params_v2()
        self.version_v2 = self.params_v2.version
        self.version_v2_start: Optional[float] = None
        self.dets_v2: dict[tuple[str, str], DetectorV1] = {}
        self._v2_invalid: set[tuple[str, str]] = set()
        self._v2_mc_baixo_logged: set[str] = set()
        self._v2_suspeito: dict[tuple[str, str], bool] = {}
        self._v2_suspeito_logged: set[tuple[str, str]] = set()
        self._bankroll_v2: dict[str, BankrollLedgerV1] = {}
        # PEDIDO ADICIONAL FASE 6, item 2: alertas operacionais (saude do bot, nunca um sinal) -- 1x por
        # OCORRENCIA, sem spam. `_tick_history` e uma janela rolante (ts, rate_limited) por ciclo.
        self._tick_history: list[tuple[float, bool]] = []
        self._alerta_429_ativo = False
        # PEDIDO 2026-10-28/29: estado POR (pool, hora_de_fechamento) -- `self._fila_pools[(pool,hora)]
        # = {"tf","avisos","resolvido","ultima_vez_pendente"}` -- no maximo 3 avisos por `(pool,hora)`
        # (teto/+60/+120 min), "resolvido" so com histerese real (nunca uma lacuna de 1 tick zera o
        # historico de avisos -- esse era o bug do flapping real do ELON). Ver `_checar_fila_atrasada`.
        self._fila_pools: dict[tuple[str, int], dict[str, Any]] = {}
        # PEDIDO (PARTE 1 de 2) FASES 1-2: trajetoria pos-entrada + baseline pareada -- medicao AO LADO de
        # V1/V2 (ver evidencia.py), nunca altera deteccao/entrada/saida/banca/Telegram/CSV oficiais. So
        # candles JA em cache (zero chamada nova de GT/DexPaprika -- ver INTERPRETACOES.md para o porque
        # o fallback "1 fetch/hora" da regra 3 fica fora do escopo desta entrega). SEM_EVIDENCIA=1 desliga
        # por completo (zero custo extra de CPU tambem).
        self.sem_evidencia = sem_evidencia
        # PEDIDO 2026-10-27 (H9): snapshot de top holders cruzados com a lista de carteiras "pro"
        # (carteiras_pro.py) -- ENTRADA reusa a MESMA chamada RPC de `adapter.holders()` (zero custo
        # extra); a horaria (`_atualizar_carteiras_horaria`) e uma chamada NOVA, orcada por
        # `carteiras_max_chamadas_dia` (env CARTEIRAS_MAX_CHAMADAS_DIA). SEM_CARTEIRAS=1 desliga por
        # completo (inclusive o cruzamento na ENTRADA, que so preenche dado, nunca filtra).
        self.sem_carteiras = sem_carteiras
        self.carteiras_max_chamadas_dia = carteiras_max_chamadas_dia
        self._mapa_carteiras_pro = carteiras_pro.carregar_mapa_grupos()   # {} se o arquivo nao existir
        self._carteiras_horaria_ultima: dict[str, int] = {}   # pool -> ultimo bucket de hora UTC coletado
        # PEDIDO (PARTE 2A) FASE 3: sombra dos filtros filtrado_mc_baixo e queda_96_mais -- MEDICAO AO
        # LADO (nunca altera deteccao/entrada/saida/banca/CSV oficiais de V1/V2). filtrado_idade nao
        # precisa de detector proprio (reusa o evento FORA_DA_IDADE que o detector REAL da V1 ja emite
        # -- ver `_on_event_v1`). mc_baixo e queda_96_mais precisam de um `DetectorV1` PARALELO (mesma
        # classe/regras, so sem o piso de MC ou com drop_max estendido), alimentado pelos MESMOS
        # candles `seq` ja buscados nesta mesma chamada pra V1/V2 (zero chamada nova de GT/DexPaprika).
        # SOMBRA_MAX_POOLS (padrao 10) limita quantos (pool,tf) tem um detector sombra PARALELO ao
        # mesmo tempo -- `sombra_descartada_teto` conta quando um candidato novo e descartado por isso.
        # SEM_SOMBRA=1 desliga esta parte inteira (zero custo extra de CPU tambem).
        self.sem_sombra = sem_sombra
        self.sombra_max_pools = sombra_max_pools
        self.dets_sombra_mc: dict[tuple[str, str], DetectorV1] = {}
        self.dets_sombra_queda96: dict[tuple[str, str], DetectorV1] = {}
        # MESMOS campos que decidem o trade dentro de `simulate_v1` (atr_period/power_atr_mult/
        # exhaustion_wick_mult/exhaustion_doji_frac/tp1_frac) sao IDENTICOS entre V1 e V2 (so
        # drop_max/age_window_days mudam) -- so drop_max precisa mudar aqui pra detectar o gatilho
        # alem do que a V1/V2 matariam como ONDA_INVALIDA; nunca um Params novo/hash novo (fora do
        # hash de ParamsV1/V2, nunca gravado como versao_config_v1/v2 de nenhum sinal real).
        self._params_sombra_queda96 = dataclasses.replace(self.params_v2, drop_max=0.995)
        # PEDIDO 2026-10-29 (item 2/3, saude.py: CARTEIRAS com 0 snapshots): diagnostico da coleta, por
        # ciclo (zerado em `tick()`) + o ultimo erro/tentativa (persistem entre ciclos, ate o proximo).
        # `_carteiras_rpc_configurado` so e gravado em `meta` (saude.py le de la, processo separado)
        # dentro de `_startup`, reflete o adapter REAL deste processo (nunca um env var lido por outro
        # processo, que pode nao compartilhar o mesmo ambiente do bot).
        self._carteiras_ciclo = {"tentativas": 0, "gravados": 0, "erros": 0, "orcamento_esgotado": 0}
        self._carteiras_ultimo_erro: Optional[str] = None
        self._carteiras_ultima_tentativa_ts: Optional[float] = None

    # -- controle -----------------------------------------------------------------------------
    def enabled(self) -> bool:
        return self.settings.ligado

    def update_settings(self, settings: LiveSettings, alerts_on: bool, links: dict) -> None:
        """Recarga do config.yaml. Os parametros do detector (arquivo separado, hash proprio) so mudam reiniciando."""
        self.settings = settings
        self.alerts_on = alerts_on
        self.links = links

    def tfs(self) -> tuple[str, ...]:
        """Revisao da FASE 1 (2026-10-22): com `--sem-v0` o V0 nunca roda, entao `_due_list` nao deve mais
        buscar os timeframes que SO o V0 usava (tipicamente 5m/4h) -- so os da V1 (`params_v1.timeframes`,
        padrao so 1h). Sem isto a flag silenciava o V0 mas continuava gastando o MESMO orcamento de GT.

        Nota (revisao FASE 1.1): `_discover`/`offer`/`_promote` (descoberta/promocao de pools) NAO tem um
        modo "so V0" para cortar -- e a MESMA fila de pools ativos que a V1 consome (`pr_pools("ativo")`,
        item 0 do prompt: "V1 roda sobre os MESMOS candles/pools do V0", nunca uma descoberta separada).
        Cortar isso com `--sem-v0` desligaria a V1 tambem, o que NAO foi pedido -- entao continua rodando;
        o corte real de "chamadas so do V0" e exatamente este metodo (timeframes) e `det=None`/
        `det_fecham=None` em `_refresh` (nenhum Detector do V0 e criado, nenhum candle extra e pedido so
        para ele)."""
        if self.sem_v0:
            return self.params_v1.timeframes
        return self.settings.timeframes or TFS

    def _startup(self, now: float) -> None:
        """1o ciclo: marca o inicio desta versao_config (decisoes anteriores, refeitas dos candles congelados, nao viram
        sinal dela); paper aberto de outra versao vira `descontinuado` (outra regra; fica fora de qualquer avaliacao);
        pool ativo sem a data de criacao (verificado por uma versao anterior do bot) volta para a fila ate a thread de
        linhagem buscar a criacao."""
        self.version_start = self.storage.pr_version_start(self.version, now)
        for signal in self.storage.pr_signals(status="aberto"):
            if signal["versao_config"] != self.version:
                self.storage.pr_update_signal(signal["id"], status="descontinuado", closed_ts=now)
        for row in self.storage.pr_pools("ativo"):
            if "criado_ts" not in LineageVerifier._info(row):
                self.storage.pr_upsert_pool(row["pool"], status="verificado", motivo="falta a data de criacao do token")
        # POS-RUNNER-V1: mesma regra de inicio de versao (item 3.7); decisao anterior ao 1o ciclo desta
        # versao_config_v1 nunca vira sinal dela.
        # PATCH 2026-10-27 (item 3, retomada): um sinal "atrasado" (lacuna > folga do tf desde o ultimo
        # candle conhecido) NAO fecha mais de cara como `perdido_offline` -- o pool `ativo` continua
        # sendo atualizado pelo ciclo normal (`_refresh`/`_refresh_safe`, GT primeiro, DexPaprika como
        # fallback quando o GT falha -- MESMO pipeline que ja busca candles antigos, ja que `_fetch_gt`
        # sempre pede de `grad_ts` at'e `now`), que fecha a lacuna sozinho e retoma o acompanhamento com
        # os precos REAIS (nunca perdidos). So fica `perdido_offline` quando o pool NAO ESTA MAIS ativo
        # (encerrado/removido -- nenhum candle novo sera buscado para ele nunca mais, os dados realmente
        # nao existem/nao virao). Ver INTERPRETACOES.md para a limitacao conhecida (pool que fica `ativo`
        # para sempre sem nunca fechar a lacuna nao e coberto por este patch).
        self.version_v1_start = self.storage.pr1_version_start(self.version_v1, now)
        for signal in self.storage.pr1_signals(status="aberto"):
            if signal["versao_config_v1"] != self.version_v1:
                self.storage.pr1_update_signal(signal["id"], status="descontinuado", closed_ts=now)
            elif self._late(now, signal["ts_fechamento"], max(1800.0, 2.0 * tf_seconds(signal["tf"]))):
                pool_row = self.storage.pr_pool(signal["pool"])
                if pool_row is None or pool_row["status"] != "ativo":
                    self.storage.pr1_update_signal(signal["id"], status="perdido_offline", closed_ts=now)
        if self._uptime_id is None:
            self._uptime_id = self.storage.pr1_uptime_start(now)
            self._uptime_sessao_inicio = now
        # PEDIDO CONSOLIDADO FASE 2: mesma regra de inicio de versao, tabelas PROPRIAS da V2.
        self.version_v2_start = self.storage.pr2_version_start(self.version_v2, now)
        for signal in self.storage.pr2_signals(status="aberto"):
            if signal["versao_config_v2"] != self.version_v2:
                self.storage.pr2_update_signal(signal["id"], status="descontinuado", closed_ts=now)
            elif self._late(now, signal["ts_fechamento"], max(1800.0, 2.0 * tf_seconds(signal["tf"]))):
                pool_row = self.storage.pr_pool(signal["pool"])
                if pool_row is None or pool_row["status"] != "ativo":
                    self.storage.pr2_update_signal(signal["id"], status="perdido_offline", closed_ts=now)
        # PEDIDO 2026-10-29 (item 4, saude.py: CARTEIRAS com 0 snapshots mesmo com posicao aberta): a
        # cada reinicio `self.dets_v1`/`self.dets_v2` comecam vazios, e `_heat_v1`/`_heat_v2` (task #94,
        # prioridade ABSOLUTA de posicao aberta) so devolvem rank 0 quando ja existe um Detector para o
        # (pool,tf) -- antes do 1o refresh pos-reinicio reconstruir isso, uma posicao JA aberta perdia
        # essa prioridade absoluta, atrasando o proprio refresh que dispara
        # `_atualizar_carteiras_horaria` (so roda APOS um refresh ja ter acontecido pra aquele pool).
        # Aqui so chama `_detector_v1`/`_detector_v2` mais cedo (nenhuma logica nova) -- a MESMA
        # reconstrucao inteira a partir de `pr_bars` ja em cache que ja aconteceria no 1o refresh
        # natural pos-reinicio ("reiniciar o bot refaz o mesmo estado a partir dos candles congelados",
        # docstring do topo deste arquivo) -- so adiantada. Restrito as posicoes JA abertas (conjunto
        # pequeno) e nunca o universo inteiro de pools ativos, pra nao disparar de 1 vez o replay de
        # historico (RPC/DexPaprika) de todo pool rastreado.
        for signal in self.storage.pr1_signals(status="aberto"):
            pool_row = self.storage.pr_pool(signal["pool"])
            if pool_row is not None:
                self._detector_v1(pool_row, signal["tf"], now)
        if not self.sem_v2:
            for signal in self.storage.pr2_signals(status="aberto"):
                pool_row = self.storage.pr_pool(signal["pool"])
                if pool_row is not None:
                    self._detector_v2(pool_row, signal["tf"], now)
        # PEDIDO 2026-10-29 (item 1/2, saude.py: CARTEIRAS com 0 snapshots): grava em `meta` a config
        # REAL deste processo (RPC configurado, orcamento, sem_carteiras) -- saude.py roda num processo
        # SEPARADO e so le banco/log, nunca o env var de OUTRO processo (que pode nao compartilhar o
        # mesmo ambiente do bot ao vivo na VM).
        self.storage.set_meta("pr_carteiras_runtime", json.dumps({
            "rpc_configurado": getattr(self.adapter, "rpc", None) is not None,
            "sem_carteiras": self.sem_carteiras, "carteiras_max_chamadas_dia": self.carteiras_max_chamadas_dia,
            "ts": now,
        }))

    def shutdown(self, now: float, motivo: str = "parado") -> None:
        """Fecha a sessao de uptime da V1 (item "registro completo"). Chamado uma vez no desligamento limpo."""
        if self._uptime_id is not None:
            self.storage.pr1_uptime_stop(self._uptime_id, now, motivo)
            self._uptime_id = None

    def lbc_tf(self) -> str:
        """L_bc sai do 1o candle de 1h (como no estagio 1 da Parte A); sem o 1h na config, do 1o tf ligado."""
        return "1h" if "1h" in self.tfs() else self.tfs()[0]

    # -- descoberta -------------------------------------------------------------------------------
    def offer(self, snaps: list[PoolSnap], now: float, fonte: str = "bot") -> int:
        """Candidatos: pool de graduacao (DEX certa), MC >= piso do runner, idade <= maxima. Entram como `pendente`
        (a linhagem on-chain decide). Um pool por token."""
        if not self.enabled():
            return 0
        queued = len(self.storage.pr_pools("pendente", "verificado"))
        added = 0
        for s in sorted(snaps, key=lambda x: -((x.mcap_usd or x.fdv_usd) or 0.0)):
            if s.chain != self.ctx.name or s.dex not in GRAD_DEX or s.both_reference:
                continue
            mc = s.mcap_usd or s.fdv_usd
            if mc is None or mc < self.params.runner_min_mc or mc > self.settings.mc_max_usd:
                continue
            if s.created_ts is None or now - s.created_ts > self.settings.idade_max_dias * 86400.0:
                continue
            if self.storage.pr_pool(s.pool) is not None or self.storage.pr_pool_for_mint(s.token) is not None:
                continue
            if queued >= QUEUE_MAX:
                break
            # liq_usd: so CAPTURA o que o snapshot do radar ja trouxe (zero chamada nova) -- instrumentacao
            # de medicao da V1 (liquidez_usd em pr1_signals), nunca usada em filtro/regra.
            # PEDIDO (PARTE 2A) FASE 4: vol_h24_usd/n_txs_h24 -- MESMO snapshot da descoberta (`s.vol`/
            # `s.tx`, GT ja devolve isso no payload de pools), nunca uma chamada nova; ficam congelados
            # aqui (a descoberta so acontece 1x por pool) pra estarem disponiveis na ENTRADA, mesmo
            # horas/dias depois (zero chamada nova la tambem).
            n_txs_h24 = s.tx.get("h24").total if s.tx.get("h24") else None
            info = {"fonte": fonte, "created_ts": s.created_ts, "side": s.target_side, "nome": s.name,
                    "liq_usd": s.liq_usd, "vol_h24_usd": s.vol.get("h24"), "n_txs_h24": n_txs_h24}
            self.storage.pr_upsert_pool(s.pool, mint=s.token, symbol=s.symbol, quote=s.other_token, dex=s.dex, status="pendente",
                                        found_ts=now, mc_found=mc, info=json.dumps(info, ensure_ascii=False))
            queued += 1
            added += 1
            log.info("POS-RUNNER: candidato %s (%s, MC %s, via %s)", s.symbol, s.dex, fmt_usd(mc), fonte)
        return added

    def _discover(self, now: float, out: dict[str, Any]) -> None:
        fontes = [f for f in self.settings.fontes if f in SOURCES]
        if not fontes or now < self.next_discovery:
            return
        name = fontes[self.source_idx % len(fontes)]
        path, query = SOURCES[name]
        try:
            data = self.http.get_json(path, query, max_wait_s=15.0)
            snaps = parse_pools_response(data, self.ctx, now)
        except RateLimited:
            raise
        except ApiError as exc:
            if exc.kind == "budget":
                raise
            out["erros"] += 1
            self.source_idx += 1                     # a lista que falhou vai para o fim do rodizio
            self.next_discovery = now + 60.0
            log.warning("POS-RUNNER: lista %s do GT falhou (%s)", name, exc)
            return
        self.source_idx += 1
        self.next_discovery = now + self.settings.descoberta_min * 60.0
        self.offer(snaps, now, fonte=name)

    def _promote(self, now: float) -> None:
        """Verificado (com a data de criacao) -> ativo enquanto houver vaga (maior MC na descoberta primeiro)."""
        active = len(self.storage.pr_pools("ativo"))
        waiting = sorted((r for r in self.storage.pr_pools("verificado") if "criado_ts" in LineageVerifier._info(r)),
                         key=lambda r: -(r["mc_found"] or 0.0))
        for row in waiting:
            if row["grad_ts"] is None or now - row["grad_ts"] > self.settings.idade_max_dias * 86400.0:
                self.storage.pr_upsert_pool(row["pool"], status="encerrado", checked_ts=now, motivo="passou da idade maxima na fila")
                continue
            if active >= self.settings.max_pools:
                break
            self.storage.pr_upsert_pool(row["pool"], status="ativo", added_ts=now)
            active += 1
            console.info("POS-RUNNER: acompanhando $%s (%s)", row["symbol"], LAUNCHPAD_NAME.get(row["launchpad"], row["launchpad"]))

    def _retire(self, now: float) -> None:
        for row in self.storage.pr_pools("ativo"):
            if now - (row["grad_ts"] or now) <= self.settings.idade_max_dias * 86400.0:
                continue
            if self.storage.pr_signals(status="aberto", pool=row["pool"]):
                continue           # trade de paper aberto: segue acompanhando ate fechar
            self.storage.pr_upsert_pool(row["pool"], status="encerrado", checked_ts=now, motivo="idade maxima")
            for tf in TFS:
                self.dets.pop((row["pool"], tf), None)
                self.sched.pop((row["pool"], tf), None)

    # -- agenda ------------------------------------------------------------------------------------
    def _heat(self, pool: str, tf: str) -> int:
        """0 = quente (fase 2 ou trade aberto: atualiza a cada candle), 1 = morno (runner), 2 = frio, -1 = sem carga.
        Revisao da FASE 1: o calor e o MELHOR entre V0 e V1 -- com `--sem-v0` o `self.dets` do V0 fica sempre
        vazio, e sem isto todo pool parecia "sem carga" (perdia a prioridade de fase 2/trade aberto da V1)."""
        v0 = self._heat_v0(pool, tf)
        v1 = self._heat_v1(pool, tf)
        if v0 == -1 and v1 == -1:
            return -1
        return min(h for h in (v0, v1) if h != -1)

    def _heat_v0(self, pool: str, tf: str) -> int:
        det = self.dets.get((pool, tf))
        if det is None:
            return -1
        if det.phase == PHASE_PULLBACK or self.storage.pr_signals(status="aberto", pool=pool, tf=tf):
            return 0
        return 1 if det.phase == PHASE_RUNNER else 2

    def _heat_v1(self, pool: str, tf: str) -> int:
        det = self.dets_v1.get((pool, tf))
        if det is None:
            return -1
        if det.phase == PHASE_PULLBACK or self.storage.pr1_signals(status="aberto", pool=pool, tf=tf):
            return 0
        return 1 if det.phase == PHASE_RUNNER else 2

    def _interval(self, tf: str, heat: int) -> float:
        step = float(tf_seconds(tf))
        return step if heat <= 0 else max(step, 900.0 if heat == 1 else 1800.0)

    def _due_list(self, now: float) -> list[tuple[int, float, Any, str]]:
        out = []
        for row in self.storage.pr_pools("ativo"):
            for tf in self.tfs():
                if row["l_bc"] is None and tf != self.lbc_tf():
                    continue
                st = self.sched.get((row["pool"], tf))
                if st is not None and now < st["next"]:
                    continue
                heat = self._heat(row["pool"], tf)
                rank = 0 if heat == 0 else (1 if heat < 0 else 2 + heat)
                out.append((rank, st["next"] if st else 0.0, row, tf))
        order = {"1h": 0, "4h": 1, "5m": 2}
        # PEDIDO 2026-10-29 (ELON, fase runner, nunca tentado -- item 2/3): dentro do MESMO rank de
        # calor, um (pool,tf) que NUNCA recebeu nenhuma tentativa nesta sessao (sem entrada em
        # `self.sched` ou sem `ultima_tentativa` -- ex.: logo depois de um restart, quando TODO pool
        # ativo zera junto) vai pra FRENTE dos que ja foram tentados ao menos uma vez (mesmo que ha
        # muito tempo) -- sem isso, o mesmo pool podia perder a competicao por orcamento pra outros do
        # MESMO rank indefinidamente. Nunca muda a ordem relativa ENTRE ranks -- posicao aberta
        # (rank 0) continua sempre primeiro, prioridade absoluta preservada.
        def _nunca_tentado(row: Any, tf: str) -> int:
            st = self.sched.get((row["pool"], tf))
            return 0 if (st is None or st.get("ultima_tentativa") is None) else 1
        out.sort(key=lambda x: (x[0], _nunca_tentado(x[2], x[3]), x[1], order.get(x[3], 9)))
        return out

    def wanted(self, now: float) -> int:
        """Quantas chamadas o POS-RUNNER quer neste ciclo (o bot reserva isso antes do refresh dos pools jovens)."""
        if not self.enabled():
            return 0
        n = len(self._due_list(now)) + (1 if now >= self.next_discovery and self.settings.fontes else 0)
        return min(n, self.settings.chamadas_por_ciclo)

    @staticmethod
    def _reserva_rank_maior() -> int:
        return int(os.environ.get("POS_RUNNER_RESERVA_RANK_MAIOR", "1"))

    # -- ciclo -------------------------------------------------------------------------------------
    def tick(self, now: float, budget: CallBudget, keep: int) -> dict[str, Any]:
        out: dict[str, Any] = {"chamadas": 0, "erros": 0, "rate_limited": False}
        if not self.enabled():
            return out
        t0 = time.monotonic()
        if self.version_start is None:
            self._startup(now)
        self._carteiras_ciclo = {"tentativas": 0, "gravados": 0, "erros": 0, "orcamento_esgotado": 0}
        fila_tamanho = 0
        due: list[tuple[int, float, Any, str]] = []
        cap_total = self.settings.chamadas_por_ciclo
        reserva = min(self._reserva_rank_maior(), max(0, cap_total - 1))
        # PEDIDO 2026-10-29 (ELON, fase runner, "nunca tentado desde que o bot subiu" -- itens 2/3):
        # posicao ABERTA (rank 0) tem prioridade ABSOLUTA, mas sem reserva, rank==0 suficiente para
        # gastar TODO `chamadas_por_ciclo` (padrao so 3) deixava descoberta e TODO pool de
        # watchlist/runner (rank>0) sem NENHUMA chance, ciclo apos ciclo -- pior logo depois de um
        # restart, quando `self.sched` zera e TODO pool ativo fica "devido" ao mesmo tempo (ver
        # INTERPRETACOES.md). Agora a 1a passada (rank==0) so pode gastar `cap_total - reserva`
        # (padrao reserva=1, env `POS_RUNNER_RESERVA_RANK_MAIOR`) -- continua sendo atendida primeiro
        # e por completo sempre que precisar de ATE esse teto; a 2a passada (descoberta + rank>0)
        # usa o que SOBROU do orcamento real do ciclo (nunca mais que `cap_total` no total). So excede
        # o teto um caso raro (varias posicoes abertas no MESMO ciclo) atrasa 1 delas por 1 tick,
        # nunca mais que isso -- nunca reduz a prioridade de rank==0 sobre rank>0.
        self.http.arm(budget, keep, max(0, cap_total - reserva))
        try:
            self._promote(now)
            due = self._due_list(now)
            fila_tamanho = len(due)
            for rank, _next, row, tf in due:
                if rank == 0:
                    self._refresh_safe(row, tf, now, out)
        except RateLimited:
            out["rate_limited"] = True
            budget.exhaust()
        except ApiError as exc:
            if exc.kind != "budget":
                out["erros"] += 1
                log.warning("POS-RUNNER: GeckoTerminal falhou: %s", exc)
        finally:
            out["chamadas"] += self.http.disarm()
        self.http.arm(budget, keep, max(0, cap_total - out["chamadas"]))
        try:
            self._discover(now, out)
            for rank, _next, row, tf in due:
                if rank > 0:
                    self._refresh_safe(row, tf, now, out)
        except RateLimited:
            out["rate_limited"] = True
            budget.exhaust()
        except ApiError as exc:
            if exc.kind != "budget":
                out["erros"] += 1
                log.warning("POS-RUNNER: GeckoTerminal falhou: %s", exc)
        finally:
            out["chamadas"] += self.http.disarm()
        self._retire(now)
        if now - self.last_baselines >= 3600.0:
            self.last_baselines = now
            self._refresh_baselines(now)
            self._update_sombra(now)
        if now - self.last_prune >= 3600.0:
            self.last_prune = now
            removed = self.storage.pr_prune(now)
            if removed:
                log.info("POS-RUNNER poda: %s", removed)
        # PEDIDO 2026-10-29 (item 3, saude.py: CARTEIRAS com 0 snapshots): diagnostico por ciclo da
        # coleta horaria -- pools tentados (RPC nova), gravados, com erro e com orcamento diario
        # esgotado -- pra auditar pelo log sem precisar de acesso ao processo ao vivo.
        log.info("POS-RUNNER-V1: ciclo | fila=%d | chamadas=%d | 429=%s | tempo=%.2fs | "
                 "carteiras_tentativas=%d carteiras_gravados=%d carteiras_erros=%d carteiras_orcamento_esgotado=%d",
                 fila_tamanho, out.get("chamadas", 0), out.get("rate_limited", False), time.monotonic() - t0,
                 self._carteiras_ciclo["tentativas"], self._carteiras_ciclo["gravados"],
                 self._carteiras_ciclo["erros"], self._carteiras_ciclo["orcamento_esgotado"])
        self._heartbeat_v1(now, out.get("chamadas", 0), out.get("rate_limited", False))
        self._checar_alerta_429(now, bool(out.get("rate_limited", False)))
        self._checar_fila_atrasada(now, due)
        self.last_tick = out
        return out

    # -- PEDIDO ADICIONAL FASE 6, item 2: alertas operacionais (saude do bot, nunca um sinal) -------------
    def _send_alerta_operacional(self, text: str) -> None:
        """Sempre tenta sair (nao depende de `alerts_on`, que e so da FASE das decisoes de trade), mas
        nunca derruba o ciclo se o Telegram falhar."""
        if self.tg is None:
            return
        try:
            self.tg.notify(text)
        except TelegramError as exc:
            log.warning("POS-RUNNER: falha ao mandar alerta operacional (%s)", exc)

    @staticmethod
    def _teto_429_pct() -> float:
        return float(os.environ.get("POS_RUNNER_429_TETO_PCT", "0.3"))

    @staticmethod
    def _janela_429_s() -> float:
        return float(os.environ.get("POS_RUNNER_429_JANELA_H", "2")) * 3600.0

    def _checar_alerta_429(self, now: float, rate_limited: bool) -> None:
        """Taxa de 429 do GeckoTerminal acima de um teto configuravel por N horas -- 1 alerta por
        OCORRENCIA: so dispara na TRANSICAO de normal->alto, nunca de novo enquanto continuar alto
        (sem spam); libera um novo alerta so depois de a taxa voltar a ficar <= o teto."""
        janela = self._janela_429_s()
        self._tick_history.append((now, rate_limited))
        corte = now - janela
        self._tick_history = [(t, r) for (t, r) in self._tick_history if t >= corte]
        if len(self._tick_history) < 5:   # poucas amostras: nunca alerta em cima de ruido
            return
        taxa = sum(1 for _, r in self._tick_history if r) / len(self._tick_history)
        teto = self._teto_429_pct()
        if taxa > teto:
            if not self._alerta_429_ativo:
                self._alerta_429_ativo = True
                self._send_alerta_operacional(
                    f"⚠ POS-RUNNER: taxa de 429 do GeckoTerminal em {100 * taxa:.0f}% nas ultimas "
                    f"{janela / 3600.0:.1f}h (teto {100 * teto:.0f}%).")
        else:
            self._alerta_429_ativo = False

    @staticmethod
    def _teto_fila_atraso_min() -> float:
        return float(os.environ.get("POS_RUNNER_FILA_ATRASO_MIN", "30"))

    def _fase_label_v1(self, pool: str, tf: str) -> str:
        det = self.dets_v1.get((pool, tf))
        if det is None:
            return "sem_fase"
        if det.phase == PHASE_PULLBACK:
            return "pullback"
        if det.phase == PHASE_RUNNER:
            return "runner"
        return "sem_fase"

    def _diagnostico_pool_fila(self, row: Any, tf: str, now: float) -> str:
        """PEDIDO 2026-10-28, item 2: token/fase/ultima tentativa/ultimo erro/fonte de 1 (pool,tf)
        pendente na fila -- so leitura de `self.sched`/`self.dets_v1` (gravados por `_refresh_safe`/
        `_refresh_core`/`_refresh_fallback_dexpaprika`), nunca uma chamada nova."""
        pool = row["pool"]
        st = self.sched.get((pool, tf), {})
        ultima = st.get("ultima_tentativa")
        desde = "nunca (desde que o bot subiu)" if ultima is None else f"{(now - ultima) / 60.0:.0f}min atrás"
        erro = st.get("ultimo_erro") or "nenhum (aguardando candle novo do provedor)"
        fonte = st.get("fonte") or "s/d"
        return (f"  {row['symbol']} ({pool[:8]}…) | fase: {self._fase_label_v1(pool, tf)} | "
                f"última tentativa: {desde} | último erro: {erro} | fonte: {fonte}")

    @staticmethod
    def _fila_resolvido_min_histerese() -> float:
        return float(os.environ.get("POS_RUNNER_FILA_RESOLVIDO_MIN", "10"))

    def _checar_fila_atrasada(self, now: float, due: list[tuple[int, float, Any, str]]) -> None:
        """Fila de atualizacao (candles 1h) que nao esvazia ate N min (padrao 30) depois do fechamento
        da hora.

        PEDIDO 2026-10-28: a 1a versao re-alertava a cada transicao 0->=1 dentro da MESMA hora.
        PEDIDO 2026-10-29 (ELON, fase runner -- flapping real a cada ~1min, limite de 3/h nao
        aplicava): o bug era um estado UNICO/global (`self._fila_estado["avisos"]`) zerado inteiro a
        cada tick em que a lista de pendentes ficava vazia -- um pool que flapeia pendente/vazio a
        cada ciclo apagava o historico de avisos e podia re-alertar na hora seguinte. Agora o estado e
        por `(pool, hora_de_fechamento)` (`self._fila_pools`), nunca por um contador agregado:
        - no maximo 3 avisos por `(pool,hora)` (teto/+60min/+120min), que SO sao zerados quando esse
          mesmo `(pool,hora)` for marcado resolvido (nunca por uma lacuna momentanea de 1 tick);
        - "resolvido" (por pool) só depois de `POS_RUNNER_FILA_RESOLVIDO_MIN` (padrao 10) minutos
          CONTINUOS sem aparecer pendente, OU imediatamente se `self.sched` registrar uma atualizacao
          bem-sucedida desse pool (`ultimo_erro is None` e `ultima_tentativa` mais recente que a
          ultima vez visto pendente) -- histerese real, nunca uma lacuna de 1 tick;
        - se o MESMO `(pool,hora)` for resolvido e depois voltar a ficar pendente (reincidencia
          genuina, nao flapping), comeca um novo ciclo de ate 3 avisos.
        Cada aviso traz, por pool pendente: token, fase do detector V1, ha quanto tempo foi a ultima
        tentativa, qual foi o ultimo erro e a fonte -- `_diagnostico_pool_fila` (so leitura de
        `self.sched`/`self.dets_v1`, nunca uma chamada nova)."""
        hora_boundary = (now // 3600) * 3600
        minutos_desde_fechamento = (now - hora_boundary) / 60.0
        hora_marcador = int(hora_boundary)
        teto = self._teto_fila_atraso_min()
        pendentes = {(row["pool"], tf): row for _rank, _next, row, tf in due if tf == "1h"}

        avisar: list[tuple[Any, str]] = []
        for (pool, tf), row in pendentes.items():
            key = (pool, hora_marcador)
            st = self._fila_pools.get(key)
            if st is None:
                st = {"tf": tf, "avisos": set(), "resolvido": False, "ultima_vez_pendente": now}
                self._fila_pools[key] = st
            elif st["resolvido"]:
                st["avisos"] = set()
                st["resolvido"] = False
            st["ultima_vez_pendente"] = now
            if minutos_desde_fechamento < teto:
                continue
            for tier in (teto, teto + 60.0, teto + 120.0):
                if minutos_desde_fechamento >= tier and tier not in st["avisos"]:
                    st["avisos"].add(tier)
                    avisar.append((row, tf))
                    break
        if avisar:
            linhas = [
                f"⚠ POS-RUNNER: fila de atualizacao (1h) ainda com {len(avisar)} pool(s)/tf "
                f"pendente(s) {minutos_desde_fechamento:.0f} min depois do fechamento da hora "
                f"(teto {teto:.0f} min)."
            ]
            linhas.extend(self._diagnostico_pool_fila(row, tf, now) for row, tf in avisar)
            self._send_alerta_operacional("\n".join(linhas))

        resolvidos: list[str] = []
        for (pool, hm), st in self._fila_pools.items():
            if st["resolvido"] or not st["avisos"] or (pool, st["tf"]) in pendentes:
                continue
            sched_st = self.sched.get((pool, st["tf"]), {})
            atualizou_com_sucesso = (sched_st.get("ultimo_erro") is None
                                     and (sched_st.get("ultima_tentativa") or 0.0) > st["ultima_vez_pendente"])
            sem_pendencia_min = (now - st["ultima_vez_pendente"]) / 60.0
            if atualizou_com_sucesso or sem_pendencia_min >= self._fila_resolvido_min_histerese():
                st["resolvido"] = True
                resolvidos.append(pool)
        if resolvidos:
            self._send_alerta_operacional(
                "✅ POS-RUNNER: fila de atualizacao (1h) normalizada para: "
                + ", ".join(sorted(set(resolvidos))) + ".")

        # limpeza: descarta (pool,hora) de horas antigas ja resolvidas (ou que nunca alertaram) --
        # nunca cresce sem limite num processo que roda dias/semanas.
        corte = hora_marcador - 3 * 3600
        for key in [k for k, st in self._fila_pools.items()
                   if k[1] < corte and (st["resolvido"] or not st["avisos"])]:
            del self._fila_pools[key]

    def _phase_counts_v1(self) -> dict[str, int]:
        """Pools acompanhados AGORA por fase do detector da V1 (item do heartbeat da revisao FASE 1.1)."""
        fases = {"sem_fase": 0, "runner": 0, "pullback": 0}
        for det in self.dets_v1.values():
            if det.phase == PHASE_PULLBACK:
                fases["pullback"] += 1
            elif det.phase == PHASE_RUNNER:
                fases["runner"] += 1
            else:
                fases["sem_fase"] += 1
        return fases

    def _phase_counts_v2(self) -> dict[str, int]:
        """PEDIDO 2026-10-29: mesmo papel de `_phase_counts_v1`, so que do detector PROPRIO da V2
        (`self.dets_v2`) -- pode divergir do V1 pro MESMO pool (parametros diferentes)."""
        fases = {"sem_fase": 0, "runner": 0, "pullback": 0}
        for det in self.dets_v2.values():
            if det.phase == PHASE_PULLBACK:
                fases["pullback"] += 1
            elif det.phase == PHASE_RUNNER:
                fases["runner"] += 1
            else:
                fases["sem_fase"] += 1
        return fases

    def _heartbeat_v1(self, now: float, chamadas: int, rate_limited: bool) -> None:
        """Mensagem "vivo": sai JA no 1o ciclo (nao espera a 1a janela) e depois a cada `heartbeat_interval_s`
        (padrao 6h, revisao FASE 1.1). Contadores (chamadas/min, 429, dado_invalido/l_bc_suspeito/
        filtrado_mc_baixo/filtrado_idade) sao so da janela desde o heartbeat anterior; pools por fase e fila
        de atualizacao sao o estado AGORA (nao acumulam)."""
        if self._heartbeat_window_start is None:
            self._heartbeat_window_start = now
            self._heartbeat_sent_at = now - self.heartbeat_interval_s   # forca o 1o heartbeat a sair ja no startup
        self._heartbeat_calls += chamadas
        if rate_limited:
            self._heartbeat_429 += 1
        if now - self._heartbeat_sent_at < self.heartbeat_interval_s:
            return
        elapsed_min = max((now - self._heartbeat_window_start) / 60.0, 1.0)
        chamadas_por_min = self._heartbeat_calls / elapsed_min
        pools_ativos = len(self.storage.pr_pools("ativo"))
        counts = self.storage.pr1_filtrado_counts(self._heartbeat_window_start)
        uptime_sessao_h = None if self._uptime_sessao_inicio is None else (now - self._uptime_sessao_inicio) / 3600.0
        fases_v1 = self._phase_counts_v1()
        # PEDIDO 2026-10-29 (item 2, saude.py: distribuicao de fases): `det.phase` so existe na MEMORIA
        # deste processo -- saude.py roda separado e so le banco/log. Persiste em `meta` o MESMO
        # contador que ja vai pro heartbeat (zero calculo novo), com o `ts` desta captura, pra saude.py
        # mostrar "ultima leitura conhecida" em vez de nada.
        self.storage.set_meta("pr_fase_counts_v1", json.dumps({**fases_v1, "ts": now}))
        text = telegram_v1.heartbeat_text(
            self.storage.pr1_uptime_hours(self.version_v1_start or now, now), pools_ativos, chamadas_por_min,
            self._heartbeat_429, fases_v1, len(self._due_list(now)), counts.get("dado_invalido", 0),
            counts.get("l_bc_suspeito", 0), counts.get("filtrado_mc_baixo", 0), counts.get("filtrado_idade", 0),
            self.version_v1, uptime_sessao_h=uptime_sessao_h,
        )
        self._send(text)
        if not self.sem_v2:
            # PEDIDO 2026-10-29: o heartbeat so mandava a V1 -- V2 ficava invisivel no "vivo"
            # periodico (so no resumo diario, que e so 1x/dia). MESMO gatilho/janela, mensagem
            # PROPRIA (nunca mistura com a V1); contadores PROPRIOS da V2 (fase/filtros), nunca os
            # compartilhados (uptime/chamadas/429/fila), ja cobertos pelo heartbeat V1 acima.
            counts_v2 = self.storage.pr2_filtrado_counts(self._heartbeat_window_start)
            fases_v2 = self._phase_counts_v2()
            self.storage.set_meta("pr_fase_counts_v2", json.dumps({**fases_v2, "ts": now}))
            text_v2 = telegram_v1.heartbeat_text_v2(
                fases_v2, counts_v2.get("dado_invalido", 0), counts_v2.get("l_bc_suspeito", 0),
                counts_v2.get("filtrado_mc_baixo", 0), counts_v2.get("filtrado_idade", 0), self.version_v2,
            )
            self._send(text_v2)
        self._heartbeat_sent_at = now
        self._heartbeat_window_start = now
        self._heartbeat_calls = 0
        self._heartbeat_429 = 0

    def _refresh_safe(self, row: Any, tf: str, now: float, out: dict[str, Any]) -> None:
        key = (row["pool"], tf)
        fallback_ja_tentado = False
        try:
            self._refresh(self.storage.pr_pool(row["pool"]), tf, now)
        except RateLimited as exc:
            # PEDIDO 2026-10-28 (diagnostico da fila atrasada): grava o 429 ANTES de relancar -- o
            # abort do ciclo inteiro (budget.exhaust() em `tick()`) continua igual, so acrescenta o
            # motivo pro alerta operacional.
            st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
            st["ultimo_erro"] = "429"
            st["ultima_tentativa"] = now
            st["fonte"] = "gt"
            raise
        except TelegramError:
            raise
        except ApiError as exc:
            if exc.kind == "budget":
                raise
            out["erros"] += 1
            st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
            st["erros"] += 1
            st["next"] = now + min(1800.0, 60.0 * (2 ** st["erros"]))
            st["ultimo_erro"] = exc.kind
            st["ultima_tentativa"] = now
            st["fonte"] = "gt"
            log.warning("POS-RUNNER: candles de %s %s falharam (%s)", row["symbol"], tf, exc)
            if exc.kind == "not_found" and st["erros"] >= 3:
                self.storage.pr_upsert_pool(row["pool"], status="encerrado", checked_ts=now, motivo="pool nao existe mais no GT (404)")
            # PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 3a: so quando o GT falhou de um jeito
            # retomavel (timeout/network/5xx -- nunca 404/400); nunca levanta, nunca substitui o GT na
            # proxima tentativa normal (o `_schedule`/retry acima continua igual, isto e so um extra).
            if self.dexpaprika is not None and (exc.kind in ("timeout", "network")
                                                or (exc.kind == "http" and (exc.status or 0) >= 500)):
                fallback_ja_tentado = True
                try:
                    if self._refresh_fallback_dexpaprika(self.storage.pr_pool(row["pool"]), tf, now):
                        log.info("POS-RUNNER: fallback DexPaprika cobriu %s %s enquanto o GT falhava", row["symbol"], tf)
                except Exception:  # noqa: BLE001 - o fallback e so um extra, nunca pode piorar o ciclo
                    log.exception("POS-RUNNER: fallback DexPaprika falhou em %s %s", row["symbol"], tf)
        except Exception:  # noqa: BLE001 - um pool com problema nunca trava os outros
            out["erros"] += 1
            st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
            st["erros"] += 1
            st["next"] = now + min(3600.0, 120.0 * (2 ** st["erros"]))
            st["ultimo_erro"] = "erro_inesperado"
            st["ultima_tentativa"] = now
            st["fonte"] = "gt"
            log.exception("POS-RUNNER: erro inesperado em %s %s (pool em espera)", row["symbol"], tf)
        if not fallback_ja_tentado:
            self._tentar_fallback_por_pendencia(row, tf, now)

    @staticmethod
    def _fallback_dexpaprika_min_pendente() -> float:
        return float(os.environ.get("POS_RUNNER_FALLBACK_DP_MIN", "20"))

    def _tentar_fallback_por_pendencia(self, row: Any, tf: str, now: float) -> None:
        """PEDIDO 2026-10-28, item 3: independente do MOTIVO (erro explicito do GT ou so sem candle
        novo ainda -- `sem_candle_novo`), se o (pool,tf) 1h continua pendente >= `POS_RUNNER_
        FALLBACK_DP_MIN` (padrao 20) min depois do fechamento da hora, tenta a mesma fonte DexPaprika
        de fallback (credito e barato/ocioso -- ver INTERPRETACOES.md). Reaproveita
        `_refresh_fallback_dexpaprika`/`_refresh_core`, que ja aplica a MESMA validacao de qualidade
        de candle do caminho GT (`_usd_prefix`/`to_mc_bars`/`fill_gaps`), nunca uma regra nova -- e
        nunca reagenda/encerra por conta propria (ver comentario em `_refresh_core`), so preenche
        candle pra deteccao/paper nao atrasarem junto. No maximo 1 tentativa por (pool,tf) por hora
        (nunca martela DexPaprika a cada tick so porque continua pendente)."""
        if tf != "1h" or self.dexpaprika is None:
            return
        hora_boundary = (now // 3600) * 3600
        minutos = (now - hora_boundary) / 60.0
        if minutos < self._fallback_dexpaprika_min_pendente():
            return
        key = (row["pool"], tf)
        st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
        hora_marcador = int(hora_boundary)
        if st.get("fallback_pendencia_hora") == hora_marcador:
            return
        st["fallback_pendencia_hora"] = hora_marcador
        # PEDIDO 2026-10-29, item 2: registra a TENTATIVA em si (fonte + resultado) independente do
        # desfecho -- antes, uma chamada que nao trazia candle novo (ou que falhava) nao deixava
        # nenhum rastro em `self.sched`, entao o diagnostico do alerta mostrava "fonte: s/d" mesmo
        # depois do fallback ter sido tentado.
        try:
            cobriu = self._refresh_fallback_dexpaprika(self.storage.pr_pool(row["pool"]), tf, now)
            st["ultima_tentativa"] = now
            st["fonte"] = "dexpaprika_fallback"
            st["ultimo_erro"] = None if cobriu else "dexpaprika_sem_candle_novo"
            if cobriu:
                log.info("POS-RUNNER: fallback DexPaprika (>=%.0fmin pendente) cobriu %s %s",
                         self._fallback_dexpaprika_min_pendente(), row["symbol"], tf)
        except Exception:  # noqa: BLE001 - o fallback e so um extra, nunca pode piorar o ciclo
            st["ultima_tentativa"] = now
            st["fonte"] = "dexpaprika_fallback"
            st["ultimo_erro"] = "dexpaprika_falhou"
            log.exception("POS-RUNNER: fallback DexPaprika (pendencia) falhou em %s %s", row["symbol"], tf)

    # -- candles e detector ------------------------------------------------------------------------
    def _detector(self, row: Any, tf: str, now: float) -> Optional[Detector]:
        key = (row["pool"], tf)
        det = self.dets.get(key)
        if det is not None or row["l_bc"] is None:
            return det
        det = Detector(self.params, tf, row["l_bc"], row["grad_ts"], self._created(row))
        for ts, o, h, l, c, v, filled in self.storage.pr_bars(row["pool"], tf):
            for ev in det.update(Bar(int(ts), o, h, l, c, v, bool(filled))):
                self._on_event(row, tf, det, ev, now)
        self.dets[key] = det
        return det

    def _detector_fecham(self, row: Any, tf: str, now: float) -> Optional[Detector]:
        """2a medida da queda (EMENDA 2026-10-16): MESMOS candles (`pr_bars`), so Params diferente -- so
        paper/CSV, nunca alerta (ver `_on_event_fecham`/`_entry(..., alerts=False)`)."""
        key = (row["pool"], tf)
        det = self.dets_fecham.get(key)
        if det is not None or row["l_bc"] is None:
            return det
        label = f"{tf}_fecham"
        det = Detector(self.params_fecham, tf, row["l_bc"], row["grad_ts"], self._created(row))
        for ts, o, h, l, c, v, filled in self.storage.pr_bars(row["pool"], tf):
            for ev in det.update(Bar(int(ts), o, h, l, c, v, bool(filled))):
                self._on_event_fecham(row, label, det, ev, now)
        self.dets_fecham[key] = det
        return det

    @staticmethod
    def _created(row: Any) -> Optional[float]:
        value = LineageVerifier._info(row).get("criado_ts")
        return None if value is None else float(value)

    # -- POS-RUNNER-V1 ("regras do professor") -----------------------------------------------------
    def _detector_v1(self, row: Any, tf: str, now: float, pending: Sequence[Bar] = ()) -> Optional[DetectorV1]:
        """MESMOS candles (`pr_bars`) do V0. `dado_invalido` (item 3.6) e MC atual abaixo do piso (item 2.4)
        nunca criam o detector -- contados em `pr1_filtrados`, nunca um alerta. `pending`: candles ja
        calculados neste ciclo mas AINDA NAO persistidos em `pr_bars` (1a carga de um pool) -- sem isto a
        avaliacao da qualidade do 1o candle real ficaria sempre vazia (dado_invalido nunca gatilha)."""
        key = (row["pool"], tf)
        if key in self._v1_invalid:
            return None
        det = self.dets_v1.get(key)
        if det is not None or row["l_bc"] is None:
            return det
        existing = self.storage.pr_bars(row["pool"], tf)
        bars = [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing] + list(pending)
        qual = avaliar_qualidade(bars, self.params_v1)
        if not qual.valido:
            self._v1_invalid.add(key)
            self.storage.pr1_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "dado_invalido",
                                          qual.motivo, self.version_v1)
            return None
        self._v1_suspeito[key] = qual.suspeito
        if qual.suspeito and key not in self._v1_suspeito_logged:
            self._v1_suspeito_logged.add(key)
            self.storage.pr1_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "l_bc_suspeito",
                                          f"{qual.l_bc_robusto:.0f}", self.version_v1)
        mc_atual = bars[-1].close if bars else None
        if mc_atual is not None and mc_atual < self.params_v1.min_mc_usd:
            if row["pool"] not in self._v1_mc_baixo_logged:
                self._v1_mc_baixo_logged.add(row["pool"])
                self.storage.pr1_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "filtrado_mc_baixo",
                                              f"{mc_atual:.0f}", self.version_v1)
            return None   # MC pode crescer: nunca marca definitivo, so nao cria o detector por enquanto
        det = DetectorV1(self.params_v1, tf, row["l_bc"], row["grad_ts"], self._created(row))
        for ts, o, h, l, c, v, filled in existing:
            for ev in det.update(Bar(int(ts), o, h, l, c, v, bool(filled))):
                self._on_event_v1(row, tf, det, ev, now)
        self.dets_v1[key] = det
        return det

    def _detector_v2(self, row: Any, tf: str, now: float, pending: Sequence[Bar] = ()) -> Optional[DetectorV1]:
        """PEDIDO CONSOLIDADO FASE 2: copia EXATA de `_detector_v1`, so troca params/estado/tabelas pela
        versao V2 (`self.params_v2`/`self.dets_v2`/`self.version_v2`/`pr2_*`) -- MESMO detector
        (`DetectorV1`), MESMOS candles (`pr_bars`), nenhum codigo novo de deteccao."""
        key = (row["pool"], tf)
        if key in self._v2_invalid:
            return None
        det = self.dets_v2.get(key)
        if det is not None or row["l_bc"] is None:
            return det
        existing = self.storage.pr_bars(row["pool"], tf)
        bars = [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing] + list(pending)
        qual = avaliar_qualidade(bars, self.params_v2)
        if not qual.valido:
            self._v2_invalid.add(key)
            self.storage.pr2_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "dado_invalido",
                                          qual.motivo, self.version_v2)
            return None
        self._v2_suspeito[key] = qual.suspeito
        if qual.suspeito and key not in self._v2_suspeito_logged:
            self._v2_suspeito_logged.add(key)
            self.storage.pr2_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "l_bc_suspeito",
                                          f"{qual.l_bc_robusto:.0f}", self.version_v2)
        mc_atual = bars[-1].close if bars else None
        if mc_atual is not None and mc_atual < self.params_v2.min_mc_usd:
            if row["pool"] not in self._v2_mc_baixo_logged:
                self._v2_mc_baixo_logged.add(row["pool"])
                self.storage.pr2_add_filtrado(now, "solana", row["pool"], row["mint"], row["symbol"], "filtrado_mc_baixo",
                                              f"{mc_atual:.0f}", self.version_v2)
            return None
        det = DetectorV1(self.params_v2, tf, row["l_bc"], row["grad_ts"], self._created(row))
        for ts, o, h, l, c, v, filled in existing:
            for ev in det.update(Bar(int(ts), o, h, l, c, v, bool(filled))):
                self._on_event_v2(row, tf, det, ev, now)
        self.dets_v2[key] = det
        return det

    # -- PEDIDO (PARTE 2A) FASE 3: sombra dos filtros -------------------------------------------------
    def _sombra_abrir_slot(self, key: tuple[str, str]) -> bool:
        """SOMBRA_MAX_POOLS: teto de (pool,tf) com um detector sombra PARALELO (mc_baixo + queda_96_mais)
        ao mesmo tempo -- um (pool,tf) ja rastreado em QUALQUER um dos 2 nunca e recusado (so conta 1x);
        um candidato NOVO alem do teto e descartado (`pr_sombra_descarte_insert`), nunca enfileirado."""
        ativos = set(self.dets_sombra_mc) | set(self.dets_sombra_queda96)
        if key in ativos:
            return True
        if len(ativos) >= self.sombra_max_pools:
            self.storage.pr_sombra_descarte_insert(self.clock(), "teto_sombra_max_pools", key[0], key[1])
            return False
        return True

    def _sombra_safe(self, fn: Callable[..., Any], *args: Any, contexto: str, default: Any = None) -> Any:
        """INCIDENTE DE PRODUCAO 2026-10-29 (KIMCHIBULL/SHAVCOIN e outros): o GT pode devolver janelas
        de candles SOBREPOSTAS -- sem isto, um candle ja visto chegando de novo no detector sombra
        levantava `ValueError` (`detector_v1.py: "candles fora de ordem ou repetidos"`) direto dentro
        de `_refresh_core`, interrompendo o resto do ciclo daquele (pool,tf) ANTES do agendamento
        normal (`_schedule`) e da coleta de carteiras rodarem -- a V1/V2 em si nunca perderam candle
        (seu proprio processamento ja tinha terminado antes da sombra rodar), mas o pool caia no
        backoff generico de erro em vez do agendamento por calor. Agora QUALQUER excecao da sombra
        (construcao do detector OU alimentacao de candle, esperada ou nao) e so um AVISO no log --
        nunca interrompe o resto de `_refresh_core`."""
        try:
            return fn(*args)
        except Exception:
            log.warning("POS-RUNNER sombra (%s): erro inesperado, ignorado neste ciclo (nunca derruba o ciclo)",
                       contexto, exc_info=True)
            return default

    def _sombra_feed(self, det: Optional[DetectorV1], seq: Sequence[Bar], row: Any, tf: str, now: float,
                     motivo: str) -> None:
        """Alimenta `seq` (candles NOVOS desta chamada) no detector sombra, pulando qualquer candle com
        ts <= o ultimo ja processado por ESTE detector (idempotente -- janelas sobrepostas do GT nunca
        batem de novo aqui). Chamado so atraves de `_sombra_safe` (ver docstring la)."""
        if det is None:
            return
        for b in seq:
            if det.bars and b.ts <= det.bars[-1].ts:
                continue
            for ev in det.update(b):
                self._on_event_sombra(row, tf, ev, now, motivo)

    def _detector_sombra_mc(self, row: Any, tf: str, now: float, pending: Sequence[Bar] = ()) -> Optional[DetectorV1]:
        """Sombra de `filtrado_mc_baixo`: `DetectorV1` NUNCA le `min_mc_usd` (esse piso e aplicado so FORA,
        em `_detector_v1`) -- entao o MESMO detector/params da V1, alimentado em paralelo enquanto o
        detector OFICIAL ainda nao existe (MC atual < piso), mede se o gatilho teria disparado apesar
        disso. Nunca vira sinal real, nunca alerta, nunca entra na banca (ver `_on_event_sombra`).
        Quando o MC real cruza o piso, `_detector_v1` cria o detector OFICIAL com a MESMA janela de
        candles e esta sombra para (libera o slot do teto -- nunca compete/duplica com o oficial)."""
        key = (row["pool"], tf)
        if self.dets_v1.get(key) is not None:
            self.dets_sombra_mc.pop(key, None)
            return None
        if key in self._v1_invalid or row["l_bc"] is None:
            return None
        det = self.dets_sombra_mc.get(key)
        if det is not None:
            return det
        if not self._sombra_abrir_slot(key):
            return None
        existing = self.storage.pr_bars(row["pool"], tf)
        bars = [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing] + list(pending)
        qual = avaliar_qualidade(bars, self.params_v1)
        if not qual.valido:
            return None
        det = DetectorV1(self.params_v1, tf, row["l_bc"], row["grad_ts"], self._created(row))
        self._sombra_feed(det, [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing],
                          row, tf, now, "filtrado_mc_baixo")
        self.dets_sombra_mc[key] = det
        return det

    def _detector_sombra_queda96(self, row: Any, tf: str, now: float, pending: Sequence[Bar] = ()) -> Optional[DetectorV1]:
        """Sombra `queda_96_mais`: MESMOS parametros da V2 (que ja estende `drop_max` a 96%), so com
        `drop_max` ainda mais largo (99,5%, `self._params_sombra_queda96`) -- mede candidatos que a
        V1/V2 matariam como ONDA_INVALIDA entre 96% e 99,5% de queda, mas que teriam gerado gatilho.
        Detector PARALELO sempre ligado (independente do mc_baixo), tambem sujeito ao teto
        SOMBRA_MAX_POOLS; `_on_event_sombra` filtra pra so contar queda_pct > 96% (abaixo disso ja e
        territorio real da V2, nunca duplicado aqui)."""
        key = (row["pool"], tf)
        det = self.dets_sombra_queda96.get(key)
        if det is not None or row["l_bc"] is None:
            return det
        if not self._sombra_abrir_slot(key):
            return None
        existing = self.storage.pr_bars(row["pool"], tf)
        bars = [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing] + list(pending)
        qual = avaliar_qualidade(bars, self._params_sombra_queda96)
        if not qual.valido:
            return None
        det = DetectorV1(self._params_sombra_queda96, tf, row["l_bc"], row["grad_ts"], self._created(row))
        self._sombra_feed(det, [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in existing],
                          row, tf, now, "queda_96_mais")
        self.dets_sombra_queda96[key] = det
        return det

    def _on_event_sombra(self, row: Any, tf: str, ev: EventV1, now: float, motivo: str) -> None:
        """Grava 1 linha em `pr_sombra` (versao=`sombra:<motivo>`) por candidato que TERIA gatilhado --
        so ENTRADA (do detector sombra PARALELO) ou FORA_DA_IDADE (do detector OFICIAL da V1, chamado
        direto de `_on_event_v1` com motivo="filtrado_idade" -- reusa o evento que a V1 ja emite, nunca
        duplica deteccao). `queda_96_mais` so conta quando `queda_pct` > 96% (<=96% ja e territorio
        real da V2). Idempotente pela UNIQUE (versao,chain,pool,tf,ts_fechamento); dispara o aviso
        curto do Telegram so para `queda_96_mais` (ver `_alerta_sombra_queda96`)."""
        if self.sem_sombra or ev.kind not in ("ENTRADA", "FORA_DA_IDADE"):
            return
        queda_pct = ev.data.get("queda_pct")
        if motivo == "queda_96_mais" and (queda_pct is None or queda_pct <= 96.0):
            return
        if motivo == "filtrado_idade":
            # V1 e V2 usam a MESMA idade MINIMA (2 dias), so o TETO diverge (V1: 7d; V2: ~sem teto) --
            # um candidato acima do teto da V1 ja e territorio REAL da V2 (gera ENTRADA de verdade ali,
            # nunca sombra); so idade abaixo do minimo compartilhado e genuinamente barrada pelas 2.
            idade = ev.data.get("idade_dias")
            if idade is None or idade >= self.params_v1.age_window_days[0]:
                return
        pool, mint, symbol = row["pool"], row["mint"], row["symbol"]
        versao = f"sombra:{motivo}"
        ts_fechamento = int(ev.decision_ts)
        if self.storage.pr_sombra_get(versao, "solana", pool, tf, ts_fechamento) is not None:
            return
        info = json.loads(row["info"] or "{}")
        row_insert = {
            "versao": versao, "chain": "solana", "pool": pool, "tf": tf, "mint": mint, "symbol": symbol,
            "ts_fechamento": ts_fechamento, "gatilho": json.dumps(list(ev.data.get("gatilho") or [])),
            "event_json": event_v1_to_json(ev), "entry_price": ev.data.get("close"), "stop": ev.data.get("stop"),
            "topo": ev.data.get("TOPO"), "s_suporte": ev.data.get("S"), "r_resistencia": ev.data.get("R"),
            "risco_pct": ev.data.get("risco_pct"), "queda_pct": queda_pct, "liquidez_usd": info.get("liq_usd"),
            "status": "aberto", "criado_ts": now, "atualizado_ts": now,
            **self._contexto_execucao(row, ev),
        }
        sombra_id = self.storage.pr_sombra_insert(row_insert)
        if sombra_id is None:
            return
        if motivo == "queda_96_mais":
            self._alerta_sombra_queda96(row, ev)

    def _alerta_sombra_queda96(self, row: Any, ev: EventV1) -> None:
        """Unica excecao de Telegram para sombra (item da FASE 3): aviso curto, sem botoes de entrada,
        fora de /relatorio e da banca -- so marca o candidato pro operador, nunca convida a agir."""
        info = json.loads(row["info"] or "{}")
        text = telegram_v1.sombra_queda96_text(
            row["symbol"], ev.data.get("queda_pct"), ev.data.get("risco_pct"), info.get("liq_usd"))
        self._send(text)

    def _update_sombra(self, now: float) -> None:
        """Progride sinais sombra 'aberto' ate 'fechado'/'cancelado' com os candles JA em `pr_bars`
        (zero chamada nova) -- MESMO `simulate_v1` da V1 (reusa `self.params_v1`: os campos que
        `simulate_v1` realmente le -- atr_period/power_atr_mult/exhaustion_*/tp1_frac -- sao IDENTICOS
        entre V1/V2/sombra_queda96, so drop_max/age_window mudam, e esses nunca influenciam a
        simulacao do trade em si). Chamado na MESMA cadencia horaria de `_refresh_baselines` (ver
        `tick`). SEM_SOMBRA=1 pula por completo."""
        if self.sem_sombra:
            return
        for s in self.storage.pr_sombra_signals(status="aberto"):
            pool_row = self.storage.pr_pool(s["pool"])
            if pool_row is None or pool_row["l_bc"] is None:
                continue
            bars_raw = self.storage.pr_bars(s["pool"], s["tf"])
            if not bars_raw:
                continue
            bars = [Bar(int(ts), o, h, l, c, v, bool(filled)) for ts, o, h, l, c, v, filled in bars_raw]
            try:
                ev = event_v1_from_json(s["event_json"])
            except (TypeError, ValueError, KeyError):
                continue
            dex = DEX_OF_LAUNCHPAD.get(pool_row["launchpad"], "desconhecido")
            res = simulate_v1(bars, ev, self.params_v1, self.costs, dex, pool_row["l_bc"], self._sol_at())
            if res.entry_price is not None and s["entry_price"] != res.entry_price:
                self.storage.pr_sombra_update(s["id"], entry_price=res.entry_price, atualizado_ts=now)
            if res.status == "cancelado":
                self.storage.pr_sombra_update(s["id"], status="cancelado", reason=res.reason,
                                              closed_ts=now, atualizado_ts=now)
                continue
            if res.status != "fechado":
                continue
            exit_leg = res.legs[-1] if res.legs else None
            self.storage.pr_sombra_update(
                s["id"], status="fechado", exit_full_price=exit_leg.price if exit_leg else None,
                exit_full_ts=exit_leg.ts if exit_leg else None, result_net=res.net_ret, reason=res.reason,
                closed_ts=now, atualizado_ts=now,
            )

    def _excluded_accounts_v1(self, row: Any) -> frozenset[str]:
        return self.adapter.excluded_accounts(row["pool"], row["mint"], row["launchpad"])

    def _vamp_search(self, symbol: str) -> list[dict]:
        """GT `/search/pools?query=<ticker>` (item 2.7 + INTERPRETACOES.md #4): melhor esforco, nunca inventa
        dado (qualquer falha/forma inesperada devolve lista vazia, nunca levanta)."""
        try:
            data = self.http.get_json("search/pools", {"query": symbol}, max_wait_s=10.0)
        except (ApiError, RateLimited):
            return []
        out: list[dict] = []
        items = (data or {}).get("data") if isinstance(data, dict) else None
        for item in items or []:
            try:
                attrs = item.get("attributes") or {}
                out.append({
                    "symbol": clean_text(attrs.get("name", "").split("/")[0], 40),
                    "created_ts": parse_iso(attrs.get("pool_created_at")),
                    "mc_usd": to_float(attrs.get("market_cap_usd") or attrs.get("fdv_usd")),
                })
            except (AttributeError, TypeError, ValueError):
                continue
        return out

    def _key_v1(self, kind: str, *parts: Any) -> str:
        return ":".join(["v1", kind, self.version_v1, *(str(p) for p in parts)])

    def _keyboard_v1(self, row: Any, signal_id: Optional[int] = None) -> dict:
        kb = telegram_v1.keyboard(self.adapter, row["mint"], row["pool"], "sol", self.dexscreener_slug)
        if signal_id is not None:
            # FASE 3: botoes de feedback (👍/👎/📝) SO no alerta de ENTRADA (quem chama passa o signal_id) --
            # WATCHLIST/INVALIDADO nunca tem sinal pr1_signals associado, continuam sem a linha extra.
            kb = telegram_v1.with_feedback(kb, signal_id)
        return kb

    def _key_v2(self, kind: str, *parts: Any) -> str:
        return ":".join(["v2", kind, self.version_v2, *(str(p) for p in parts)])

    def _keyboard_v2(self, row: Any) -> dict:
        # PEDIDO CONSOLIDADO FASE 2: sem botoes de feedback (FASE 3 e um recurso so da V1 por ora).
        return telegram_v1.keyboard(self.adapter, row["mint"], row["pool"], "sol", self.dexscreener_slug)

    def _conferencia_cruzada_dexpaprika(self, row: Any, tf: str, ev: EventV1) -> None:
        """PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 3b: so log, nunca influencia a decisao. O candle GT
        comparado e o RAW (token, pre-conversao de MC) da MESMA janela ja usada nesta mesma rodada -- a
        leitura do cache de disco do `OhlcvStore` nao gasta chamada nova (mesma chave pool/tf/currency/
        side ja coberta)."""
        if self.dexpaprika is None or not self.dexpaprika.deve_conferir():
            return
        try:
            info = json.loads(row["info"] or "{}")
            step = tf_seconds(tf)
            raw = self.ohlcv.history(row["pool"], tf, ev.ts, ev.ts + step, currency="token", side=info.get("side", "base"))
            candle_gt = next((b for b in raw if b.ts == ev.ts), None)
            if candle_gt is None:
                return
            divergencias = self.dexpaprika.conferir(self.ctx.gt_network, row["pool"], tf, candle_gt)
            for d in divergencias:
                self.storage.pr1_dexpaprika_divergencia_insert(
                    self.clock(), "solana", row["pool"], row["mint"], row["symbol"], tf, int(candle_gt.ts),
                    d.campo, d.valor_gt, d.valor_dexpaprika, d.diff_pct, self.version_v1)
        except Exception:  # noqa: BLE001 - conferencia e so log, nunca pode travar o ciclo
            log.exception("POS-RUNNER: conferencia cruzada DexPaprika falhou em %s %s", row["symbol"], tf)

    def _on_event_v1(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        pool = row["pool"]
        tracked = (row["added_ts"] is not None and ev.decision_ts >= row["added_ts"]
                   and self.version_v1_start is not None and ev.decision_ts >= self.version_v1_start)
        if not tracked:
            return
        if ev.kind in ("WATCHLIST", "ENTRADA"):
            self._conferencia_cruzada_dexpaprika(row, tf, ev)
        if ev.kind == "ENTRADA":
            self._entry_v1(row, tf, det, ev, now)
            return
        if ev.kind == "FORA_DA_IDADE":
            self.storage.pr1_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "filtrado_idade",
                                          f"{ev.data.get('idade_dias')}", self.version_v1)
            self._on_event_sombra(row, tf, ev, now, "filtrado_idade")
            return
        late = self._late(now, ev.decision_ts, max(900.0, float(det.step)))
        if late:
            return
        if ev.kind == "WATCHLIST":
            if self.storage.pr_alert_once(self._key_v1("w", pool, tf, ev.data.get("zona")), now):
                text = telegram_v1.watchlist_text(self.chain_name, row["symbol"], ev.data["S"], ev.data["R"], ev.data["n_testes"])
                self._send(text, self._keyboard_v1(row))
        elif ev.kind == "ONDA_INVALIDA":
            if self.storage.pr_alert_once(self._key_v1("x", pool, tf, ev.data.get("onda")), now):
                motivo = str(ev.data.get("motivo", ""))
                text = telegram_v1.invalidado_text(self.chain_name, row["symbol"], motivo)
                self._send(text, self._keyboard_v1(row))
                queda_pct = ev.data.get("queda_pct")
                # item 3 do pedido de ajustes de alerta/medicao: gravar a queda % MAXIMA (desde o pico da
                # onda, igual ao campo que a V1 ja usa pra decidir a invalidacao -- nunca inventa outro
                # numero) junto do motivo, nunca so o motivo sozinho; so medicao, nunca muda a decisao.
                valor = motivo if queda_pct is None else f"{motivo} | queda_maxima={queda_pct:.1f}%"
                self.storage.pr1_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "invalidado",
                                              valor, self.version_v1)
                # item 4 da FASE 2 de medicao/UX: contador SEPARADO, nunca alerta, so pra faixa de
                # queda 90-96% -- diagnostico de quao perto do limiar atual (drop_max=90%) os
                # candidatos descartados ficam; nao muda nem promete mudar o limiar em si.
                if queda_pct is not None and 90.0 <= queda_pct < 96.0:
                    mc = ev.data.get("P_peak")
                    valor = f"MC={fmt_usd(mc) if mc is not None else 's/d'} queda={queda_pct:.1f}%"
                    self.storage.pr1_add_filtrado(now, "solana", pool, row["mint"], row["symbol"],
                                                  "filtrado_queda_90_96", valor, self.version_v1)

    @staticmethod
    def _contexto_execucao(row: Any, ev: EventV1, holders: Optional[HolderCheck] = None) -> dict[str, Any]:
        """PARTE 2A FASE 4: colunas de contexto/execucao na ENTRADA -- so dado JA disponivel neste
        exato momento (zero chamada nova): `ev.data` (gatilho/zona, ja calculado pelo detector),
        `info` do pool (`vol_h24_usd`/`n_txs_h24`, congelados na descoberta -- ver `offer()`) e
        `holders` (RPC ja chamado por outro motivo, nunca de novo aqui -- `None` na sombra, que nunca
        chama `adapter.holders()` so para preencher isto: `holder_top1_pct` fica None la, nunca uma
        chamada extra so pra medicao). `holders_count` fica sempre None -- nem o RPC nem o GT devolvem
        uma contagem agregada de holders no que ja e chamado hoje (ver INTERPRETACOES.md, nunca um
        numero inventado)."""
        info = json.loads(row["info"] or "{}")
        vol_h24 = info.get("vol_h24_usd")
        n_txs_h24 = info.get("n_txs_h24")
        liq_usd = info.get("liq_usd")
        return {
            "dia_semana": dia_semana_brt(ev.decision_ts), "idade_dias": ev.data.get("idade_dias"),
            "mc_na_entrada": ev.data.get("close"), "volume_24h": vol_h24, "caixa_candles": ev.data.get("box_len"),
            "holder_top1_pct": holders.top_holder_pct if holders is not None else None,
            "slippage_estimado_pct": (100.0 * MAO_SIMULADA_USD / liq_usd) if liq_usd else None,
            "n_txs_24h": n_txs_h24, "ticket_medio_usd": (vol_h24 / n_txs_h24) if vol_h24 and n_txs_h24 else None,
            "holders_count": None,
        }

    @staticmethod
    def _r_liquido_estimado(signal: Any, res: Any) -> Optional[float]:
        """PARTE 2A FASE 4: MESMO retorno BRUTO do trade oficial (`res.gross_ret`), so troca o custo
        OFICIAL (`CostModel`, intocado) pelo modelo simples de slippage estimado gravado na ENTRADA
        (`slippage_estimado_pct`, 1 perna de entrada + 1 de saida) -- puramente diagnostico, NUNCA
        sobrescreve `result_net`."""
        slip = signal["slippage_estimado_pct"]
        if slip is None or res.gross_ret is None:
            return None
        return res.gross_ret - 2.0 * (slip / 100.0)

    def _entry_v1(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        pool, mint, symbol = row["pool"], row["mint"], row["symbol"]
        ts_fechamento = int(ev.decision_ts)
        signal = self.storage.pr1_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
        if signal is None:
            gatilho = list(ev.data.get("gatilho") or [])
            tags: list[str] = []
            if ev.data.get("risco_fora_da_faixa"):
                tags.append("risco_fora_da_faixa")
            # item 4 da FASE 2 de medicao/UX: so atributo (nunca filtra/descarta) -- consolidacao com
            # >= 48 candles do tf principal (1h) = pelo menos 2 dias de base antes do rompimento.
            if tf == "1h" and (ev.data.get("box_len") or 0) >= 48:
                tags.append("base_ge_2d")
            if self._v1_suspeito.get((pool, tf)):
                tags.append("l_bc_suspeito")
            holders = self.adapter.holders(mint, self._excluded_accounts_v1(row))
            if holders.tag:
                tags.append(holders.tag)
            # PEDIDO 2026-10-27 (H9): cruza os MESMOS holders resolvidos acima (sem chamada RPC
            # extra) contra a lista de carteiras "pro" -- so medicao, nunca filtra/altera o sinal.
            # SEM_CARTEIRAS=1 desliga ate este cruzamento (nunca so a tabela de snapshot).
            n_carteiras_pro = n_pessoas_pro = None
            if not self.sem_carteiras:
                owners_v1 = [o for o, _pct in holders.top_holders]
                n_carteiras_pro, n_pessoas_pro, _grupos_v1 = carteiras_pro.pessoas_presentes(owners_v1, self._mapa_carteiras_pro)
            # item 2 da FASE 2 de medicao/UX: 1 chamada RPC por mint (cacheada no adapter) -- nunca
            # filtra/descarta o sinal, so preenche dado.
            authority = self.adapter.authorities(mint)
            vamp = self.adapter.vamp_risk(symbol, ev.data.get("P_peak"), self._vamp_search)
            if vamp.tag:
                tags.append(vamp.tag)
            janela = "janela_ouro" if na_janela_ouro(ev.decision_ts, *self.params_v1.janela_ouro_brt) else "fora_da_janela"
            info = json.loads(row["info"] or "{}")
            row_insert = {
                "chain": "solana", "pool": pool, "tf": tf, "evento": "ENTRADA", "ts_fechamento": ts_fechamento,
                "mint": mint, "symbol": symbol, "launchpad": row["launchpad"], "dex": row["dex"],
                "versao_config_v1": self.version_v1, "gatilho": json.dumps(gatilho), "tags": json.dumps(tags),
                "janela_ouro": janela, "hora_brt": hora_brt(ev.decision_ts), "origem": info.get("fonte", ""),
                "teste_vol_ratio": ev.data.get("teste_vol_ratio"), "event_json": event_v1_to_json(ev), "status": "aberto",
                "entry_price": ev.data.get("close"), "stop": ev.data.get("stop"), "topo": ev.data.get("TOPO"),
                "s_suporte": ev.data.get("S"), "r_resistencia": ev.data.get("R"), "holders_tag": holders.tag,
                # instrumentacao de medicao (nunca entra em regra/filtro/tamanho):
                "liquidez_usd": info.get("liq_usd"), "ts_fechamento_candle": ts_fechamento,
                "retorno_sol_dia": self._retorno_sol_dia_v1(ts_fechamento),
                "mint_authority": authority.mint_authority, "freeze_authority": authority.freeze_authority,
                "token_signal_seq": self.storage.pr1_token_next_seq(mint),
                "fonte_candle": self._fonte_candle_atual,
                # DIAGNOSTICO 2026-10-27: snapshot do preco PROVISORIO do alerta -- nunca sobrescrito
                # (ver comentario da coluna em storage.py). So diagnostico/exclusao, nunca lido por V1.
                "entry_price_alerta": ev.data.get("close"),
                # PATCH 2026-10-27: qual versao do gate de qualidade de candle estava ativa quando
                # este sinal foi decidido (qualidade_candle.py -- fora do hash de ParamsV1).
                "qualidade_versao": qualidade_candle.QUALIDADE_VERSAO,
                # PEDIDO 2026-10-27 (H9): carteiras_pro_presentes agora guarda n_carteiras_pro (a
                # CONTAGEM de enderecos, nao um booleano -- H8 le ">= 1"); NULL se holders indisponivel
                # (nunca inventa um 0 quando o dado nao existe).
                "carteiras_pro_presentes": n_carteiras_pro if holders.tag != "holders_indisponivel" else None,
                "n_pessoas_pro": n_pessoas_pro if holders.tag != "holders_indisponivel" else None,
                **self._contexto_execucao(row, ev, holders),
            }
            signal_id = self.storage.pr1_insert_signal(row_insert)
            if signal_id is None:   # corrida rara (outro ciclo/processo ja inseriu): usa o que ja existe
                signal = self.storage.pr1_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
                if signal is None:
                    return
                signal_id = signal["id"]
            self._registrar_snapshot_carteiras("entrada", pool, mint, holders, now, versao="v1", entry_id=signal_id)
            signal = self.storage.pr1_signal(signal_id)
        if signal is None or signal["tg_message_id"]:
            return
        if self._late(now, ev.decision_ts, max(300.0, det.step / 2.0)):
            return
        if not self.storage.pr_alert_once(self._key_v1("e", pool, tf, ts_fechamento), now):
            return
        # instrumentacao de medicao: momento em que o bot DECIDIU alertar (antes do envio em si);
        # ts_envio_telegram (abaixo) e o momento em que o Telegram CONFIRMOU o envio.
        self.storage.pr1_update_signal(signal["id"], ts_alerta=self.clock())
        tags = json.loads(signal["tags"] or "[]")
        gatilho = json.loads(signal["gatilho"] or "[]")
        age_h = None if ev.data.get("idade_dias") is None else ev.data["idade_dias"] * 24.0
        banca = self._bankroll_v1_ledger(tf).state.banca
        text = telegram_v1.entrada_text(
            self.chain_name, symbol, ev.data.get("P_peak"), age_h or 0.0, signal["janela_ouro"] or "fora_da_janela",
            gatilho, tags, signal["entry_price"], signal["stop"], signal["topo"], tamanho_posicao_usd(banca, self.params_v1),
            mint, liquidez_usd=signal["liquidez_usd"], mint_authority=signal["mint_authority"],
            freeze_authority=signal["freeze_authority"],
        )
        mid = self._send(text, self._keyboard_v1(row, signal["id"]))
        if mid is not None:
            agora = self.clock()
            # ts_envio_telegram duplica alert_ts (MESMO instante, nome mais claro p/ instrumentacao) --
            # alert_ts fica como estava, nenhum consumidor existente precisa mudar.
            self.storage.pr1_update_signal(signal["id"], tg_message_id=mid, alert_ts=agora, ts_envio_telegram=agora)

    # PATCH 2026-10-27 (diagnostico McRib): risco real (fill real vs stop) < 3% = `risco_irrealista`
    # -- tag/registro, NUNCA bloqueio silencioso (pedido explicito do operador).
    RISCO_IRREALISTA_MIN_PCT = 3.0

    def _confirmar_entrada(self, signal: Any, res: TradeResultV1, now: float, update_signal: Callable[..., None],
                           key_kind: Callable[..., str], keyboard: dict) -> None:
        """PATCH 2026-10-27: manda 'ENTRADA CONFIRMADA' 1x, quando o fill real e conhecido
        (`res.entry_price`), retificando o preco PROVISORIO do alerta ENTRADA original (nunca o
        reescreve, so responde com o fill/stop/risco real). Nunca cancela/bloqueia por risco baixo."""
        if res.entry_price is None or res.status == "cancelado" or not res.risk_frac or res.risk_frac <= 0:
            return
        risco_real_pct = 100.0 * res.risk_frac
        tags = json.loads(signal["tags"] or "[]")
        if risco_real_pct < self.RISCO_IRREALISTA_MIN_PCT and "risco_irrealista" not in tags:
            tags.append("risco_irrealista")
            update_signal(signal["id"], tags=json.dumps(tags))
        if not signal["tg_message_id"] or not self.storage.pr_alert_once(key_kind("confirma", signal["id"]), now):
            return
        text = telegram_v1.entrada_confirmada_text(self.chain_name, signal["symbol"], res.entry_price, res.stop,
                                                   risco_real_pct, risco_irrealista="risco_irrealista" in tags)
        self._send(text, keyboard, reply_to=signal["tg_message_id"])

    def _confirmar_entrada_v1(self, signal: Any, res: TradeResultV1, row: Any, now: float) -> None:
        self._confirmar_entrada(signal, res, now, self.storage.pr1_update_signal, self._key_v1,
                                self._keyboard_v1(row, signal["id"]))

    def _confirmar_entrada_v2(self, signal: Any, res: TradeResultV1, row: Any, now: float) -> None:
        self._confirmar_entrada(signal, res, now, self.storage.pr2_update_signal, self._key_v2,
                                self._keyboard_v2(row))

    def _update_paper_v1(self, row: Any, tf: str, det: DetectorV1, now: float) -> None:
        for signal in self.storage.pr1_signals(status="aberto", pool=row["pool"], tf=tf):
            if signal["versao_config_v1"] != self.version_v1:
                continue
            ev = event_v1_from_json(signal["event_json"])
            dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
            confiavel = self._candle_confiavel_cb(det.bars, row["pool"], ev.data.get("TOPO"))
            res = simulate_v1(det.bars, ev, self.params_v1, self.costs, dex, row["l_bc"], self._sol_at(),
                              candle_confiavel=confiavel)
            if res.entry_price is not None and signal["entry_price"] != res.entry_price:
                self.storage.pr1_update_signal(signal["id"], entry_price=res.entry_price)
            self._confirmar_entrada_v1(signal, res, row, now)
            if res.status == "cancelado":
                self.storage.pr1_update_signal(signal["id"], status="cancelado", reason=res.reason, closed_ts=now)
                continue
            tp1_leg = next((leg for leg in res.legs if leg.reason == "tp1"), None)
            if tp1_leg is not None and signal["tp1_price"] is None:
                if signal["tg_message_id"] and self.storage.pr_alert_once(self._key_v1("tp1", signal["id"]), now):
                    text = telegram_v1.tp1_text(self.chain_name, signal["symbol"], tp1_leg.price, res.entry_price or signal["entry_price"])
                    # item 1 da FASE 2 de medicao/UX: TP1/EXIT FULL ganham os MESMOS botoes de
                    # terminal/DexScreener do alerta de ENTRADA (antes so tinham feedback), para o
                    # operador nunca precisar rolar pra cima pra achar o link.
                    self._send(text, self._keyboard_v1(row, signal["id"]), reply_to=signal["tg_message_id"])
                self.storage.pr1_update_signal(signal["id"], tp1_price=tp1_leg.price, tp1_ts=tp1_leg.ts)
            if res.status != "fechado":
                continue
            exit_leg = res.legs[-1] if res.legs else None
            if exit_leg is not None and signal["tg_message_id"] and self.storage.pr_alert_once(self._key_v1("x", signal["id"]), now):
                text = telegram_v1.exit_full_text(self.chain_name, signal["symbol"], exit_leg.price,
                                                  res.entry_price or signal["entry_price"], exit_leg.reason)
                self._send(text, self._keyboard_v1(row, signal["id"]), reply_to=signal["tg_message_id"])
            self.storage.pr1_update_signal(
                signal["id"], status="fechado", exit_full_price=exit_leg.price if exit_leg else None,
                exit_full_ts=exit_leg.ts if exit_leg else None, result_net=res.net_ret, reason=res.reason,
                tempo_h=None if res.bars_held is None else res.bars_held * det.step / 3600.0, closed_ts=now,
                r_exit_open_seguinte=res.r_exit_open_seguinte,
                r_liquido_estimado=self._r_liquido_estimado(signal, res),
            )
            self._update_bankroll_v1(row, tf, det, signal, now)

    def _bankroll_v1_ledger(self, tf: str) -> BankrollLedgerV1:
        ledger = self._bankroll_v1.get(tf)
        if ledger is None:
            saved = self.storage.pr1_bankroll_load(tf, self.version_v1)
            from .bankroll_v1 import BankrollStateV1
            state = BankrollStateV1.from_json(saved) if saved else None
            ledger = BankrollLedgerV1(self.params_v1, self.costs, state)
            self._bankroll_v1[tf] = ledger
        return ledger

    def _update_bankroll_v1(self, row: Any, tf: str, det: DetectorV1, signal: Any, now: float) -> None:
        ev = event_v1_from_json(signal["event_json"])
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        meta = {"token": row["symbol"], "contrato": row["mint"], "launchpad": row["launchpad"], "tf": tf}
        ledger = self._bankroll_v1_ledger(tf)
        linha = ledger.step(det.bars, ev, dex, row["l_bc"], self._sol_at(), meta)
        if linha is None:
            return
        if self.storage.pr1_bankroll_append(tf, self.version_v1, signal["id"], linha, now):
            self.storage.pr1_bankroll_save(tf, self.version_v1, ledger.state.to_json())

    # -- PEDIDO CONSOLIDADO FASE 2: POS-RUNNER-V2 ("regras do professor", so 2 parametros diferentes) ---------
    def _on_event_v2(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        pool = row["pool"]
        tracked = (row["added_ts"] is not None and ev.decision_ts >= row["added_ts"]
                  and self.version_v2_start is not None and ev.decision_ts >= self.version_v2_start)
        if not tracked:
            return
        if ev.kind == "ENTRADA":
            self._entry_v2(row, tf, det, ev, now)
            return
        if ev.kind == "FORA_DA_IDADE":
            self.storage.pr2_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "filtrado_idade",
                                          f"{ev.data.get('idade_dias')}", self.version_v2)
            self._on_event_sombra(row, tf, ev, now, "filtrado_idade")
            return
        late = self._late(now, ev.decision_ts, max(900.0, float(det.step)))
        if late:
            return
        if ev.kind == "WATCHLIST":
            if self.storage.pr_alert_once(self._key_v2("w", pool, tf, ev.data.get("zona")), now):
                text = telegram_v1.watchlist_text(self.chain_name, row["symbol"], ev.data["S"], ev.data["R"], ev.data["n_testes"])
                self._send(text, self._keyboard_v2(row))
        elif ev.kind == "ONDA_INVALIDA":
            if self.storage.pr_alert_once(self._key_v2("x", pool, tf, ev.data.get("onda")), now):
                motivo = str(ev.data.get("motivo", ""))
                text = telegram_v1.invalidado_text(self.chain_name, row["symbol"], motivo)
                self._send(text, self._keyboard_v2(row))
                queda_pct = ev.data.get("queda_pct")
                valor = motivo if queda_pct is None else f"{motivo} | queda_maxima={queda_pct:.1f}%"
                self.storage.pr2_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "invalidado",
                                              valor, self.version_v2)

    def _entry_v2(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        """MESMA logica de `_entry_v1`, so troca a tabela/versao -- EXCETO o alerta: se a V1 JA tem uma
        ENTRADA no MESMO (pool,tf,ts_fechamento) (candle idêntico -- a V1 roda ANTES da V2 no mesmo
        `seq`, sempre resolvida primeiro), a V2 NUNCA manda um alerta cheio novo (evita duplicar) -- so
        uma nota curta de confirmacao em resposta ao alerta da V1, tag "V1+V2" (`so_v2=False`). Sem
        match, alerta cheio proprio, tag "SOMENTE V2 (experimental)" (`so_v2=True`)."""
        pool, mint, symbol = row["pool"], row["mint"], row["symbol"]
        ts_fechamento = int(ev.decision_ts)
        signal = self.storage.pr2_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
        sinal_v1 = self.storage.pr1_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
        so_v2 = sinal_v1 is None or sinal_v1["versao_config_v1"] != self.version_v1
        if signal is None:
            gatilho = list(ev.data.get("gatilho") or [])
            tags: list[str] = []
            if ev.data.get("risco_fora_da_faixa"):
                tags.append("risco_fora_da_faixa")
            if tf == "1h" and (ev.data.get("box_len") or 0) >= 48:
                tags.append("base_ge_2d")
            if self._v2_suspeito.get((pool, tf)):
                tags.append("l_bc_suspeito")
            holders = self.adapter.holders(mint, self._excluded_accounts_v1(row))
            if holders.tag:
                tags.append(holders.tag)
            n_carteiras_pro = n_pessoas_pro = None
            if not self.sem_carteiras:
                owners_v2 = [o for o, _pct in holders.top_holders]
                n_carteiras_pro, n_pessoas_pro, _grupos_v2 = carteiras_pro.pessoas_presentes(owners_v2, self._mapa_carteiras_pro)
            authority = self.adapter.authorities(mint)
            vamp = self.adapter.vamp_risk(symbol, ev.data.get("P_peak"), self._vamp_search)
            if vamp.tag:
                tags.append(vamp.tag)
            janela = "janela_ouro" if na_janela_ouro(ev.decision_ts, *self.params_v2.janela_ouro_brt) else "fora_da_janela"
            info = json.loads(row["info"] or "{}")
            row_insert = {
                "chain": "solana", "pool": pool, "tf": tf, "evento": "ENTRADA", "ts_fechamento": ts_fechamento,
                "mint": mint, "symbol": symbol, "launchpad": row["launchpad"], "dex": row["dex"],
                "versao_config_v2": self.version_v2, "gatilho": json.dumps(gatilho), "tags": json.dumps(tags),
                "janela_ouro": janela, "hora_brt": hora_brt(ev.decision_ts), "origem": info.get("fonte", ""),
                "teste_vol_ratio": ev.data.get("teste_vol_ratio"), "event_json": event_v1_to_json(ev), "status": "aberto",
                "entry_price": ev.data.get("close"), "stop": ev.data.get("stop"), "topo": ev.data.get("TOPO"),
                "s_suporte": ev.data.get("S"), "r_resistencia": ev.data.get("R"), "holders_tag": holders.tag,
                "liquidez_usd": info.get("liq_usd"), "ts_fechamento_candle": ts_fechamento,
                "retorno_sol_dia": self._retorno_sol_dia_v1(ts_fechamento),
                "mint_authority": authority.mint_authority, "freeze_authority": authority.freeze_authority,
                "token_signal_seq": self.storage.pr2_token_next_seq(mint),
                "fonte_candle": self._fonte_candle_atual, "so_v2": 1 if so_v2 else 0,
                "entry_price_alerta": ev.data.get("close"),
                "qualidade_versao": qualidade_candle.QUALIDADE_VERSAO,
                "carteiras_pro_presentes": n_carteiras_pro if holders.tag != "holders_indisponivel" else None,
                "n_pessoas_pro": n_pessoas_pro if holders.tag != "holders_indisponivel" else None,
                **self._contexto_execucao(row, ev, holders),
            }
            signal_id = self.storage.pr2_insert_signal(row_insert)
            if signal_id is None:
                signal = self.storage.pr2_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
                if signal is None:
                    return
                signal_id = signal["id"]
            self._registrar_snapshot_carteiras("entrada", pool, mint, holders, now, versao="v2", entry_id=signal_id)
            signal = self.storage.pr2_signal(signal_id)
        if signal is None or signal["tg_message_id"]:
            return
        if self._late(now, ev.decision_ts, max(300.0, det.step / 2.0)):
            return
        if not self.storage.pr_alert_once(self._key_v2("e", pool, tf, ts_fechamento), now):
            return
        self.storage.pr2_update_signal(signal["id"], ts_alerta=self.clock())
        tags = json.loads(signal["tags"] or "[]")
        gatilho = json.loads(signal["gatilho"] or "[]")
        age_h = None if ev.data.get("idade_dias") is None else ev.data["idade_dias"] * 24.0
        if so_v2:
            banca = self._bankroll_v2_ledger(tf).state.banca
            text = telegram_v1.entrada_text(
                self.chain_name, symbol, ev.data.get("P_peak"), age_h or 0.0, signal["janela_ouro"] or "fora_da_janela",
                gatilho, tags, signal["entry_price"], signal["stop"], signal["topo"], tamanho_posicao_usd(banca, self.params_v2),
                mint, liquidez_usd=signal["liquidez_usd"], mint_authority=signal["mint_authority"],
                freeze_authority=signal["freeze_authority"],
            ) + "\n⚠️ SOMENTE V2 (experimental)"
            mid = self._send(text, self._keyboard_v2(row))
        else:
            text = f"🔁 V2 CONFIRMA este sinal (tag: V1+V2) | config V2 {self.version_v2}"
            mid = self._send(text, reply_to=sinal_v1["tg_message_id"])
        if mid is not None:
            agora = self.clock()
            self.storage.pr2_update_signal(signal["id"], tg_message_id=mid, alert_ts=agora, ts_envio_telegram=agora)

    def _update_paper_v2(self, row: Any, tf: str, det: DetectorV1, now: float) -> None:
        for signal in self.storage.pr2_signals(status="aberto", pool=row["pool"], tf=tf):
            if signal["versao_config_v2"] != self.version_v2:
                continue
            ev = event_v1_from_json(signal["event_json"])
            dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
            confiavel = self._candle_confiavel_cb(det.bars, row["pool"], ev.data.get("TOPO"))
            res = simulate_v1(det.bars, ev, self.params_v2, self.costs, dex, row["l_bc"], self._sol_at(),
                              candle_confiavel=confiavel)
            if res.entry_price is not None and signal["entry_price"] != res.entry_price:
                self.storage.pr2_update_signal(signal["id"], entry_price=res.entry_price)
            self._confirmar_entrada_v2(signal, res, row, now)
            if res.status == "cancelado":
                self.storage.pr2_update_signal(signal["id"], status="cancelado", reason=res.reason, closed_ts=now)
                continue
            # PEDIDO CONSOLIDADO FASE 2 ("sem duplicar"): quando a ENTRADA foi mesclada com a V1
            # (so_v2=False -- mesmo candle, mesmo gatilho, ja confirmado em resposta ao alerta da V1),
            # TP1/EXIT FULL da V2 NUNCA mandam um alerta Telegram proprio (seria texto repetido do que a
            # V1 ja mandou) -- estatisticas/banca da V2 continuam sendo gravadas normalmente, so o envio
            # ao Telegram e que fica silencioso para esse sinal especifico.
            pode_alertar = bool(signal["so_v2"])
            tp1_leg = next((leg for leg in res.legs if leg.reason == "tp1"), None)
            if tp1_leg is not None and signal["tp1_price"] is None:
                if pode_alertar and signal["tg_message_id"] and self.storage.pr_alert_once(self._key_v2("tp1", signal["id"]), now):
                    text = telegram_v1.tp1_text(self.chain_name, signal["symbol"], tp1_leg.price, res.entry_price or signal["entry_price"])
                    self._send(text, self._keyboard_v2(row), reply_to=signal["tg_message_id"])
                self.storage.pr2_update_signal(signal["id"], tp1_price=tp1_leg.price, tp1_ts=tp1_leg.ts)
            if res.status != "fechado":
                continue
            exit_leg = res.legs[-1] if res.legs else None
            if (pode_alertar and exit_leg is not None and signal["tg_message_id"]
                    and self.storage.pr_alert_once(self._key_v2("x", signal["id"]), now)):
                text = telegram_v1.exit_full_text(self.chain_name, signal["symbol"], exit_leg.price,
                                                  res.entry_price or signal["entry_price"], exit_leg.reason)
                self._send(text, self._keyboard_v2(row), reply_to=signal["tg_message_id"])
            self.storage.pr2_update_signal(
                signal["id"], status="fechado", exit_full_price=exit_leg.price if exit_leg else None,
                exit_full_ts=exit_leg.ts if exit_leg else None, result_net=res.net_ret, reason=res.reason,
                tempo_h=None if res.bars_held is None else res.bars_held * det.step / 3600.0, closed_ts=now,
                r_exit_open_seguinte=res.r_exit_open_seguinte,
                r_liquido_estimado=self._r_liquido_estimado(signal, res),
            )
            self._update_bankroll_v2(row, tf, det, signal, now)

    def _bankroll_v2_ledger(self, tf: str) -> BankrollLedgerV1:
        ledger = self._bankroll_v2.get(tf)
        if ledger is None:
            saved = self.storage.pr2_bankroll_load(tf, self.version_v2)
            from .bankroll_v1 import BankrollStateV1
            state = BankrollStateV1.from_json(saved) if saved else None
            ledger = BankrollLedgerV1(self.params_v2, self.costs, state)
            self._bankroll_v2[tf] = ledger
        return ledger

    def _update_bankroll_v2(self, row: Any, tf: str, det: DetectorV1, signal: Any, now: float) -> None:
        ev = event_v1_from_json(signal["event_json"])
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        meta = {"token": row["symbol"], "contrato": row["mint"], "launchpad": row["launchpad"], "tf": tf}
        ledger = self._bankroll_v2_ledger(tf)
        linha = ledger.step(det.bars, ev, dex, row["l_bc"], self._sol_at(), meta)
        if linha is None:
            return
        if self.storage.pr2_bankroll_append(tf, self.version_v2, signal["id"], linha, now):
            self.storage.pr2_bankroll_save(tf, self.version_v2, ledger.state.to_json())

    # -- PEDIDO 2026-10-27 (H9): snapshot de carteiras "pro" ------------------------------------------------
    def _registrar_snapshot_carteiras(self, momento: str, pool: str, mint: str, holders: HolderCheck,
                                      now: float, versao: Optional[str] = None,
                                      entry_id: Optional[int] = None) -> None:
        """Grava 1 linha em `pr_carteiras_snapshot` cruzando os owners resolvidos
        (`holders.top_holders`, ja excluindo queima/programas base/vaults -- MESMA lista usada para
        `top_holder_pct`) contra a lista de carteiras "pro". Nunca grava quando os holders estao
        indisponiveis (RPC falhou/sem RPC) -- dado ausente nunca vira um `n_carteiras_pro=0` fabricado.
        Idempotente por `chave` (`pr_carteiras_snapshot_insert` usa INSERT OR IGNORE)."""
        if self.sem_carteiras or holders.tag == "holders_indisponivel":
            return
        owners = [o for o, _pct in holders.top_holders]
        n_carteiras, n_pessoas, grupos = carteiras_pro.pessoas_presentes(owners, self._mapa_carteiras_pro)
        if momento == "entrada":
            chave = f"entrada:{versao}:{entry_id}"
        else:
            chave = f"horaria:{pool}:{int(now // 3600)}"
        self.storage.pr_carteiras_snapshot_insert(
            chave, now, "solana", pool, mint, momento, holders.top_holders, n_carteiras, n_pessoas,
            grupos, versao=versao, entry_id=entry_id,
        )

    def _atualizar_carteiras_horaria(self, row: Any, now: float) -> None:
        """1x por pool por hora UTC (bucket `int(now//3600)`, nunca reabre a mesma hora), SO para
        pools com pelo menos 1 posicao ABERTA (V1 ou V2) -- nunca gasta orcamento de RPC em pools sem
        posicao. Chamada NOVA de RPC (ao contrario da snapshot de ENTRADA, que reusa `adapter.holders`
        ja chamado por outro motivo) -- orcada por `carteiras_max_chamadas_dia`
        (`CARTEIRAS_MAX_CHAMADAS_DIA`), contada por dia UTC corrido."""
        if self.sem_carteiras:
            return
        pool = row["pool"]
        bucket = int(now // 3600)
        if self._carteiras_horaria_ultima.get(pool) == bucket:
            return
        tem_posicao = bool(self.storage.pr1_signals(status="aberto", pool=pool)
                          or self.storage.pr2_signals(status="aberto", pool=pool))
        if not tem_posicao:
            return
        inicio_do_dia = now - (now % 86400.0)
        if self.storage.pr_carteiras_snapshot_count_since(inicio_do_dia, "horaria") >= self.carteiras_max_chamadas_dia:
            self._carteiras_ciclo["orcamento_esgotado"] += 1
            return
        self._carteiras_horaria_ultima[pool] = bucket
        self._carteiras_ciclo["tentativas"] += 1
        self._carteiras_ultima_tentativa_ts = now
        holders = self.adapter.holders(row["mint"], self._excluded_accounts_v1(row))
        if holders.tag == "holders_indisponivel":
            self._carteiras_ciclo["erros"] += 1
            motivo = (holders.detail or {}).get("motivo", "s/d")
            self._carteiras_ultimo_erro = f"{row['symbol'] or pool}: {motivo}"
            log.warning("POS-RUNNER carteiras: snapshot horario falhou em %s (%s)", row["symbol"] or pool, motivo)
        else:
            self._carteiras_ciclo["gravados"] += 1
        self._registrar_snapshot_carteiras("horaria", pool, row["mint"], holders, now)

    # -- PATCH 2026-10-27 (diagnostico McRib/yagi, qualidade_candle.py) -----------------------------------------
    def _candle_confiavel_cb(self, bars: list[Bar], pool: str, peak: Optional[float]) -> Callable[[int], Optional[str]]:
        """Closure p/ `simulate_v1(candle_confiavel=...)`: usa a conferencia DexPaprika JA registrada
        (`pr1_dexpaprika_divergencias` -- compartilhada por V1/V2, mesmos candles do mesmo pool) e o
        candle seguinte quando ja existir nesta chamada (simulate_v1 e re-simulado a cada ciclo sobre
        os candles mais recentes -- quem decide 'confirmar pelo candle seguinte' e aqui, nao dentro do
        simulador, que so recebe a resposta ja resolvida)."""
        divergentes = {int(r["candle_ts"]) for r in self.storage.pr1_dexpaprika_divergencias() if r["pool"] == pool}

        def cb(j: int) -> Optional[str]:
            bar = bars[j]
            anterior = bars[j - 1].close if j > 0 else None
            seguinte = bars[j + 1].open if j + 1 < len(bars) else None
            return qualidade_candle.motivo_suspeito(bar, anterior, peak, seguinte, bar.ts in divergentes)
        return cb

    # -- PEDIDO (PARTE 1 de 2) FASES 1-2: trajetoria pos-entrada + baseline pareada ---------------------------
    # Medicao AO LADO de V1/V2 (ver pos_runner/evidencia.py): roda DEPOIS de `_update_paper_v1/v2`, nunca
    # altera nenhuma linha/alerta/banca oficial -- so grava em pr_trajetoria/pr_baseline. So usa candles JA
    # em `pr_bars` (zero chamada nova de GT/DexPaprika; ver INTERPRETACOES.md para o porque o fallback "1
    # fetch/hora" da regra 3 do pedido fica fora do escopo desta entrega -- nunca reagenda nem refaz o
    # pipeline de conversao MC/USD do caminho oficial, que e frozen).
    def _bars_de(self, pool: str, tf: str) -> list[Bar]:
        return [Bar(int(t[0]), t[1], t[2], t[3], t[4], t[5], bool(t[6])) for t in self.storage.pr_bars(pool, tf)]

    def _update_evidencia_v1(self, row: Any, tf: str, now: float) -> None:
        for signal in self.storage.pr1_signals(pool=row["pool"], tf=tf):
            if signal["versao_config_v1"] != self.version_v1 or signal["evento"] != "ENTRADA" or signal["status"] == "cancelado":
                continue
            self._update_evidencia_signal("v1", signal, row, self.params_v1, now)

    def _update_evidencia_v2(self, row: Any, tf: str, now: float) -> None:
        for signal in self.storage.pr2_signals(pool=row["pool"], tf=tf):
            if signal["versao_config_v2"] != self.version_v2 or signal["evento"] != "ENTRADA" or signal["status"] == "cancelado":
                continue
            self._update_evidencia_signal("v2", signal, row, self.params_v2, now)

    def _update_evidencia_signal(self, versao: str, signal: Any, row: Any, params: Any, now: float) -> None:
        bars = self._bars_de(signal["pool"], signal["tf"])
        if not bars:
            return
        traj = self.storage.pr_trajetoria_get(versao, signal["id"])
        if traj is None or not traj["fechado"]:
            self._atualizar_trajetoria(versao, signal, row, bars, params, now)
        baseline = self.storage.pr_baseline_get(versao, signal["id"])
        if baseline is None or baseline["dif_pareada"] is None:
            self._atualizar_baseline(versao, signal, row, bars, params, now)

    def _atualizar_trajetoria(self, versao: str, signal: Any, row: Any, bars: list[Bar], params: Any, now: float) -> None:
        """FASE 1: MFE/MAE + retornos em R nos horizontes fixos, reusando `simulate_v1` (MESMO evento real)
        so para saber se tocou TP1/stop -- nunca copia a logica de saida."""
        ev = event_v1_from_json(signal["event_json"])
        if ev.idx + 1 >= len(bars):
            return   # ainda sem o candle de entrada em cache
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        confiavel = self._candle_confiavel_cb(bars, row["pool"], ev.data.get("TOPO"))
        res = simulate_v1(bars, ev, params, self.costs, dex, row["l_bc"], self._sol_at(), candle_confiavel=confiavel)
        if res.entry_price is None or not res.risk_frac or res.risk_frac <= 0:
            return
        calc = calcular_trajetoria(bars, ev.idx + 1, res.entry_ts, res.entry_price, res.risk_frac,
                                   tf_seconds(signal["tf"]), res.legs, now)
        r = calc.retornos_r
        self.storage.pr_trajetoria_upsert(
            versao, signal["id"], now,
            chain=signal["chain"], pool=signal["pool"], tf=signal["tf"], mint=signal["mint"], symbol=signal["symbol"],
            t_entrada=res.entry_ts, preco_entrada=res.entry_price, risco_pct=100.0 * res.risk_frac,
            r_unidade=res.entry_price * res.risk_frac, fonte_candle=signal["fonte_candle"] or "gt",
            mfe_r=calc.mfe_r, mfe_h=calc.mfe_h, mae_r=calc.mae_r, mae_h=calc.mae_h,
            ret_r_1h=r.get(1), ret_r_2h=r.get(2), ret_r_4h=r.get(4), ret_r_8h=r.get(8),
            ret_r_24h=r.get(24), ret_r_48h=r.get(48), ret_r_72h=r.get(72),
            tocou_tp1=1 if calc.tocou_tp1 else 0, tocou_stop_antes_de_tp1=1 if calc.tocou_stop_antes_de_tp1 else 0,
            fechado=1 if calc.fechado else 0,
        )

    def _atualizar_baseline(self, versao: str, signal: Any, row: Any, bars: list[Bar], params: Any, now: float) -> None:
        """FASE 2a: sorteia (1a chamada) ou resolve (chamadas seguintes) os controles pareados. `stop` do
        controle usa o MESMO risco_pct do sinal real; `TOPO`/`S` sao escalados pela MESMA razao preco/entry
        do sinal real (ver `evidencia.evento_controle` para a justificativa completa)."""
        baseline = self.storage.pr_baseline_get(versao, signal["id"])
        ev = event_v1_from_json(signal["event_json"])
        if baseline is None:
            created_ts = self._created(row)   # criacao CONFIRMADA on-chain (a MESMA que o detector usa p/ idade)
            candidatos = candidatos_elegiveis(bars, created_ts, params.age_window_days, tf_seconds(signal["tf"]), ev.idx)
            if len(candidatos) < N_CONTROLES_MINIMO:
                return   # poucos candles elegiveis ainda -- tenta de novo no proximo ciclo (mais podem qualificar)
            escolhidos = sortear_controles(candidatos, signal["id"], versao)
            controles = [{"idx": i, "ts": bars[i].ts, "status": "pendente", "r_controle": None} for i in escolhidos]
            self.storage.pr_baseline_upsert(
                versao, signal["id"], now, chain=signal["chain"], pool=signal["pool"], tf=signal["tf"],
                mint=signal["mint"], symbol=signal["symbol"], n_controles=len(controles),
                controles_json=json.dumps(controles),
            )
            baseline = self.storage.pr_baseline_get(versao, signal["id"])
        entry_price_sinal = signal["entry_price"]
        if not entry_price_sinal or signal["stop"] is None or signal["topo"] is None or signal["s_suporte"] is None:
            return   # ENTRADA real sem dado suficiente (nao deveria acontecer) -- nunca inventa a razao
        risco_pct_sinal = 100.0 * (1.0 - signal["stop"] / entry_price_sinal)
        topo_mult = signal["topo"] / entry_price_sinal
        s_mult = signal["s_suporte"] / entry_price_sinal
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        controles = json.loads(baseline["controles_json"])
        mudou = False
        for c in controles:
            if c["status"] != "pendente":
                continue
            res = simular_controle(bars, c["idx"], risco_pct_sinal, topo_mult, s_mult, params, self.costs,
                                   dex, row["l_bc"], self._sol_at())
            if res is None or res.status == "em_aberto":
                continue   # ainda sem desfecho -- continua pendente, recalculado no proximo ciclo
            c["status"] = res.status  # 'fechado' | 'cancelado'
            c["r_controle"] = res.r_mult if res.status == "fechado" else None
            mudou = True
        r_controle_medio: Optional[float] = None
        r_sinal: Optional[float] = None
        dif_pareada: Optional[float] = None
        if all(c["status"] != "pendente" for c in controles):
            valores = [c["r_controle"] for c in controles if c["r_controle"] is not None]
            if valores:
                r_controle_medio = sum(valores) / len(valores)
            if signal["status"] == "fechado" and signal["result_net"] is not None and risco_pct_sinal:
                r_sinal = 100.0 * signal["result_net"] / risco_pct_sinal
            if r_controle_medio is not None and r_sinal is not None:
                dif_pareada = r_sinal - r_controle_medio
        if mudou or dif_pareada is not None:
            self.storage.pr_baseline_upsert(
                versao, signal["id"], now, controles_json=json.dumps(controles),
                r_controle_medio=r_controle_medio, r_sinal=r_sinal, dif_pareada=dif_pareada,
            )

    @staticmethod
    def _motivo_exclusao_r(tags_json: Optional[str]) -> Optional[str]:
        """PEDIDO 2026-10-28 (McRib: R acumulado -564,74R/-561,43R contaminado): candle contaminado
        (marcacao retroativa do operador, `scripts/marcar_contaminados.py`, tag `contaminado_candle`)
        ou risco real <3% (fill colado no stop, PATCH 2026-10-27, tag `risco_irrealista`) tornam o
        R-multiplo (lucro_liquido_% / risco_%) uma divisao por quase-zero -- NUNCA entram em
        estatistica agregada (resumo diario, /relatorio); ficam fora com motivo explicito, nunca
        silenciosamente. O trade continua visivel (CSV, tags, /fechados) -- so as estatisticas
        agregadas excluem, nunca os dados em si (nunca deletar dado)."""
        tags = json.loads(tags_json or "[]")
        for motivo in ("contaminado_candle", "risco_irrealista"):
            if motivo in tags:
                return motivo
        return None

    @staticmethod
    def _stats_r_de_fechados(sinais: Sequence[Any]) -> dict[str, Any]:
        """PEDIDO ADICIONAL FASE 5, item 3: R-multiplo (lucro_liquido_% / risco_%, MESMA formula da
        analise Monte Carlo -- `signals_mvp/analise/simulacao_bloco.py`) sobre todos os sinais
        FECHADOS recebidos. `n_tokens` conta tokens DISTINTOS (mint), nao sinais.

        PEDIDO 2026-10-28: nunca calcula R quando o risco real e <3% (`RISCO_IRREALISTA_MIN_PCT`) ou
        o sinal foi marcado `contaminado_candle` -- R fica de fora (nao NULL misturado na media, fora
        da amostra mesmo), contado em `excluidos` por motivo."""
        valores: list[float] = []
        tokens: set[str] = set()
        excluidos: dict[str, int] = {}
        for s in sinais:
            if s["status"] != "fechado" or s["result_net"] is None:
                continue
            motivo = PosRunnerLive._motivo_exclusao_r(s["tags"])
            if motivo is not None:
                excluidos[motivo] = excluidos.get(motivo, 0) + 1
                continue
            entry, stop = s["entry_price"], s["stop"]
            if not entry or stop is None:
                continue
            risco_pct = 100.0 * (1.0 - stop / entry)
            if not risco_pct or risco_pct < PosRunnerLive.RISCO_IRREALISTA_MIN_PCT:
                excluidos["risco_irrealista"] = excluidos.get("risco_irrealista", 0) + 1
                continue
            valores.append(100.0 * s["result_net"] / risco_pct)
            if s["mint"]:
                tokens.add(s["mint"])
        n = len(valores)
        if n == 0:
            return {"n_tokens": 0, "r_acumulado": None, "taxa_r_positivo": None, "r_medio": None,
                    "r_mediana": None, "excluidos": excluidos}
        ordenados = sorted(valores)
        mediana = ordenados[n // 2] if n % 2 else (ordenados[n // 2 - 1] + ordenados[n // 2]) / 2.0
        return {
            "n_tokens": len(tokens), "r_acumulado": sum(valores),
            "taxa_r_positivo": 100.0 * sum(1 for v in valores if v > 0) / n,
            "r_medio": sum(valores) / n, "r_mediana": mediana, "excluidos": excluidos,
        }

    @staticmethod
    def _alvo_tokens() -> int:
        return int(os.environ.get("POS_RUNNER_ALVO_TOKENS", "30"))

    def _ultimo_preco_fechado(self, pool: str, tf: str) -> Optional[float]:
        """Ultimo close JA buscado em `pr_bars` -- zero chamada nova (item 1 do pedido adicional FASE 5)."""
        bars = self.storage.pr_bars(pool, tf)
        return bars[-1][4] if bars else None

    def daily_summary_v1(self) -> str:
        now = self.clock()
        since = now - 86400.0
        filtrados = self.storage.pr1_filtrado_counts(since)
        recentes = [s for s in self.storage.pr1_signals() if s["ts_fechamento"] >= since]
        sinais = len(recentes)
        base_ge_2d = sum(1 for s in recentes if "base_ge_2d" in (json.loads(s["tags"] or "[]")))
        invalidados = filtrados.get("invalidado", 0)
        resumos = self.storage.pr1_bankroll_resumos()
        pnl = None
        liq = [r["lucro_liq_medio_pct"] for r in resumos.values() if r.get("lucro_liq_medio_pct") is not None]
        if liq:
            pnl = sum(liq) / len(liq)
        version_ts = self.version_v1_start or now
        uptime_h = self.storage.pr1_uptime_hours(version_ts, now)
        dp_impacto = self.dexpaprika.resumo_impacto() if self.dexpaprika is not None else None
        dp_divergencias = self.storage.pr1_dexpaprika_divergencia_count_since(since)
        texto = telegram_v1.resumo_diario_text(sinais, invalidados, filtrados.get("dado_invalido", 0),
                                               filtrados.get("filtrado_mc_baixo", 0), filtrados.get("filtrado_idade", 0),
                                               pnl, uptime_h, filtrados.get("filtrado_queda_90_96", 0), base_ge_2d,
                                               dexpaprika_impacto=dp_impacto, dexpaprika_divergencias_24h=dp_divergencias)
        stats = self._stats_r_de_fechados(self.storage.pr1_signals())
        return texto + "\n" + telegram_v1.stats_r_text("V1", stats["n_tokens"], self._alvo_tokens(),
                                                       stats["r_acumulado"], stats["taxa_r_positivo"],
                                                       stats["r_medio"], stats["r_mediana"],
                                                       excluidos=stats["excluidos"])

    def send_daily_summary_v1(self) -> None:
        self._send(self.daily_summary_v1())

    def daily_summary_v2(self) -> str:
        """PEDIDO ADICIONAL FASE 5, item 3: MESMO bloco de estatisticas de R, a partir das tabelas
        pr2_* -- bloco SEPARADO (mensagem propria), nunca misturado com a V1."""
        stats = self._stats_r_de_fechados(self.storage.pr2_signals())
        return "📋 RESUMO DIÁRIO — POS-RUNNER-V2\n" + telegram_v1.stats_r_text(
            "V2", stats["n_tokens"], self._alvo_tokens(), stats["r_acumulado"], stats["taxa_r_positivo"],
            stats["r_medio"], stats["r_mediana"], excluidos=stats["excluidos"])

    def send_daily_summary_v2(self) -> None:
        if self.sem_v2:
            return
        self._send(self.daily_summary_v2())

    # -- PEDIDO ADICIONAL FASE 5: /abertos, /fechados [n] ---------------------------------------------------
    def _bloco_abertos(self, sinais_abertos: Sequence[Any]) -> list[dict[str, Any]]:
        now = self.clock()
        out = []
        for s in sinais_abertos:
            entry, stop = s["entry_price"], s["stop"]
            ultimo = self._ultimo_preco_fechado(s["pool"], s["tf"])
            risco_pct = 100.0 * (1.0 - stop / entry) if entry and stop is not None else None
            if self._motivo_exclusao_r(s["tags"]) is not None or (risco_pct is not None
                                                                   and risco_pct < self.RISCO_IRREALISTA_MIN_PCT):
                risco_pct = None
            r_na = None
            if ultimo is not None and entry and risco_pct:
                r_na = (100.0 * (ultimo / entry - 1.0)) / risco_pct
            out.append({
                "symbol": s["symbol"], "entry_price": entry, "stop": stop, "tp1_price": s["tp1_price"],
                "ultimo_preco": ultimo, "r_nao_realizado": r_na, "tempo_h": (now - s["ts_fechamento"]) / 3600.0,
            })
        return out

    def abertos_texto(self) -> str:
        abertos_v1 = [s for s in self.storage.pr1_signals(status="aberto") if s["versao_config_v1"] == self.version_v1]
        blocos = [("V1", self._bloco_abertos(abertos_v1))]
        if not self.sem_v2:
            abertos_v2 = [s for s in self.storage.pr2_signals(status="aberto") if s["versao_config_v2"] == self.version_v2]
            blocos.append(("V2", self._bloco_abertos(abertos_v2)))
        return telegram_v1.abertos_text(blocos)

    def _bloco_fechados(self, sinais_fechados: Sequence[Any], n: int) -> list[dict[str, Any]]:
        recentes = sorted((s for s in sinais_fechados if s["status"] == "fechado"),
                          key=lambda s: s["closed_ts"] or 0, reverse=True)[:n]
        out = []
        for s in recentes:
            entry, stop = s["entry_price"], s["stop"]
            risco_pct = 100.0 * (1.0 - stop / entry) if entry and stop is not None else None
            # PEDIDO 2026-10-28: nunca calcula R quando contaminado/risco real <3% (mesma regra de
            # `_stats_r_de_fechados`) -- aqui so troca o R individual por s/d, nunca remove o trade
            # da lista (/fechados sempre mostra TODOS os trades fechados, so o numero fica de fora).
            if self._motivo_exclusao_r(s["tags"]) is not None or (risco_pct is not None
                                                                   and risco_pct < self.RISCO_IRREALISTA_MIN_PCT):
                risco_pct = None
            r_realizado = (100.0 * s["result_net"] / risco_pct) if (s["result_net"] is not None and risco_pct) else None
            out.append({
                "symbol": s["symbol"], "r_realizado": r_realizado, "motivo_saida": s["reason"],
                "data_fechamento": iso_utc(s["closed_ts"]) if s["closed_ts"] else None,
            })
        return out

    def fechados_texto(self, n: int = 10) -> str:
        fechados_v1 = [s for s in self.storage.pr1_signals() if s["versao_config_v1"] == self.version_v1]
        blocos = [("V1", self._bloco_fechados(fechados_v1, n))]
        if not self.sem_v2:
            fechados_v2 = [s for s in self.storage.pr2_signals() if s["versao_config_v2"] == self.version_v2]
            blocos.append(("V2", self._bloco_fechados(fechados_v2, n)))
        return telegram_v1.fechados_text(blocos, n)

    def relatorio_semanal_v1(self) -> str:
        """"Bons vs ruins" da ultima semana (FASE 3, item 3): so votos (👍/👎) e so da versao congelada ATUAL
        (`version_v1`) -- nunca mistura versoes de config, mesma regra do `daily_summary_v1`.

        PEDIDO 2026-10-28: sinais contaminado_candle/risco_irrealista (excluidos uma unica vez pelo
        `id`, mesmo entrando em mais de uma estatistica abaixo) ficam fora de TODAS as quebras do
        relatorio (PnL, votos, risco_fora_da_faixa, histograma) -- `excluidos` mostra quantos e por
        qual motivo, nunca some o trade silenciosamente (continua no CSV/tags/`/fechados`)."""
        now = self.clock()
        since = now - 7 * 86400.0
        # item 4 do pedido de ajustes de alerta/medicao: quebra de risco_fora_da_faixa por gatilho e
        # histograma do % de stop vem de TODOS os sinais ENTRADA da semana (nao so os com feedback do
        # operador, que e um subconjunto bem menor) -- so leitura, nunca muda o que ja esta em pr1_signals.
        sinais_semana_todos = [s for s in self.storage.pr1_signals()
                               if s["versao_config_v1"] == self.version_v1 and s["ts_fechamento"] >= since]
        excluidos: dict[str, int] = {}
        excluidos_ids: set[int] = set()
        sinais_semana = []
        for s in sinais_semana_todos:
            motivo = self._motivo_exclusao_r(s["tags"])
            if motivo is not None:
                excluidos[motivo] = excluidos.get(motivo, 0) + 1
                excluidos_ids.add(s["id"])
                continue
            sinais_semana.append(s)
        rows = [r for r in self.storage.pr1_feedback_votes_since(since, now, self.version_v1)
               if r["pr1_signal_id"] not in excluidos_ids]
        pnl_values = [r["sig_result_net"] for r in rows if r["sig_result_net"] is not None]
        pnl_pct = None if not pnl_values else 100.0 * sum(pnl_values) / len(pnl_values)
        scam_count = self.storage.pr1_feedback_scam_count_since(since, now, self.version_v1)
        return telegram_v1.relatorio_semanal_text(rows, pnl_pct, self.version_v1, sinais_semana, scam_count,
                                                  excluidos=excluidos)

    def send_relatorio_semanal_v1(self) -> None:
        self._send(self.relatorio_semanal_v1())

    def relatorio_semanal_v2(self) -> str:
        """PEDIDO CONSOLIDADO FASE 2: MESMO relatorio da V1, so que a partir das tabelas pr2_* -- sem
        feedback (a FASE 3 de botoes/votos e um recurso so da V1 por ora, `rows=[]`); PnL vem direto dos
        sinais FECHADOS da V2 na semana. `/relatorio v2` chama este metodo; nunca mistura com a V1.

        PEDIDO 2026-10-28: mesma exclusao contaminado_candle/risco_irrealista da V1."""
        now = self.clock()
        since = now - 7 * 86400.0
        sinais_semana_todos = [s for s in self.storage.pr2_signals()
                               if s["versao_config_v2"] == self.version_v2 and s["ts_fechamento"] >= since]
        excluidos: dict[str, int] = {}
        sinais_semana = []
        for s in sinais_semana_todos:
            motivo = self._motivo_exclusao_r(s["tags"])
            if motivo is not None:
                excluidos[motivo] = excluidos.get(motivo, 0) + 1
                continue
            sinais_semana.append(s)
        pnl_values = [s["result_net"] for s in sinais_semana if s["status"] == "fechado" and s["result_net"] is not None]
        pnl_pct = None if not pnl_values else 100.0 * sum(pnl_values) / len(pnl_values)
        return telegram_v1.relatorio_semanal_text([], pnl_pct, self.version_v2, sinais_semana, excluidos=excluidos)

    def send_relatorio_semanal_v2(self) -> None:
        self._send(self.relatorio_semanal_v2())

    # -- PEDIDO (PARTE 1 de 2) FASE 2c: /analise [v1|v2] (analise condicional pre-registrada) ---------------
    def analise_texto(self, versao: str) -> str:
        from ..analise import condicional

        try:
            rel = condicional.executar(self.storage, versao)
        except condicional.PlanoAlteradoError as exc:
            return str(exc)
        return condicional.formatar_telegram(rel)

    def _usd_prefix(self, bars: list[Bar], tf: str, usd: UsdSeries) -> list[Bar]:
        """Candles ate o 1o sem cotacao/USD no fechamento (esse e os seguintes esperam: nunca convertidos no chute)."""
        step = tf_seconds(tf)
        out = []
        for b in bars:
            f = usd.at(b.ts + step)
            if f is None or f <= 0:
                break
            out.append(b)
        return out

    def _schedule(self, pool: str, tf: str, now: float) -> None:
        """Proxima busca: no proximo fechamento de candle (+ folga) se quente; a cada 15/30 min se morno/frio."""
        interval = self._interval(tf, self._heat(pool, tf))
        nxt = (int((now - LAG_S) // interval) + 1) * interval + LAG_S
        self.sched[(pool, tf)] = {"next": nxt, "erros": 0.0}

    def _refresh(self, row: Any, tf: str, now: float) -> None:
        self._refresh_core(row, tf, now, self._fetch_gt, fonte="gt")

    def _fetch_gt(self, pool: str, tf: str, grad_ts: float, now: float, side: str) -> list[Bar]:
        return self.ohlcv.history(pool, tf, int(grad_ts), int(now), currency="token", side=side)

    def _refresh_fallback_dexpaprika(self, row: Any, tf: str, now: float) -> bool:
        """PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 3a: so chamado por `_refresh_safe` quando o GT
        falhou (timeout/network/5xx) -- NUNCA substitui o GT na reconstrucao do setup, so tenta uma
        atualizacao pontual pra nao deixar o pool parado durante a instabilidade. Devolve True se algum
        candle novo foi processado (mesmo pipeline de conversao/alimentacao de detector do GT, so a
        ORIGEM do candle cru muda)."""
        if self.dexpaprika is None or row is None or row["status"] != "ativo":
            return False

        def _fetch_dp(pool: str, tf: str, grad_ts: float, now: float, side: str) -> list[Bar]:
            last_bars = self.storage.pr_bars(pool, tf)
            since_ts = last_bars[-1][0] if last_bars else grad_ts
            return self.dexpaprika.candles_fallback(self.ctx.gt_network, pool, tf, since_ts, now)

        before = len(self.storage.pr_bars(row["pool"], tf))
        self._refresh_core(row, tf, now, _fetch_dp, fonte="dexpaprika")
        depois = len(self.storage.pr_bars(row["pool"], tf))
        return depois > before

    def _refresh_core(self, row: Any, tf: str, now: float,
                      fetch_fn: Callable[[str, str, float, float, str], list[Bar]], fonte: str) -> None:
        if row is None or row["status"] != "ativo":
            return
        step = tf_seconds(tf)
        pool = row["pool"]
        info = json.loads(row["info"] or "{}")
        det = None if self.sem_v0 else self._detector(row, tf, now)
        det_fecham = None if self.sem_v0 else self._detector_fecham(row, tf, now)
        det_v1 = self._detector_v1(row, tf, now)
        det_v2 = None if self.sem_v2 else self._detector_v2(row, tf, now)
        det_sombra_mc = None if self.sem_sombra else self._sombra_safe(
            self._detector_sombra_mc, row, tf, now, contexto="filtrado_mc_baixo")
        det_sombra_q96 = None if self.sem_sombra else self._sombra_safe(
            self._detector_sombra_queda96, row, tf, now, contexto="queda_96_mais")
        last = ((det.bars[-1] if det is not None and det.bars else None)
               or (det_v1.bars[-1] if det_v1 is not None and det_v1.bars else None)
               or (det_v2.bars[-1] if det_v2 is not None and det_v2.bars else None))
        # cotacao/USD antes dos candles: sem ela nada e consumido (renova no maximo a cada 15 min; estavel nao custa)
        usd = self.quotes.series(row["quote"], last.ts + step if last else int(row["grad_ts"]), now)
        if usd is None:
            if self.quotes.no_reference(row["quote"]):
                self.storage.pr_upsert_pool(pool, status="encerrado", checked_ts=now, motivo=f"cotacao {row['quote']} sem referencia USD")
            elif fonte == "gt":
                self.sched[(pool, tf)] = {"next": now + 60.0, "erros": 0.0}
            return
        raw = fetch_fn(pool, tf, row["grad_ts"], now, info.get("side", "base"))
        first_load = last is None
        fresh = [b for b in raw if b.ts + step <= now - LAG_S and (last is None or b.ts > last.ts)]
        ok = self._usd_prefix(fresh, tf, usd)
        mc, _missing = to_mc_bars(ok, tf, usd, row["supply"])
        if mc:
            seq = fill_gaps(([last] if last else []) + mc, step)[1 if last else 0:]
            if row["l_bc"] is None:
                self.storage.pr_upsert_pool(pool, l_bc=seq[0].open)
                row = self.storage.pr_pool(pool)
                det = None if self.sem_v0 else self._detector(row, tf, now)
                det_fecham = None if self.sem_v0 else self._detector_fecham(row, tf, now)
                det_v1 = self._detector_v1(row, tf, now, pending=seq)
                det_v2 = None if self.sem_v2 else self._detector_v2(row, tf, now, pending=seq)
                det_sombra_mc = None if self.sem_sombra else self._sombra_safe(
                    self._detector_sombra_mc, row, tf, now, seq, contexto="filtrado_mc_baixo")
                det_sombra_q96 = None if self.sem_sombra else self._sombra_safe(
                    self._detector_sombra_queda96, row, tf, now, seq, contexto="queda_96_mais")
            self.storage.pr_append_bars(pool, tf, [(b.ts, b.open, b.high, b.low, b.close, b.volume, b.filled) for b in seq], fonte=fonte)
            self._fonte_candle_atual = fonte
            if det is not None:
                for b in seq:
                    for ev in det.update(b):
                        self._on_event(row, tf, det, ev, now)
                if det_fecham is not None:
                    label = f"{tf}_fecham"
                    for b in seq:
                        for ev in det_fecham.update(b):
                            self._on_event_fecham(row, label, det_fecham, ev, now)
                self._watch(row, tf, det, now, on_arrival=first_load)
                self._update_paper(row, tf, det, now)
                if det_fecham is not None:
                    self._update_paper(row, f"{tf}_fecham", det_fecham, now, alerts=False)
            if det_v1 is not None:
                for b in seq:
                    for ev in det_v1.update(b):
                        self._on_event_v1(row, tf, det_v1, ev, now)
                self._update_paper_v1(row, tf, det_v1, now)
                if not self.sem_evidencia:
                    # AUDITORIA 2026-10-29 (mesmo incidente da sombra): evidencia (trajetoria/baseline)
                    # tambem e medicao AO LADO -- uma excecao aqui nunca pode derrubar o resto do ciclo
                    # (agendamento/carteiras abaixo).
                    try:
                        self._update_evidencia_v1(row, tf, now)
                    except Exception:  # noqa: BLE001
                        log.warning("POS-RUNNER evidencia v1: erro inesperado em %s %s, ignorado neste ciclo",
                                   row["symbol"], tf, exc_info=True)
            # PEDIDO CONSOLIDADO FASE 2: V2 roda DEPOIS da V1 sobre os MESMOS `seq`, de proposito --
            # assim, quando a V2 fecha uma ENTRADA no MESMO (pool,tf,ts_fechamento), a linha da V1 (se
            # houver) ja esta gravada e o merge de alerta ("V1+V2" vs "SOMENTE V2") sempre ve o estado
            # final da V1 para aquele candle, nunca uma corrida.
            if det_v2 is not None:
                for b in seq:
                    for ev in det_v2.update(b):
                        self._on_event_v2(row, tf, det_v2, ev, now)
                self._update_paper_v2(row, tf, det_v2, now)
                if not self.sem_evidencia:
                    try:
                        self._update_evidencia_v2(row, tf, now)
                    except Exception:  # noqa: BLE001 - ver evidencia v1 acima (mesma auditoria)
                        log.warning("POS-RUNNER evidencia v2: erro inesperado em %s %s, ignorado neste ciclo",
                                   row["symbol"], tf, exc_info=True)
            # PARTE 2A FASE 3: sombra -- MESMOS `seq` ja buscados acima pra V1/V2, zero chamada nova.
            # `_sombra_safe` garante que NENHUMA excecao daqui alcance o resto do ciclo (agendamento/
            # carteiras abaixo) -- ver docstring (incidente de producao 2026-10-29).
            self._sombra_safe(self._sombra_feed, det_sombra_mc, seq, row, tf, now, "filtrado_mc_baixo",
                              contexto="filtrado_mc_baixo")
            self._sombra_safe(self._sombra_feed, det_sombra_q96, seq, row, tf, now, "queda_96_mais",
                              contexto="queda_96_mais")
            self._fonte_candle_atual = "gt"
        if fonte != "gt":
            return    # fallback: nunca reagenda/encerra por conta propria -- o ciclo normal do GT decide
        # INCIDENTE 2026-10-27 (fila de atualizacao 1h presa ~30-59min): a coleta horaria de carteiras
        # "pro" faz uma chamada RPC NOVA (`adapter.holders()`, ate ~21 chamadas sequenciais, cada uma
        # podendo levar ate `max_total_wait_s` da SolanaRpc) direto no ciclo principal sincrono. Rodar
        # isso ANTES de reagendar fazia a lentidao/rate-limit dessa chamada atrasar o PROPRIO reagendamento
        # do (pool,tf) -- exatamente o que `_checar_fila_atrasada` mede -- alem de travar o resto do tick.
        # Reagendar primeiro garante que a coleta "ao lado" nunca atrasa a cadencia oficial de candles/alerta.
        if len(ok) < len(fresh):
            self.sched[(pool, tf)] = {"next": now + 60.0, "erros": 0.0}     # faltou cotacao no fim: tenta logo
        else:
            self._schedule(pool, tf, now)
        if not self.sem_carteiras:
            # AUDITORIA 2026-10-29: ja roda DEPOIS do agendamento acima (nunca atrasa `_schedule`),
            # mas uma excecao aqui ainda subiria pro catch-all de `_refresh_safe` (incrementando
            # `erros` sem motivo) -- isolada tambem, mesmo principio da sombra/evidencia.
            try:
                self._atualizar_carteiras_horaria(row, now)
            except Exception:  # noqa: BLE001
                log.warning("POS-RUNNER carteiras horaria: erro inesperado em %s %s, ignorado neste ciclo",
                           row["symbol"], tf, exc_info=True)

    # -- alertas -------------------------------------------------------------------------------------
    def _keyboard(self, row: Any) -> dict:
        fields = {"pool": row["pool"], "token": row["mint"], "gmgn_slug": "sol", "dexscreener_slug": self.dexscreener_slug}
        buttons = []
        for label, key in (("Axiom", "axiom"), ("DexScreener", "dexscreener")):
            template = self.links.get(key)
            if template:
                try:
                    buttons.append({"text": label, "url": template.format(**fields)})
                except (KeyError, IndexError, ValueError):
                    continue
        return {"inline_keyboard": [buttons]} if buttons else {}

    def _send(self, text: str, keyboard: Optional[dict] = None, png: Optional[bytes] = None, reply_to: Optional[int] = None) -> Optional[int]:
        """O alerta nunca deixa de sair por enfeite: foto recusada -> texto; Telegram 400 -> variante mais simples."""
        if self.tg is None or not self.alerts_on:
            return None
        if png is not None:
            try:
                return int(self.tg.send_photo(png, text, keyboard or None, reply_to=reply_to))
            except TelegramError as exc:
                log.warning("POS-RUNNER: foto recusada (%s); mandando so o texto", exc)
        for variant_text, variant_kb, mode in delivery_variants(text, keyboard or {"inline_keyboard": []}):
            try:
                return int(self.tg.send_message(variant_text, variant_kb if variant_kb.get("inline_keyboard") else None,
                                                parse_mode=mode, reply_to=reply_to))
            except TelegramError as exc:
                if exc.status == 400:
                    continue
                log.warning("POS-RUNNER: falha ao enviar alerta (%s)", exc)
                return None
        return None

    @staticmethod
    def _late(now: float, known_ts: float, limit_s: float) -> bool:
        return now - known_ts > limit_s

    def _key(self, kind: str, *parts: Any) -> str:
        """Chave de alerta por versao_config (a numeracao de onda/zona/entrada recomeca com outra regra)."""
        return ":".join([kind, self.version, *(str(p) for p in parts)])

    def _watched(self, pool: str, tf: str, wave: Any) -> bool:
        return self.storage.pr_alert_seen(self._key("w", pool, tf, wave) + ":")

    def _watch(self, row: Any, tf: str, det: Detector, now: float, on_arrival: bool) -> None:
        """👀 quando a zona da fase 2 esta MADURA agora (>= 12 candles desde o fundo e >= 1 teste de suporte): so ai S, R e
        os testes existem. Depois de uma decisao (entrada/absurdo/invalidacao) a zona recomeca e precisa amadurecer de novo."""
        z = det.zone
        if not (self.settings.alerta_watchlist and det.phase == PHASE_PULLBACK and det.armed and z is not None
                and z.S is not None and z.R is not None and z.last_test is not None):
            return
        last = len(det.bars) - 1
        if self.settings.so_primario and (det.primary_done or not det.in_age_window(last)):
            return                # so sairia reentrada/diagnostico: sem 👀 quando o operador pediu so primarios
        if self._late(now, det.bars[last].ts + det.step, max(900.0, float(det.step))):
            return
        if not self.storage.pr_alert_once(self._key("w", row["pool"], tf, det.wave_no, z.zid), now):
            return
        d = {"P_peak": det.peak, "faixa_pico": self.params.peak_band(det.peak), "queda_pct": det.drop_pct(), "L_bc": det.l_bc,
             "idade_dias": det.age_days(last), "S": z.S, "R": z.R, "n_testes": len(z.tests), "box_len": z.length(last),
             "morre_abaixo": z.last_test["low"] * (1.0 - self.params.test_break)}
        self._send(watch_text(row["symbol"], row["launchpad"], tf, row["mint"], d, on_arrival), self._keyboard(row))

    def _on_event(self, row: Any, tf: str, det: Detector, ev: Event, now: float) -> None:
        pool = row["pool"]
        # sinal = decidido com o token ja no radar E com esta versao_config ja rodando (nada retroativo)
        tracked = (row["added_ts"] is not None and ev.decision_ts >= row["added_ts"]
                   and self.version_start is not None and ev.decision_ts >= self.version_start)
        if ev.kind == "ENTRADA":
            if tracked:
                self._entry(row, tf, det, ev, now)
            return
        if not tracked or not self._watched(pool, tf, ev.data.get("onda")):
            return
        late = self._late(now, ev.decision_ts, max(900.0, float(det.step)))
        if ev.kind in ("INVALIDADO", "ONDA_INVALIDA") and self.settings.alerta_invalidado and not late:
            if self.storage.pr_alert_once(self._key("x", pool, tf, ev.data.get("onda"), ev.idx), now):
                if ev.kind == "INVALIDADO":
                    limit = ev.data["teste_minima"] * (1.0 - self.params.test_break)
                    why = (f"setup morto: fechou abaixo da mínima do último teste de suporte −{100 * self.params.test_break:.0f}% "
                           f"(MC {fmt_usd(det.bars[ev.idx].close)} < {fmt_usd(limit)})")
                else:
                    why = "onda descartada: " + str(ev.data.get("motivo", "onda invalida"))
                self._send(f"{_head('🔴', 'INVALIDADO', tf, row['symbol'], row['launchpad'])}\n{_esc(why, 160)}", self._keyboard(row))
        elif ev.kind == "ABSURDO" and self.settings.alerta_entrada and not late:
            if self.storage.pr_alert_once(self._key("a", pool, tf, ev.data.get("onda"), ev.idx), now):
                cov = ev.data.get("cobertura")
                self._send(f"{_head('⚪', 'NÃO ENTRAR', tf, row['symbol'], row['launchpad'])}\nCandle absurdo no rompimento: já "
                           f"cobriu {_num(None if cov is None else 100 * min(cov, 9.99), 0)}% do caminho de R até o topo (desequilíbrio)",
                           self._keyboard(row))

    def _on_event_fecham(self, row: Any, tf_label: str, det: Detector, ev: Event, now: float) -> None:
        """EMENDA 2026-10-16: 2a medida da queda, so paper/CSV -- so a ENTRADA interessa (sem alerta de
        watchlist/invalidado/absurdo; `_entry(..., alerts=False)` grava o sinal sem mandar nada no Telegram)."""
        if ev.kind != "ENTRADA":
            return
        tracked = (row["added_ts"] is not None and ev.decision_ts >= row["added_ts"]
                  and self.version_start is not None and ev.decision_ts >= self.version_start)
        if tracked:
            self._entry(row, tf_label, det, ev, now, alerts=False)

    def _entry(self, row: Any, tf: str, det: Detector, ev: Event, now: float, alerts: bool = True) -> None:
        pool, n = row["pool"], int(ev.data["n_entrada"])
        self.storage.pr_insert_signal({
            "pool": pool, "tf": tf, "n": n, "primario": int(bool(ev.data.get("primario"))), "decision_ts": float(ev.decision_ts),
            "mint": row["mint"], "symbol": row["symbol"], "launchpad": row["launchpad"], "dex": row["dex"],
            "versao_config": self.version, "event_json": event_to_json(ev), "status": "aberto",
        })
        if not alerts:
            return
        signal = self.storage.pr_signal_by_key(pool, tf, n, self.version)
        if signal is None or not self.settings.alerta_entrada:
            return
        if self.settings.so_primario and not ev.data.get("primario"):
            return
        if self._late(now, ev.decision_ts, max(300.0, det.step / 2.0)):
            return
        if not self.storage.pr_alert_once(self._key("e", pool, tf, n), now):
            return
        data = dict(ev.data, n_entrada=n)
        text = entry_text(row["symbol"], row["launchpad"], tf, row["mint"], data, self.version, self.status)
        mid = self._send(text, self._keyboard(row), self._chart(row, tf, det, ev))
        if mid is not None:
            self.storage.pr_update_signal(signal["id"], tg_message_id=mid, alert_ts=self.clock())
            console.info("POS-RUNNER ENTRADA [%s] $%s #%s", tf, row["symbol"], n)

    def _chart(self, row: Any, tf: str, det: Detector, ev: Event) -> Optional[bytes]:
        if not self.settings.grafico or not charts.available():
            return None
        d = ev.data
        lo = max(0, d["peak_idx"] - 10)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{iso_utc(ev.decision_ts)[:16]}_{row['symbol'] or row['pool'][:8]}_{tf}_{d['n_entrada']}.png")
        try:
            path = charts.plot_setup(
                self.chart_dir / name, det.bars, tf, f"POS-RUNNER {tf} — ${clean_text(row['symbol'], 20)} — entrada #{d['n_entrada']}",
                f"{LAUNCHPAD_NAME.get(row['launchpad'], row['launchpad'])} · stop {fmt_usd(d['stop'])} · alvo {fmt_usd(d['tp'])}",
                row["l_bc"], ev, [e for e in det.events if e.idx >= lo], (), (lo, ev.idx), self.params.atr_period,
                self.params.power_atr_mult, small=True, pad_right=6)
            return path.read_bytes() if path else None
        except Exception:  # noqa: BLE001 - grafico e enfeite: o alerta sai sem ele
            log.exception("POS-RUNNER: falha ao desenhar o grafico")
            return None

    # -- paper ---------------------------------------------------------------------------------------
    def _sol_at(self) -> Callable[[float], Optional[float]]:
        sol = self.quotes.peek(SOL_MINT)
        return sol.at if sol is not None else (lambda t: None)

    def _retorno_sol_dia_v1(self, ts: float) -> Optional[float]:
        """Instrumentacao de medicao (item 1): retorno % do SOL/USD nas 24h antes de `ts`. So LEITURA da
        cotacao JA cacheada (`self.quotes.peek`, zero chamada nova) -- None quando a cobertura cacheada nao
        alcanca 24h atras (nunca busca mais dado so para isto, nunca inventa)."""
        serie = self.quotes.peek(SOL_MINT)
        if serie is None:
            return None
        agora = serie.at(ts)
        ontem = serie.at(ts - 86_400.0)
        if agora is None or ontem is None or ontem <= 0:
            return None
        return 100.0 * (agora / ontem - 1.0)

    def _simulate(self, bars: list[Bar], ev: Event, row: Any, costs: CostModel) -> dict[str, TradeResult]:
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        return {v: simulate(bars, ev, v, self.params, costs, dex, row["l_bc"], self._sol_at()) for v in ("A", "B")}

    def _update_paper(self, row: Any, tf: str, det: Detector, now: float, alerts: bool = True) -> None:
        """`alerts=False` (EMENDA 2026-10-16, 2a medida da queda): grava o paper (resultado, motivo, detalhe) para
        comparar depois, mas nunca manda alerta de saida/resultado, nunca calcula a base pareada (so da
        combinacao primaria) e nunca avanca a gestao de banca (que continua so da combinacao primaria)."""
        step = det.step
        for signal in self.storage.pr_signals(status="aberto", pool=row["pool"], tf=tf):
            if signal["versao_config"] != self.version:
                continue                  # outra regra: virou `descontinuado` no 1o ciclo desta versao
            ev = event_from_json(signal["event_json"])
            res = self._simulate(det.bars, ev, row, self.costs)
            res2 = self._simulate(det.bars, ev, row, self.costs2)
            a, b = res["A"], res["B"]
            detail = {
                "entrada": a.entry_price, "entrada_ts": a.entry_ts, "ambiguo_A": int(a.ambiguous), "ambiguo_B": int(b.ambiguous),
                "bruto_A": a.gross_ret, "bruto_B": b.gross_ret, "custo2x_A": res2["A"].net_ret, "custo2x_B": res2["B"].net_ret,
                "R_A": a.r_mult, "R_B": b.r_mult, "tempo_B_h": None if b.bars_held is None else b.bars_held * step / 3600.0,
                "max_caminho_A": a.max_path_pct, "max_caminho_B": b.max_path_pct,
                "pernas_A": [[leg.idx, leg.price, leg.frac, leg.reason] for leg in a.legs],
                "pernas_B": [[leg.idx, leg.price, leg.frac, leg.reason] for leg in b.legs],
            }
            if alerts:
                self._exit_alerts(row, tf, signal, res, det, now)
            if a.status == "cancelado":
                self.storage.pr_update_signal(signal["id"], status="cancelado", reason_a=a.reason, reason_b=b.reason,
                                              detail_json=json.dumps(detail), closed_ts=now)
                continue
            if a.status == "fechado" and b.status == "fechado":
                base = self._baseline(signal, row, tf, a) if alerts else {"n": 0}
                self.storage.pr_update_signal(
                    signal["id"], status="fechado", result_a=a.net_ret, result_b=b.net_ret, reason_a=a.reason, reason_b=b.reason,
                    tempo_h=None if a.bars_held is None else a.bars_held * step / 3600.0, detail_json=json.dumps(detail),
                    base_json=json.dumps(base), closed_ts=now)
                if alerts:
                    self._result_alert(row, tf, signal, a, b, base)
                    self._update_bankroll(row, tf, det, signal, now)
                continue
            self.storage.pr_update_signal(signal["id"], detail_json=json.dumps(detail))

    def _exit_alerts(self, row: Any, tf: str, signal: Any, res: dict[str, TradeResult], det: Detector, now: float) -> None:
        """🟡 no fechamento do candle em que a saida foi decidida (stop/alvo/trailing dentro do candle; exaustao e tempo
        saem no open seguinte, mas o aviso vai no fechamento que os decidiu). A e B iguais viram uma mensagem so."""
        reply = signal["tg_message_id"]
        if not (self.settings.alerta_saida and reply):
            return
        a = res["A"]
        if a.status == "cancelado":
            if self.storage.pr_alert_once(f"s:{signal['id']}:cancelado", now):
                self._send(f"{_head('🟡', 'NÃO ENTRAR', tf, row['symbol'], row['launchpad'])}\nO candle seguinte abriu fora do "
                           f"plano ({_esc(a.reason, 60)}): paper cancelado", reply_to=reply)
            return
        decided: dict[int, dict[str, Any]] = {}
        for v, r in res.items():
            items = [(leg.idx - 1 if leg.reason in ("exaustao", "tempo") else leg.idx, leg.reason, leg.price) for leg in r.legs]
            if r.pending_exit and r.pending_idx is not None:
                items.append((r.pending_idx, r.pending_exit, det.bars[r.pending_idx].close))
            for idx, reason, price in items:
                slot = decided.setdefault(idx, {"reasons": set(), "variants": set(), "price": price})
                slot["reasons"].add(reason)
                slot["variants"].add(v)
        for idx in sorted(decided):
            slot = decided[idx]
            key = f"s:{signal['id']}:{idx}:" + "+".join(sorted(slot["reasons"]))
            if self._late(now, det.bars[idx].ts + det.step, max(900.0, float(det.step))) or not self.storage.pr_alert_once(key, now):
                continue
            self._send(exit_text(row["symbol"], row["launchpad"], tf, sorted(slot["reasons"]), "/".join(sorted(slot["variants"])),
                                 slot["price"], a.entry_price or slot["price"]), self._keyboard(row), reply_to=reply)

    def _result_alert(self, row: Any, tf: str, signal: Any, a: TradeResult, b: TradeResult, base: dict) -> None:
        reply = signal["tg_message_id"]
        if not (self.settings.alerta_saida and reply):
            return
        if not self.storage.pr_alert_once(f"r:{signal['id']}", self.clock()):
            return
        base_txt = (f"base pareada A {_pct(None if base.get('A') is None else 100 * base['A'], 1)} (n={base.get('n', 0)})"
                    if base.get("n") else "base pareada: sem pools comparaveis ainda")
        self._send(f"📊 POS-RUNNER [{tf}] ${_esc(row['symbol'], 20)} — paper com custos: A {_pct(100 * (a.net_ret or 0), 1)} "
                   f"({_esc(a.reason, 20)}) | B {_pct(100 * (b.net_ret or 0), 1)} ({_esc(b.reason, 20)}) | {base_txt}", reply_to=reply)

    # -- linha de base pareada -------------------------------------------------------------------------
    def _baseline(self, signal: Any, row: Any, tf: str, a: TradeResult) -> dict[str, Any]:
        """Mesma regra da Parte A: ate K outros runners acompanhados (com data de criacao) que ja eram runners na mesma
        idade desde a criacao, entrada no 1o candle com idade >= a do sinal, mesmo colchete (% do stop e do alvo, e o
        pico equivalente da exaustao), mesmas saidas e custos."""
        created = self._created(row)
        if a.entry_ts is None or not a.entry_price or a.stop is None or a.tp is None or not a.peak or created is None:
            return {"n": 0}
        step = tf_seconds(tf)
        age = a.entry_ts - created
        stop_pct, tp_pct, peak_mult = 1.0 - a.stop / a.entry_price, a.tp / a.entry_price - 1.0, a.peak / a.entry_price
        others = [q for q in self.storage.pr_pools("ativo", "encerrado")
                  if q["pool"] != row["pool"] and q["grad_ts"] is not None and q["l_bc"] is not None
                  and self._created(q) is not None]
        rng = random.Random(f"base:{signal['pool']}:{tf}:{signal['n']}")
        rng.shuffle(others)
        rows = []
        for q in others:
            if len(rows) >= K_BASELINE:
                break
            q_created = self._created(q)
            assert q_created is not None
            bars = [Bar(int(t), o, h, l, c, v, bool(f)) for t, o, h, l, c, v, f in self.storage.pr_bars(q["pool"], tf)]
            if not bars or not runner_by_age(bars, q_created, age, self.params.runner_min_mc, step):
                continue
            target = q_created + age
            j = next((i for i, x in enumerate(bars) if x.ts >= target), None)
            if j is None or j == 0 or j + self.params.time_stop_candles >= len(bars):
                continue
            entry = bars[j].open
            ev = Event("ENTRADA", j - 1, bars[j - 1].ts, bars[j].ts,
                       {"stop": entry * (1 - stop_pct), "tp": entry * (1 + tp_pct), "P_peak": entry * peak_mult})
            res = self._simulate(bars, ev, q, self.costs)
            rows.append({"pool": q["pool"], **{v: (r.net_ret if r.status == "fechado" else None) for v, r in res.items()}})
        out: dict[str, Any] = {"n": len(rows), "pools": rows}
        for v in ("A", "B"):
            vals = [r[v] for r in rows if r[v] is not None]
            out[v] = sum(vals) / len(vals) if vals else None
        return out

    def _refresh_baselines(self, now: float) -> None:
        """Base de sinais fechados com menos de K comparaveis e fechados ha < 14 dias: recalcula (so medicao, sem chamada).
        EMENDA 2026-10-16: so a combinacao primaria (extremos) tem base pareada; a 2a medida (fechamentos) nunca entra aqui."""
        for signal in self.storage.pr_signals(status="fechado"):
            if signal["versao_config"] != self.version or signal["tf"].endswith("_fecham"):
                continue
            base = json.loads(signal["base_json"] or "{}")
            if base.get("n", 0) >= K_BASELINE or now - (signal["closed_ts"] or now) > 14 * 86400.0:
                continue
            row = self.storage.pr_pool(signal["pool"])
            detail = json.loads(signal["detail_json"] or "{}")
            if row is None or not detail.get("entrada"):
                continue
            ev = event_from_json(signal["event_json"])
            fake = TradeResult("A", "fechado", ev.idx + 1, entry_ts=detail.get("entrada_ts"), entry_price=detail["entrada"],
                               stop=ev.data["stop"], tp=ev.data["tp"], peak=ev.data.get("P_peak"))
            new = self._baseline(signal, row, signal["tf"], fake)
            if new.get("n", 0) > base.get("n", 0):
                self.storage.pr_update_signal(signal["id"], base_json=json.dumps(new))

    # -- gestao de banca (addendum de relatorio, 2026-10-16) -------------------------------------------
    def _bankroll_ledger(self, tf: str, variant: str) -> BankrollLedger:
        """Um por (tf, variante) desta `versao_config` (troca de config comeca banca nova, como o resto do paper
        -- decisao de outra versao nunca vira sinal/resultado dela)."""
        key = (tf, variant)
        ledger = self._bankroll.get(key)
        if ledger is None:
            saved = self.storage.pr_bankroll_load(tf, variant, self.version)
            state = BankrollState.from_json(saved) if saved else None
            ledger = BankrollLedger(self.params, self.costs, self._bankroll_params, state)
            self._bankroll[key] = ledger
        return ledger

    def _update_bankroll(self, row: Any, tf: str, det: Detector, signal: Any, now: float) -> None:
        """Avanca os 2 ledgers (A/B) deste tf com o sinal que acabou de fechar; nunca reescreve uma linha ja gravada
        (um sinal fecha so uma vez por variante). So trades FECHADOS entram -- cancelado nunca chega aqui."""
        ev = event_from_json(signal["event_json"])
        dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
        sol_at = self._sol_at()
        meta = {"token": row["symbol"], "contrato": row["mint"], "launchpad": row["launchpad"], "tf": tf}
        for variant in ("A", "B"):
            ledger = self._bankroll_ledger(tf, variant)
            linha = ledger.step(det.bars, ev, variant, dex, row["l_bc"], sol_at, {**meta, "saida": variant})
            if linha is None:
                continue
            if self.storage.pr_bankroll_append(tf, variant, self.version, signal["id"], linha, now):
                self.storage.pr_bankroll_save(tf, variant, self.version, ledger.state.to_json())

    def daily_bankroll_summary(self) -> str:
        """Resumo diario por ajuste (nº trades, % com lucro, lucro liquido medio, banca final, maior queda) -- o
        operador pediu que a Parte B mande isso no Telegram todo dia."""
        resumos = self.storage.pr_bankroll_resumos()
        if not resumos:
            return "Gestão de banca: nenhum ajuste com trade fechado ainda."
        out = ["💰 Resumo diário da gestão de banca (US$100, posição 5%, até 3 abertas):"]
        for k in sorted(resumos):
            s = resumos[k]
            if not s["n_trades"]:
                out.append(f"- {k}: 0 trades | banca US$ {s['banca_final_usd']:.2f}")
                continue
            out.append(f"- {k}: {s['n_trades']} trades | {s['pct_com_lucro']:.0f}% com lucro | "
                       f"líquido médio {s['lucro_liq_medio_pct']:+.1f}% | banca US$ {s['banca_final_usd']:.2f} | "
                       f"maior queda US$ {s['maior_queda_usd']:.2f} ({s['maior_queda_pct']:.0f}%)")
        return "\n".join(out)

    def send_daily_bankroll_summary(self) -> None:
        self._send(self.daily_bankroll_summary())

    # -- status ----------------------------------------------------------------------------------------
    def status_line(self) -> str:
        if not self.enabled():
            return "POS-RUNNER: desligado (config.yaml > pos_runner.ligado)"
        c = self.storage.pr_counts()
        hot = sum(1 for (pool, tf) in self.dets if self._heat(pool, tf) == 0)
        v1_abertos = len(self.storage.pr1_signals(status="aberto"))
        v1_fechados = len(self.storage.pr1_signals(status="fechado"))
        return (f"POS-RUNNER: config {self.version} ({self.status}) | pools {c.get('pools_ativo', 0)}/{self.settings.max_pools} "
                f"(fila {c.get('pools_verificado', 0)}, conferindo {c.get('pools_pendente', 0)}, em fase 2: {hot}) | "
                f"sinais abertos {c.get('sinais_aberto', 0)}, fechados {c.get('sinais_fechado', 0)}\n"
                f"POS-RUNNER-V1: config {self.version_v1} | sinais abertos {v1_abertos}, fechados {v1_fechados}"
                + (" | V0 desligado (--sem-v0)" if self.sem_v0 else ""))
