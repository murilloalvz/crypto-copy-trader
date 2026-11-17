"""RODADA 25 (pedido 2026-11-17): PILOTO DO B1 (copy-wallet) -- so CONTAGENS, nunca preco/candle/retorno.
PAPER/READ-ONLY.

O que faz (desenho em docs/pos-runner-v3/RODADA_25_B1_AJUSTES.md, §3 e §5 + adendo):
 1. Para cada uma das 121 carteiras da lista congelada (`carteiras_pro_papodefi.json`, sha256
    71d6ee62a458...), le ate `--max-paginas` paginas de `getSignaturesForAddress` e conta as
    transacoes BEM-SUCEDIDAS posteriores ao congelamento (2026-10-27 19:09:46 UTC) -> TX_pos/dia.
 2. Sorteia ~`--amostra` (200) dessas transacoes, alocadas por carteira em proporcao ao volume
    estimado (semente fixa), e faz `getTransaction` (jsonParsed, maxSupportedTransactionVersion 1).
 3. Classifica cada tx SO pelos saldos do proprio tx (pre/postTokenBalances, pre/postBalances,
    logMessages): compra / venda / outro; para compra: 1a vez daquela carteira no token (f_novo),
    passou pela curva de bonding (f_curva), liquidez do pool no instante (cofres do pool no tx) ->
    sem_dado / < US$5k / >= US$5k. Para venda: fracao vendida do saldo (diagnostico do limiar 50%).
 4. N_proj = lambda_ef x 180 e a decisao pela regra do B4 (104 tokens; pessimista com limites de IC).

GARANTIAS (testadas em tests/test_piloto_b1_compras.py):
 - NUNCA abre o banco do bot (nenhum `sqlite3.connect`), nunca le `pr_bars`, nunca chama
   GeckoTerminal nem Jupiter: o unico destino de rede e `--rpc-url`/`PILOTO_B1_RPC_URL`.
 - so `getSignaturesForAddress` e `getTransaction` (1 credito Helius cada, docs 2026-11-16);
   medidor por metodo e teto `--max-creditos` (aborta antes de passar). Aborta no 1o 429.
 - a URL do RPC (pode conter a chave) nunca e impressa: so o host.
 - `--sol-usd` e OBRIGATORIO (so converte a reserva de SOL do pool para o corte de US$5k; nao e
   preco de token, e nao e buscado em lugar nenhum -- o operador informa).
Limites declarados: f_novo e "1a vez DESTA CARTEIRA no token"; a sobreposicao entre pessoas da lista
so e estimada dentro da amostra (subestima); carteiras com mais transacoes que `--max-paginas` x 1000
tem a taxa extrapolada da janela observada (marcadas `truncada`).

Uso (piloto com a chave do bot e permitido, ~320 creditos):
    PILOTO_B1_RPC_URL='https://...' python -m signals_mvp.scripts.piloto_b1_compras --sol-usd 70.7
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from .piloto_rendimento_b2 import clopper_pearson

CONGELAMENTO_TS = int(datetime(2026, 10, 27, 19, 9, 46, tzinfo=timezone.utc).timestamp())
D_PROJECAO = 180                       # 2026-10-27 -> 2027-04-25 (limite do OHLCV gratis; conservador)
N_MIN = 104                            # d=0,3; alfa 0,05; 80% poder; folga 1,5x (Rodada 25 §5)
N_MIN_ALFA2 = 132
F_GT = (0.87, 0.60)                    # cobertura de candle GT (ponto, limite inferior) -- Rodada 22, n=15
LIQ_MIN_USD = 5000.0
LIMIAR_VENDA = 0.50
CREDITOS = {"getSignaturesForAddress": 1, "getTransaction": 1}
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
QUOTES = {WSOL} | STABLES
CURVA_PROGRAMAS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pumpfun",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "meteora_dbc",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "raydium_launchlab",
}


class Abortar(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# RPC com medidor de creditos
# ---------------------------------------------------------------------------


class RpcMedido:
    def __init__(self, url: str, max_creditos: int, intervalo_s: float = 0.5,
                 post: Optional[Callable[[str, bytes], tuple[int, Any]]] = None,
                 dormir: Callable[[float], None] = time.sleep):
        self.url, self.max_creditos, self.intervalo_s = url, max_creditos, intervalo_s
        self.post = post or self._post
        self.dormir = dormir
        self.chamadas: Counter = Counter()
        self.ultima = 0.0

    @property
    def creditos(self) -> int:
        return sum(CREDITOS[m] * n for m, n in self.chamadas.items())

    @staticmethod
    def _post(url: str, corpo: bytes) -> tuple[int, Any]:
        req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            return exc.code, None

    def call(self, metodo: str, params: list) -> Any:
        if metodo not in CREDITOS:
            raise ValueError(f"metodo nao autorizado no piloto: {metodo}")
        if self.creditos + CREDITOS[metodo] > self.max_creditos:
            raise Abortar(f"teto de {self.max_creditos} creditos atingido")
        espera = self.intervalo_s - (time.monotonic() - self.ultima)
        if self.ultima and espera > 0:
            self.dormir(espera)
        self.ultima = time.monotonic()
        self.chamadas[metodo] += 1
        st, dado = self.post(self.url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": metodo,
                                                   "params": params}).encode())
        if st == 429:
            raise Abortar("HTTP 429")
        if st != 200 or not isinstance(dado, dict):
            raise RuntimeError(f"{metodo}: HTTP {st}")
        if dado.get("error"):
            msg = str(dado["error"].get("message", ""))
            if dado["error"].get("code") in (-32429, 429) or "rate" in msg.lower():
                raise Abortar(f"rate limit: {msg[:60]}")
            raise RuntimeError(f"{metodo}: {msg[:80]}")
        return dado.get("result")


# ---------------------------------------------------------------------------
# classificacao de 1 transacao (pura, testada com tx sinteticos)
# ---------------------------------------------------------------------------


def _saldos(lista: Optional[list]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for b in lista or []:
        dono, mint = b.get("owner"), b.get("mint")
        valor = (b.get("uiTokenAmount") or {}).get("uiAmount")
        if dono and mint:
            out[(dono, mint)] = out.get((dono, mint), 0.0) + float(valor or 0.0)
    return out


def _chaves(tx: dict) -> list[str]:
    ks = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k["pubkey"] if isinstance(k, dict) else k for k in ks]


@dataclass
class Classificacao:
    tipo: str                               # compra | venda | outro | erro
    mint: Optional[str] = None
    novo: Optional[bool] = None
    curva: Optional[str] = None             # launchpad da curva invocada, ou None
    liq_usd: Optional[float] = None         # 2 x reserva da cotacao do pool no tx (pre)
    fracao_vendida: Optional[float] = None


def classificar_tx(tx: dict, carteira: str, sol_usd: float) -> Classificacao:
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return Classificacao("erro")
    pre, post = _saldos(meta.get("preTokenBalances")), _saldos(meta.get("postTokenBalances"))
    deltas: dict[str, float] = {}
    for (dono, mint) in set(pre) | set(post):
        if dono == carteira and mint not in QUOTES:
            d = post.get((dono, mint), 0.0) - pre.get((dono, mint), 0.0)
            if abs(d) > 0:
                deltas[mint] = d
    chaves = _chaves(tx)
    lam = 0.0
    if carteira in chaves:
        i = chaves.index(carteira)
        pb, qb = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i < len(pb) and i < len(qb):
            lam = (qb[i] - pb[i]) / 1e9
    quote_delta = lam + sum(post.get((carteira, q), 0.0) - pre.get((carteira, q), 0.0) for q in QUOTES)
    compras = {m: d for m, d in deltas.items() if d > 0}
    vendas = {m: d for m, d in deltas.items() if d < 0}
    if compras and quote_delta < 0:
        mint = max(compras, key=compras.get)
        logs = " ".join(meta.get("logMessages") or [])
        curva = next((lp for prog, lp in CURVA_PROGRAMAS.items() if f"Program {prog} invoke" in logs), None)
        liq = None
        if curva is None:
            donos = {d for (d, m) in pre if m == mint and d != carteira}
            candidatos = []
            for d in donos:
                for q in QUOTES:
                    reserva = pre.get((d, q))
                    if reserva:
                        candidatos.append(2.0 * reserva * (sol_usd if q == WSOL else 1.0))
            liq = max(candidatos) if candidatos else None
        return Classificacao("compra", mint, novo=pre.get((carteira, mint), 0.0) <= 0.0, curva=curva, liq_usd=liq)
    if vendas and quote_delta > 0:
        mint = min(vendas, key=vendas.get)
        antes = pre.get((carteira, mint), 0.0)
        frac = (-vendas[mint] / antes) if antes > 0 else None
        return Classificacao("venda", mint, fracao_vendida=frac)
    return Classificacao("outro")


# ---------------------------------------------------------------------------
# contagem de assinaturas e amostra
# ---------------------------------------------------------------------------


@dataclass
class Carteira:
    endereco: str
    nome: str
    grupo: str
    pos: list[str] = field(default_factory=list)   # assinaturas ok pos-congelamento observadas
    taxa_dia: float = 0.0
    truncada: bool = False
    paginas: int = 0


def contar_carteira(rpc: RpcMedido, c: Carteira, agora: float, max_paginas: int) -> None:
    antes: Optional[str] = None
    mais_novo = mais_velho = None
    while c.paginas < max_paginas:
        opts: dict[str, Any] = {"limit": 1000}
        if antes:
            opts["before"] = antes
        pagina = rpc.call("getSignaturesForAddress", [c.endereco, opts]) or []
        c.paginas += 1
        if not pagina:
            break
        for s in pagina:
            bt = s.get("blockTime")
            if bt is None:
                continue
            mais_novo = bt if mais_novo is None else max(mais_novo, bt)
            mais_velho = bt if mais_velho is None else min(mais_velho, bt)
            if s.get("err") is None and bt >= CONGELAMENTO_TS:
                c.pos.append(s["signature"])
        if len(pagina) < 1000 or (mais_velho is not None and mais_velho < CONGELAMENTO_TS):
            break
        antes = pagina[-1]["signature"]
    dias_obs = (agora - CONGELAMENTO_TS) / 86400.0
    if mais_velho is not None and mais_velho >= CONGELAMENTO_TS and c.paginas >= max_paginas:
        c.truncada = True   # nao chegou ao congelamento: taxa da janela observada (recente)
        janela = max((agora - mais_velho) / 86400.0, 1e-6)
        c.taxa_dia = len(c.pos) / janela
    else:
        c.taxa_dia = len(c.pos) / dias_obs


def sortear_amostra(carteiras: list[Carteira], n: int, semente: int) -> list[tuple[Carteira, str]]:
    rng = random.Random(semente)
    pesos = [c.taxa_dia if c.pos else 0.0 for c in carteiras]
    if not any(pesos):
        return []
    escolhidas = rng.choices(carteiras, weights=pesos, k=n)
    out, usadas = [], set()
    for c in escolhidas:
        livres = [s for s in c.pos if s not in usadas]
        if livres:
            s = rng.choice(livres)
            usadas.add(s)
            out.append((c, s))
    return out


# ---------------------------------------------------------------------------
# resumo e regra do B4
# ---------------------------------------------------------------------------


def _frac(x: int, n: int) -> tuple[Optional[float], float, float]:
    if n == 0:
        return None, 0.0, 1.0
    lo, hi = clopper_pearson(x, n)
    return x / n, lo, hi


def decidir(tx_dia: float, fr: dict[str, tuple[Optional[float], float, float]]) -> dict[str, Any]:
    """lambda_ef = TX/dia x f_compra x f_novo x (1-sobrep) x (1-f_curva) x (1-f_sem_dado) x (1-f_liq) x f_gt.
    Pessimista: limite inferior das fracoes de 'passa' e superior das de 'exclui'."""
    if any(v[0] is None for k, v in fr.items() if k != "sobreposicao"):
        return {"decisao": "indeterminado (fracao sem amostra)", "n_proj": None, "n_proj_pess": None}
    passa = ("f_compra", "f_novo")
    exclui = ("f_curva", "f_sem_dado", "f_liq_menor_5k", "sobreposicao")
    ponto = tx_dia * F_GT[0]
    pess = tx_dia * F_GT[1]
    for k in passa:
        ponto *= fr[k][0]
        pess *= fr[k][1]
    for k in exclui:
        ponto *= 1.0 - (fr[k][0] or 0.0)
        pess *= 1.0 - fr[k][2] if k != "sobreposicao" else 1.0 - (fr[k][0] or 0.0)
    n_ponto, n_pess = ponto * D_PROJECAO, pess * D_PROJECAO
    if n_ponto < N_MIN:
        dec = "NAO_RODA (redesenhar ou encerrar o B1)"
    elif n_pess < N_MIN:
        dec = "ZONA_CINZENTA (so roda com decisao explicita do operador, registrada antes de coletar precos)"
    else:
        dec = "SEGUE para o pre-registro"
    return {"decisao": dec, "n_proj": n_ponto, "n_proj_pess": n_pess, "lambda_ef": ponto, "lambda_ef_pess": pess}


def executar(rpc: RpcMedido, lista: Path, sol_usd: float, amostra: int, semente: int, max_paginas: int,
             agora: Optional[float] = None) -> str:
    from ..pos_runner import carteiras_pro
    agora = time.time() if agora is None else agora
    carteiras = [Carteira(e, n, g) for e, n, g in carteiras_pro.gerar_grupos(lista)]
    out = [f"# Piloto B1 (so contagens) — RPC={urlparse(rpc.url).hostname} | congelamento 2026-10-27 19:09:46 UTC",
           f"carteiras={len(carteiras)} pessoas={len({c.grupo for c in carteiras})} | sol_usd informado={sol_usd}"]
    abortado = ""
    classes: list[tuple[Carteira, Classificacao]] = []
    try:
        for c in carteiras:
            contar_carteira(rpc, c, agora, max_paginas)
        pares = sortear_amostra(carteiras, amostra, semente)
        for c, sig in pares:
            tx = rpc.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            classes.append((c, classificar_tx(tx, c.endereco, sol_usd) if tx else Classificacao("erro")))
    except Abortar as exc:
        abortado = str(exc)
    tx_dia = sum(c.taxa_dia for c in carteiras)
    validas = [k for _, k in classes if k.tipo != "erro"]
    compras = [(c, k) for c, k in classes if k.tipo == "compra"]
    novas = [(c, k) for c, k in compras if k.novo]
    fora_curva = [(c, k) for c, k in novas if k.curva is None]
    com_dado = [(c, k) for c, k in fora_curva if k.liq_usd is not None]
    mints_por_pessoa: dict[str, set[str]] = {}
    for c, k in compras:
        mints_por_pessoa.setdefault(k.mint, set()).add(c.grupo)
    sobrep = sum(1 for c, k in novas if len(mints_por_pessoa.get(k.mint, set()) - {c.grupo}) > 0)
    fr = {
        "f_compra": _frac(len(compras), len(validas)),
        "f_novo": _frac(len(novas), len(compras)),
        "f_curva": _frac(len(novas) - len(fora_curva), len(novas)),
        "f_sem_dado": _frac(len(fora_curva) - len(com_dado), len(fora_curva)),
        "f_liq_menor_5k": _frac(sum(1 for _, k in com_dado if k.liq_usd < LIQ_MIN_USD), len(com_dado)),
        "sobreposicao": _frac(sobrep, len(novas)),
    }
    dec = decidir(tx_dia, fr)
    out.append(f"TX_pos/dia (soma das carteiras, tx bem-sucedidas apos o congelamento) = {tx_dia:.1f} | "
               f"carteiras truncadas={sum(c.truncada for c in carteiras)} | sem tx pos={sum(not c.pos for c in carteiras)}")
    out.append(f"amostra: {len(classes)} tx ({Counter(k.tipo for _, k in classes)}) | curva por launchpad: "
               f"{dict(Counter(k.curva for _, k in novas if k.curva))}")
    for nome, (p, lo, hi) in fr.items():
        out.append(f"- {nome} = {'s/d' if p is None else f'{p:.3f}'} (IC95% {lo:.3f}-{hi:.3f})")
    vendas = [k.fracao_vendida for _, k in classes if k.tipo == "venda" and k.fracao_vendida is not None]
    if vendas:
        out.append(f"- vendas: n={len(vendas)}; fracao vendida >=25%: {sum(v >= .25 for v in vendas)}, "
                   f">=50%: {sum(v >= .5 for v in vendas)}, >=75%: {sum(v >= .75 for v in vendas)} (diagnostico do limiar)")
    out.append(f"- f_gt = {F_GT[0]} (pessimista {F_GT[1]}; Rodada 22, n=15)")
    if dec.get("n_proj") is not None:
        out.append(f"N_proj (D={D_PROJECAO}) = {dec['n_proj']:.0f} tokens (lambda_ef={dec['lambda_ef']:.2f}/dia) | "
                   f"pessimista = {dec['n_proj_pess']:.0f} ({dec['lambda_ef_pess']:.2f}/dia) | N_min={N_MIN} "
                   f"(alfa/2: {N_MIN_ALFA2})")
    out.append(f"DECISAO (regra B4): {dec['decisao']}")
    out.append(f"creditos gastos (contagem x tabela Helius): {rpc.creditos} {dict(rpc.chamadas)}"
               + (f" | PAROU: {abortado}" if abortado else ""))
    out.append("Nenhum preco, candle ou retorno foi lido. f_novo = 1a vez da carteira no token; sobreposicao "
               "entre pessoas so dentro da amostra (subestima).")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    from ..pos_runner import carteiras_pro
    ap = argparse.ArgumentParser(description="Piloto B1: contagens de compras das carteiras pro (sem preco).")
    ap.add_argument("--rpc-url", default=os.environ.get("PILOTO_B1_RPC_URL"))
    ap.add_argument("--sol-usd", type=float, required=True)
    ap.add_argument("--amostra", type=int, default=200)
    ap.add_argument("--semente", type=int, default=20261117)
    ap.add_argument("--max-paginas", type=int, default=1, help="paginas de 1000 assinaturas por carteira")
    ap.add_argument("--max-creditos", type=int, default=400)
    ap.add_argument("--lista", type=Path, default=carteiras_pro.LISTA_PATH)
    args = ap.parse_args(argv)
    if not args.rpc_url:
        ap.error("informe --rpc-url ou PILOTO_B1_RPC_URL")
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    rpc = RpcMedido(args.rpc_url, args.max_creditos)
    print(executar(rpc, args.lista, args.sol_usd, args.amostra, args.semente, args.max_paginas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
