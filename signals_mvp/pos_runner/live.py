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
import random
import re
import threading
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
from . import charts, telegram_v1
from .bankroll import BankrollLedger, BankrollParams, BankrollState
from .bankroll_v1 import BankrollLedgerV1, tamanho_posicao_usd
from .brt import hora_brt, na_janela_ouro
from .candles import Bar, OhlcvStore, fill_gaps, tf_seconds
from .chain_adapter import SolanaAdapter
from .costs import CostModel
from .detector import PHASE_PULLBACK, PHASE_RUNNER, Detector, Event
from .detector_v1 import DetectorV1, EventV1
from .enumerate import LAUNCHPADS as MIGRATIONS, resolve_graduation
from .lineage import creation_time
from .params import Params, is_preregistered
from .params_v1 import load_params_v1
from .parte_a.baseline import K_BASELINE, runner_by_age
from .parte_a.pipeline import DEX_OF_LAUNCHPAD
from .parte_a.quotebook import QuoteBook
from .qualidade_v1 import avaliar_qualidade
from .quotes import SOL_MINT, STABLES, UsdSeries, stable_series, to_mc_bars
from .simulate import TradeResult, simulate
from .simulate_v1 import simulate_v1
from .solana_rpc import SIGNATURES_PAGE_SIZE, RpcError, anchor_at_or_after

log = logging.getLogger("signals_mvp.pos_runner.live")
console = logging.getLogger("signals_mvp.console")

TFS = ("5m", "1h", "4h")
LAG_S = 90.0                 # folga depois do fechamento do candle para o GT indexar as ultimas trades
QUOTE_REFRESH_S = 900.0      # cotacao/USD (1h) renovada no maximo a cada 15 min
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
        self.sched: dict[tuple[str, str], dict[str, float]] = {}
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
        # heartbeat periodico (revisao da FASE 1, 2026-10-22: nao existia -- telegram_v1.heartbeat_text
        # ficava morto; revisao da FASE 1.1: sai ja no startup -- nao espera a 1a janela -- e a cada 6h, nao
        # 4h). Janela rolante: zera a cada envio, nunca acumula indefinidamente.
        self.heartbeat_interval_s: float = 6 * 3600.0
        self._heartbeat_calls = 0
        self._heartbeat_429 = 0
        self._heartbeat_window_start: Optional[float] = None
        self._heartbeat_sent_at: float = 0.0

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
        # versao_config_v1 nunca vira sinal dela. Evento ocorrido com o processo desligado (lacuna > folga do
        # tf) fica `perdido_offline`, nunca tenta alertar com atraso.
        self.version_v1_start = self.storage.pr1_version_start(self.version_v1, now)
        for signal in self.storage.pr1_signals(status="aberto"):
            if signal["versao_config_v1"] != self.version_v1:
                self.storage.pr1_update_signal(signal["id"], status="descontinuado", closed_ts=now)
            elif self._late(now, signal["ts_fechamento"], max(1800.0, 2.0 * tf_seconds(signal["tf"]))):
                self.storage.pr1_update_signal(signal["id"], status="perdido_offline", closed_ts=now)
        if self._uptime_id is None:
            self._uptime_id = self.storage.pr1_uptime_start(now)

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
            info = {"fonte": fonte, "created_ts": s.created_ts, "side": s.target_side, "nome": s.name}
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
        out.sort(key=lambda x: (x[0], x[1], order.get(x[3], 9)))
        return out

    def wanted(self, now: float) -> int:
        """Quantas chamadas o POS-RUNNER quer neste ciclo (o bot reserva isso antes do refresh dos pools jovens)."""
        if not self.enabled():
            return 0
        n = len(self._due_list(now)) + (1 if now >= self.next_discovery and self.settings.fontes else 0)
        return min(n, self.settings.chamadas_por_ciclo)

    # -- ciclo -------------------------------------------------------------------------------------
    def tick(self, now: float, budget: CallBudget, keep: int) -> dict[str, Any]:
        out: dict[str, Any] = {"chamadas": 0, "erros": 0, "rate_limited": False}
        if not self.enabled():
            return out
        if self.version_start is None:
            self._startup(now)
        self.http.arm(budget, keep, self.settings.chamadas_por_ciclo)
        try:
            self._promote(now)
            due = self._due_list(now)
            for rank, _next, row, tf in due:
                if rank == 0:
                    self._refresh_safe(row, tf, now, out)
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
            out["chamadas"] = self.http.disarm()
        self._retire(now)
        if now - self.last_baselines >= 3600.0:
            self.last_baselines = now
            self._refresh_baselines(now)
        if now - self.last_prune >= 3600.0:
            self.last_prune = now
            removed = self.storage.pr_prune(now)
            if removed:
                log.info("POS-RUNNER poda: %s", removed)
        self._heartbeat_v1(now, out.get("chamadas", 0), out.get("rate_limited", False))
        self.last_tick = out
        return out

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
        text = telegram_v1.heartbeat_text(
            self.storage.pr1_uptime_hours(self.version_v1_start or now, now), pools_ativos, chamadas_por_min,
            self._heartbeat_429, self._phase_counts_v1(), len(self._due_list(now)), counts.get("dado_invalido", 0),
            counts.get("l_bc_suspeito", 0), counts.get("filtrado_mc_baixo", 0), counts.get("filtrado_idade", 0),
            self.version_v1,
        )
        self._send(text)
        self._heartbeat_sent_at = now
        self._heartbeat_window_start = now
        self._heartbeat_calls = 0
        self._heartbeat_429 = 0

    def _refresh_safe(self, row: Any, tf: str, now: float, out: dict[str, Any]) -> None:
        key = (row["pool"], tf)
        try:
            self._refresh(self.storage.pr_pool(row["pool"]), tf, now)
        except (RateLimited, TelegramError):
            raise
        except ApiError as exc:
            if exc.kind == "budget":
                raise
            out["erros"] += 1
            st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
            st["erros"] += 1
            st["next"] = now + min(1800.0, 60.0 * (2 ** st["erros"]))
            log.warning("POS-RUNNER: candles de %s %s falharam (%s)", row["symbol"], tf, exc)
            if exc.kind == "not_found" and st["erros"] >= 3:
                self.storage.pr_upsert_pool(row["pool"], status="encerrado", checked_ts=now, motivo="pool nao existe mais no GT (404)")
        except Exception:  # noqa: BLE001 - um pool com problema nunca trava os outros
            out["erros"] += 1
            st = self.sched.setdefault(key, {"next": 0.0, "erros": 0.0})
            st["erros"] += 1
            st["next"] = now + min(3600.0, 120.0 * (2 ** st["erros"]))
            log.exception("POS-RUNNER: erro inesperado em %s %s (pool em espera)", row["symbol"], tf)

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

    def _keyboard_v1(self, row: Any) -> dict:
        return telegram_v1.keyboard(self.adapter, row["mint"], row["pool"], "sol", self.dexscreener_slug)

    def _on_event_v1(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        pool = row["pool"]
        tracked = (row["added_ts"] is not None and ev.decision_ts >= row["added_ts"]
                   and self.version_v1_start is not None and ev.decision_ts >= self.version_v1_start)
        if not tracked:
            return
        if ev.kind == "ENTRADA":
            self._entry_v1(row, tf, det, ev, now)
            return
        if ev.kind == "FORA_DA_IDADE":
            self.storage.pr1_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "filtrado_idade",
                                          f"{ev.data.get('idade_dias')}", self.version_v1)
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
                text = telegram_v1.invalidado_text(self.chain_name, row["symbol"], str(ev.data.get("motivo", "")))
                self._send(text, self._keyboard_v1(row))
                self.storage.pr1_add_filtrado(now, "solana", pool, row["mint"], row["symbol"], "invalidado",
                                              str(ev.data.get("motivo", "")), self.version_v1)

    def _entry_v1(self, row: Any, tf: str, det: DetectorV1, ev: EventV1, now: float) -> None:
        pool, mint, symbol = row["pool"], row["mint"], row["symbol"]
        ts_fechamento = int(ev.decision_ts)
        signal = self.storage.pr1_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
        if signal is None:
            gatilho = list(ev.data.get("gatilho") or [])
            tags: list[str] = []
            if ev.data.get("risco_fora_da_faixa"):
                tags.append("risco_fora_da_faixa")
            if self._v1_suspeito.get((pool, tf)):
                tags.append("l_bc_suspeito")
            holders = self.adapter.holders(mint, self._excluded_accounts_v1(row))
            if holders.tag:
                tags.append(holders.tag)
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
            }
            signal_id = self.storage.pr1_insert_signal(row_insert)
            if signal_id is None:   # corrida rara (outro ciclo/processo ja inseriu): usa o que ja existe
                signal = self.storage.pr1_signal_by_key("solana", pool, tf, "ENTRADA", ts_fechamento)
                if signal is None:
                    return
                signal_id = signal["id"]
            signal = self.storage.pr1_signal(signal_id)
        if signal is None or signal["tg_message_id"]:
            return
        if self._late(now, ev.decision_ts, max(300.0, det.step / 2.0)):
            return
        if not self.storage.pr_alert_once(self._key_v1("e", pool, tf, ts_fechamento), now):
            return
        tags = json.loads(signal["tags"] or "[]")
        gatilho = json.loads(signal["gatilho"] or "[]")
        age_h = None if ev.data.get("idade_dias") is None else ev.data["idade_dias"] * 24.0
        banca = self._bankroll_v1_ledger(tf).state.banca
        text = telegram_v1.entrada_text(
            self.chain_name, symbol, ev.data.get("P_peak"), age_h or 0.0, signal["janela_ouro"] or "fora_da_janela",
            gatilho, tags, signal["entry_price"], signal["stop"], signal["topo"], tamanho_posicao_usd(banca, self.params_v1),
            mint, liquidez_usd=signal["liquidez_usd"],
        )
        mid = self._send(text, self._keyboard_v1(row))
        if mid is not None:
            self.storage.pr1_update_signal(signal["id"], tg_message_id=mid, alert_ts=self.clock())

    def _update_paper_v1(self, row: Any, tf: str, det: DetectorV1, now: float) -> None:
        for signal in self.storage.pr1_signals(status="aberto", pool=row["pool"], tf=tf):
            if signal["versao_config_v1"] != self.version_v1:
                continue
            ev = event_v1_from_json(signal["event_json"])
            dex = DEX_OF_LAUNCHPAD.get(row["launchpad"], "desconhecido")
            res = simulate_v1(det.bars, ev, self.params_v1, self.costs, dex, row["l_bc"], self._sol_at())
            if res.entry_price is not None and signal["entry_price"] != res.entry_price:
                self.storage.pr1_update_signal(signal["id"], entry_price=res.entry_price)
            if res.status == "cancelado":
                self.storage.pr1_update_signal(signal["id"], status="cancelado", reason=res.reason, closed_ts=now)
                continue
            tp1_leg = next((leg for leg in res.legs if leg.reason == "tp1"), None)
            if tp1_leg is not None and signal["tp1_price"] is None:
                if signal["tg_message_id"] and self.storage.pr_alert_once(self._key_v1("tp1", signal["id"]), now):
                    text = telegram_v1.tp1_text(self.chain_name, signal["symbol"], tp1_leg.price, res.entry_price or signal["entry_price"])
                    self._send(text, reply_to=signal["tg_message_id"])
                self.storage.pr1_update_signal(signal["id"], tp1_price=tp1_leg.price, tp1_ts=tp1_leg.ts)
            if res.status != "fechado":
                continue
            exit_leg = res.legs[-1] if res.legs else None
            if exit_leg is not None and signal["tg_message_id"] and self.storage.pr_alert_once(self._key_v1("x", signal["id"]), now):
                text = telegram_v1.exit_full_text(self.chain_name, signal["symbol"], exit_leg.price,
                                                  res.entry_price or signal["entry_price"], exit_leg.reason)
                self._send(text, reply_to=signal["tg_message_id"])
            self.storage.pr1_update_signal(
                signal["id"], status="fechado", exit_full_price=exit_leg.price if exit_leg else None,
                exit_full_ts=exit_leg.ts if exit_leg else None, result_net=res.net_ret, reason=res.reason,
                tempo_h=None if res.bars_held is None else res.bars_held * det.step / 3600.0, closed_ts=now,
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

    def daily_summary_v1(self) -> str:
        now = self.clock()
        since = now - 86400.0
        filtrados = self.storage.pr1_filtrado_counts(since)
        sinais = len([s for s in self.storage.pr1_signals() if s["ts_fechamento"] >= since])
        invalidados = filtrados.get("invalidado", 0)
        resumos = self.storage.pr1_bankroll_resumos()
        pnl = None
        liq = [r["lucro_liq_medio_pct"] for r in resumos.values() if r.get("lucro_liq_medio_pct") is not None]
        if liq:
            pnl = sum(liq) / len(liq)
        version_ts = self.version_v1_start or now
        uptime_h = self.storage.pr1_uptime_hours(version_ts, now)
        return telegram_v1.resumo_diario_text(sinais, invalidados, filtrados.get("dado_invalido", 0),
                                              filtrados.get("filtrado_mc_baixo", 0), filtrados.get("filtrado_idade", 0),
                                              pnl, uptime_h)

    def send_daily_summary_v1(self) -> None:
        self._send(self.daily_summary_v1())

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
        if row is None or row["status"] != "ativo":
            return
        step = tf_seconds(tf)
        pool = row["pool"]
        info = json.loads(row["info"] or "{}")
        det = None if self.sem_v0 else self._detector(row, tf, now)
        det_fecham = None if self.sem_v0 else self._detector_fecham(row, tf, now)
        det_v1 = self._detector_v1(row, tf, now)
        last = (det.bars[-1] if det is not None and det.bars else None) or (det_v1.bars[-1] if det_v1 is not None and det_v1.bars else None)
        # cotacao/USD antes dos candles: sem ela nada e consumido (renova no maximo a cada 15 min; estavel nao custa)
        usd = self.quotes.series(row["quote"], last.ts + step if last else int(row["grad_ts"]), now)
        if usd is None:
            if self.quotes.no_reference(row["quote"]):
                self.storage.pr_upsert_pool(pool, status="encerrado", checked_ts=now, motivo=f"cotacao {row['quote']} sem referencia USD")
            else:
                self.sched[(pool, tf)] = {"next": now + 60.0, "erros": 0.0}
            return
        raw = self.ohlcv.history(pool, tf, int(row["grad_ts"]), int(now), currency="token", side=info.get("side", "base"))
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
            self.storage.pr_append_bars(pool, tf, [(b.ts, b.open, b.high, b.low, b.close, b.volume, b.filled) for b in seq])
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
        if len(ok) < len(fresh):
            self.sched[(pool, tf)] = {"next": now + 60.0, "erros": 0.0}     # faltou cotacao no fim: tenta logo
        else:
            self._schedule(pool, tf, now)

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
