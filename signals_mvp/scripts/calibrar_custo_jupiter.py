"""RODADA 22 (pedido 2026-11-16, acrescimo a Fase A): CALIBRACAO DE CUSTO REAL por cotacao Jupiter
(somente leitura -- nenhuma transacao, nenhuma chave, nenhuma assinatura). PAPER/READ-ONLY.

Para cada token da amostra e cada tamanho (US$10, US$25): cota SOL->token (ExactIn) e, em seguida,
token->SOL com a quantidade recebida. Custo ida+volta = 1 - SOL_devolvido/SOL_enviado; custo por perna
= 1 - sqrt(1 - ida_e_volta). Isso mede FEE DE POOL + IMPACTO DE PRECO no instante da cotacao. NAO
inclui: terminal (1%/perna no `CostModel`), taxa base de rede, priority fee/Jito, MEV/sandwich,
latencia (preco anda entre sinal e envio), aluguel de ATA, falha de transacao. Comparado com
`CostModel` offline: 3,45%/perna = 1,25 fee + 1,0 terminal + 0,2 rede + 1,0 slippage
(`pos_runner/costs.py:56-75`) -- a parte comparavel com a cotacao e fee+slippage = 2,25%/perna.

Dois modos (separados de proposito):
  --exportar-amostra ARQ  (NA VM; so leitura de `pr_pools`, `mode=ro`): sorteia (semente fixa)
                          pools estratificados por idade desde a graduacao e grava CSV proprio.
                          Zero rede.
  --cotar ARQ             le o CSV, cota na Jupiter e resume. Liquidez atual = `liquidity` do
                          `price/v3` da Jupiter (por TOKEN, somando pools; 50 tokens/chamada) --
                          zero GeckoTerminal e zero RPC Solana, entao nao concorre com o orcamento
                          do bot (a Jupiter nao e usada pelo bot). Pode rodar na VM ou fora dela.
Nenhum dos dois le preco historico, R ou desfecho; a cotacao e do instante em que roda.

Uso:
    python -m signals_mvp.scripts.calibrar_custo_jupiter --db signals_mvp/dados/estado.sqlite \
        --exportar-amostra ~/amostra_custo.csv --n 120
    python -m signals_mvp.scripts.calibrar_custo_jupiter --cotar ~/amostra_custo.csv --saida ~/cotacoes.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

SOL = "So11111111111111111111111111111111111111112"
JUP_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUP_PRICE = "https://lite-api.jup.ag/price/v3"
TAMANHOS_USD = (10.0, 25.0)
CUSTO_POR_PERNA_COSTS_PY = 0.0345          # offline, sol_usd=None
FEE_MAIS_SLIPPAGE_COSTS_PY = 0.0225        # parte comparavel com a cotacao (sem terminal/rede)
FAIXAS_LIQ = ((0, 5_000, "<5k"), (5_000, 20_000, "5k-20k"), (20_000, 100_000, "20k-100k"),
              (100_000, 1_000_000, "100k-1M"), (1_000_000, float("inf"), ">=1M"))
FAIXAS_IDADE_D = ((0, 1, "<1d"), (1, 3, "1-3d"), (3, 7, "3-7d"), (7, 14, "7-14d"), (14, float("inf"), ">=14d"))
CAMPOS = ("pool", "mint", "launchpad", "grad_ts", "status", "mc_found", "liq_found")


class Abortar(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# modo 1: exportar amostra (na VM, so leitura)
# ---------------------------------------------------------------------------


def exportar_amostra(db: Path, destino: Path, n: int, semente: int, agora: float) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    try:
        rows = [r for r in con.execute("SELECT pool, mint, launchpad, grad_ts, status, mc_found, info FROM pr_pools "
                                       "WHERE mint IS NOT NULL AND grad_ts IS NOT NULL")]
    finally:
        con.close()
    estratos: dict[str, list[Any]] = {}
    for r in rows:
        idade = (agora - r["grad_ts"]) / 86400.0
        nome = next(lbl for lo, hi, lbl in FAIXAS_IDADE_D if lo <= idade < hi)
        estratos.setdefault(nome, []).append(r)
    rng = random.Random(semente)
    por_estrato = max(1, n // max(1, len(estratos)))
    escolhidos: list[Any] = []
    contagem: dict[str, int] = {}
    for nome in sorted(estratos):
        lista = sorted(estratos[nome], key=lambda r: r["pool"])
        pega = rng.sample(lista, min(por_estrato, len(lista)))
        escolhidos += pega
        contagem[nome] = len(pega)
    with destino.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CAMPOS)
        for r in escolhidos:
            try:
                liq = json.loads(r["info"] or "{}").get("liq_usd")
            except ValueError:
                liq = None
            w.writerow([r["pool"], r["mint"], r["launchpad"], int(r["grad_ts"]), r["status"], r["mc_found"], liq])
    return contagem


# ---------------------------------------------------------------------------
# modo 2: cotar (fora da VM)
# ---------------------------------------------------------------------------


def _get_json(url: str, timeout: float = 30.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "calibracao-custo"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        corpo = None
        try:
            corpo = json.load(exc)
        except Exception:
            pass
        return exc.code, corpo


class Ritmo:
    """1 chamada a cada `intervalo_s` por servico; 429 -> espera crescente; 3 seguidos -> aborta."""

    def __init__(self, intervalo_s: float, dormir: Callable[[float], None] = time.sleep):
        self.intervalo_s, self.dormir, self.ultima, self.seguidos = intervalo_s, dormir, 0.0, 0

    def chamar(self, url: str, get: Callable[[str], tuple[int, Any]] = _get_json) -> tuple[int, Any]:
        while True:
            espera = self.intervalo_s - (time.monotonic() - self.ultima)
            if espera > 0:
                self.dormir(espera)
            self.ultima = time.monotonic()
            st, dado = get(url)
            if st != 429:
                self.seguidos = 0
                return st, dado
            self.seguidos += 1
            if self.seguidos >= 3:
                raise Abortar(f"3 respostas 429 seguidas em {urllib.parse.urlparse(url).hostname}")
            self.dormir(30.0 * self.seguidos)


def custo_por_perna(ida_e_volta: float) -> float:
    return 1.0 - math.sqrt(max(0.0, 1.0 - ida_e_volta))


def cotar_ida_e_volta(mint: str, usd: float, sol_usd: float, jup: Ritmo) -> dict[str, Any]:
    lamports = int(usd / sol_usd * 1e9)
    q = {"inputMint": SOL, "outputMint": mint, "amount": lamports, "slippageBps": 300}
    st, ida = jup.chamar(f"{JUP_QUOTE}?{urllib.parse.urlencode(q)}")
    if st != 200 or not ida or "outAmount" not in ida:
        return {"status": "sem_rota_compra", "http": st, "erro": (ida or {}).get("errorCode") if isinstance(ida, dict) else None}
    tokens = int(ida["outAmount"])
    q2 = {"inputMint": mint, "outputMint": SOL, "amount": tokens, "slippageBps": 300}
    st2, volta = jup.chamar(f"{JUP_QUOTE}?{urllib.parse.urlencode(q2)}")
    if st2 != 200 or not volta or "outAmount" not in volta:
        return {"status": "sem_rota_venda", "http": st2,
                "erro": (volta or {}).get("errorCode") if isinstance(volta, dict) else None}
    sol_volta = int(volta["outAmount"])
    rt = 1.0 - sol_volta / lamports
    return {"status": "ok", "ida_e_volta": rt, "por_perna": custo_por_perna(rt),
            "impacto_compra_pct": float(ida.get("priceImpactPct") or 0) * 100,
            "impacto_venda_pct": float(volta.get("priceImpactPct") or 0) * 100,
            "rotas": [h["swapInfo"].get("label") for h in ida.get("routePlan", [])]}


def liquidez_jupiter(mints: list[str], jup: Ritmo, lote: int = 50) -> dict[str, Optional[float]]:
    """`liquidity` (USD, por token) do `price/v3`. Token ausente da resposta = None explicito."""
    out: dict[str, Optional[float]] = {}
    for i in range(0, len(mints), lote):
        parte = mints[i:i + lote]
        st, d = jup.chamar(f"{JUP_PRICE}?ids={','.join(parte)}")
        for m in parte:
            info = (d or {}).get(m) if st == 200 and isinstance(d, dict) else None
            out[m] = float(info["liquidity"]) if info and info.get("liquidity") is not None else None
    return out


def _quantil(v: list[float], p: float) -> Optional[float]:
    if not v:
        return None
    s = sorted(v)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def faixa(valor: Optional[float], faixas: tuple) -> str:
    if valor is None:
        return "s/d"
    return next(lbl for lo, hi, lbl in faixas if lo <= valor < hi)


def resumir(linhas: list[dict[str, Any]]) -> list[str]:
    out = ["| tamanho | liquidez atual (Jupiter, por token) | n tokens | sem rota | mediana/perna | p90/perna | max/perna |",
           "|---|---|---|---|---|---|---|"]
    for usd in TAMANHOS_USD:
        for _lo, _hi, lbl in FAIXAS_LIQ + ((None, None, "s/d"),):
            grupo = [l for l in linhas if l["usd"] == usd and l["faixa_liq"] == lbl]
            if not grupo:
                continue
            ok = [l["por_perna"] for l in grupo if l["status"] == "ok"]
            f = lambda x: "s/d" if x is None else f"{100 * x:.2f}%"
            out.append(f"| US${usd:.0f} | {lbl} | {len(grupo)} | {len(grupo) - len(ok)} | {f(_quantil(ok, .5))} | "
                       f"{f(_quantil(ok, .9))} | {f(max(ok) if ok else None)} |")
    out.append("")
    out.append("Referencia costs.py: 3,45%/perna no total; a parte comparavel (fee de pool + slippage) e 2,25%/perna. "
               "A cotacao NAO inclui terminal, rede, priority fee, MEV nem latencia.")
    return out


def cotar(entrada: Path, saida: Path, intervalo_jup: float = 1.5) -> list[str]:
    jup = Ritmo(intervalo_jup)
    st, p = jup.chamar(f"{JUP_PRICE}?ids={SOL}")
    sol_usd = float(p[SOL]["usdPrice"]) if st == 200 and p and SOL in p else None
    if not sol_usd:
        raise SystemExit("sem cotacao SOL/USD na Jupiter -- nada cotado (nunca chuta preco)")
    feitos = set()
    if saida.exists():
        feitos = {(json.loads(l)["pool"], json.loads(l)["usd"]) for l in saida.read_text().splitlines() if l.strip()}
    agora = time.time()
    linhas_csv = list(csv.DictReader(entrada.open()))
    liq = liquidez_jupiter(sorted({r["mint"] for r in linhas_csv}), jup)
    abortado = ""
    with saida.open("a") as fh:
        for row in linhas_csv:
            if all((row["pool"], usd) in feitos for usd in TAMANHOS_USD):
                continue
            try:
                reserva = liq.get(row["mint"])
                for usd in TAMANHOS_USD:
                    if (row["pool"], usd) in feitos:
                        continue
                    r = cotar_ida_e_volta(row["mint"], usd, sol_usd, jup)
                    idade = (agora - float(row["grad_ts"])) / 86400.0 if row.get("grad_ts") else None
                    r.update({"pool": row["pool"], "usd": usd, "reserva_usd": reserva, "sol_usd": sol_usd,
                              "faixa_liq": faixa(reserva, FAIXAS_LIQ), "faixa_idade": faixa(idade, FAIXAS_IDADE_D),
                              "ts": int(time.time())})
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
            except Abortar as exc:
                abortado = str(exc)
                break
    linhas = [json.loads(l) for l in saida.read_text().splitlines() if l.strip()]
    out = [f"SOL/USD={sol_usd:.2f} | cotacoes={len(linhas)}" + (f" | PAROU: {abortado}" if abortado else ""), ""]
    return out + resumir(linhas)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Calibracao de custo por cotacao Jupiter (somente leitura).")
    ap.add_argument("--db", type=Path, default=Path("signals_mvp/dados/estado.sqlite"))
    ap.add_argument("--exportar-amostra", type=Path)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--semente", type=int, default=20261117)
    ap.add_argument("--cotar", type=Path)
    ap.add_argument("--saida", type=Path, default=Path("cotacoes_jupiter.jsonl"))
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    if args.exportar_amostra:
        print(exportar_amostra(args.db, args.exportar_amostra, args.n, args.semente, time.time()))
    if args.cotar:
        print("\n".join(cotar(args.cotar, args.saida)))
    if not (args.exportar_amostra or args.cotar):
        ap.error("use --exportar-amostra e/ou --cotar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
