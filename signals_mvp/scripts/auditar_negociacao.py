"""PEDIDO 2026-11-03/05 (continuacao -- rotacao/capacidade, FRENTE B). SOMENTE LEITURA, zero chamada de rede
(abre o banco em `mode=ro`, mesmo padrao de `sensibilidade_parametros.py`/`diagnostico_vagas.py`).

Contexto: a rotacao hoje (`live.py: _rotacionar_vagas`) aposenta por MC atual < piso OU queda do pico
> 96%, com sem_fase > 24h/72h (conforme idade), NUNCA runner/pullback/posicao aberta -- volume e
holders NAO entram no criterio. Caso relatado: ANT e CHICO ficaram dias em sem_fase com MC>=100k (ou
seja, passariam no criterio de MC, mas continuam sem negociacao real).

Este script SO MEDE (nenhum criterio novo decide nada aqui): para TODO pool 'ativo' ou 'dormente',
volume em USD das ultimas 24h/72h (`pr_bars.v`, ja convertido pra USD em `to_mc_bars` -- soma direta,
nenhum numero novo), numero de candles 1h com volume exatamente 0 nas ultimas 24h, liquidez (reservas)
SE houver (`pr_pools.info.liq_usd` -- snapshot da descoberta, pode faltar: "s/d" explicito, nunca 0),
MC atual (ultimo candle) e horas em sem_fase (`pr_pools.sem_fase_desde`). Destaca ANT/CHICO (pedido
explicito) e os pools 'dormente' (aposentados pela rotacao atual).

NENHUM limiar e escolhido aqui -- so a medicao, pra decidir o criterio DEPOIS com dado real.

PEDIDO 2026-11-05 (FRENTE B, leitura): estende a lista de destaque (DESSA/NIO/MAMESUKE/FOCO/CAPY/
WASTED/XD, alem de ANT/CHICO) e acrescenta a fase atual (`pr_pools.fase_v1`/`fase_v2`, persistida a
cada ciclo por `live.py` -- nenhum calculo novo). Responde tambem: o GeckoTerminal OMITE intervalos
sem negociacao e `pos_runner/candles.py: fill_gaps` PREENCHE essas horas com candles "parados" (OHLC
= fechamento anterior, volume=0, `filled=True`) para o detector contar a duracao em candles de
verdade -- usado em TODO o pipeline (`series.py` ao vivo, `parte_a/pipeline.py`, replay retro). Isso
SIM distorce ATR (`DetectorV1.atr_before`: true range de um candle parado e sempre 0 -- some direto
na media de `atr_period` candles, sem excluir `filled`), a media de volume da caixa (`_gatilhos`/
`_check_zone`: `mean_vol = sum(b.volume for b in zone_bars)/len(zone_bars)`, candle parado conta
volume=0 -- puxa a media pra baixo, o que FACILITA (nao dificulta) `rompimento_volume` contra um
candle real seguinte) e a contagem de candles da caixa (`Zone.length`: `last - anchor + 1`, conta
TODOS os candles desde a ancora, parados ou nao -- uma caixa pode atingir `zone_min_candles` so com
candles sem negociacao real). `n_filled_24h`/`n_candles_24h` abaixo quantifica isso por pool, sem
corrigir nada (medicao, FRENTE C decide se/como agir).

Uso (na VM):
    python -m signals_mvp.scripts.auditar_negociacao --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Optional

from .sensibilidade_parametros import _bars_do_pool, _conectar_ro, _created_ts

DESTAQUE_SYMBOLS = ("DESSA", "NIO", "MAMESUKE", "FOCO", "CAPY", "WASTED", "XD", "ANT", "CHICO")


def _info(info_json: Optional[str]) -> dict[str, Any]:
    try:
        data = json.loads(info_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def medir_pool(con, row: Any, now: float) -> dict[str, Any]:
    bars = _bars_do_pool(con, row["pool"], "1h")
    vol_24h = sum(b.volume for b in bars if b.ts >= now - 24 * 3600.0)
    vol_72h = sum(b.volume for b in bars if b.ts >= now - 72 * 3600.0)
    bars_24h = [b for b in bars if b.ts >= now - 24 * 3600.0]
    n_vol_zero_24h = sum(1 for b in bars_24h if b.volume == 0.0)
    # PEDIDO 2026-11-05 (FRENTE B): `filled` (fill_gaps) marca o candle "parado" que o GT nunca
    # reportou -- conta SEPARADO de vol=0 real (um candle real pode ter volume 0 e nao ser `filled`,
    # embora raro) pra quantificar a distorcao de ATR/media de volume/caixa sem adivinhar limiar.
    n_filled_24h = sum(1 for b in bars_24h if b.filled)
    info = _info(row["info"])
    liq_usd = info.get("liq_usd")
    mc_atual = bars[-1].close if bars else None
    sem_fase_desde = row["sem_fase_desde"]
    horas_sem_fase = (now - sem_fase_desde) / 3600.0 if sem_fase_desde is not None else None
    created_ts = _created_ts(row["info"])
    idade_dias = (now - created_ts) / 86400.0 if created_ts is not None else None
    cols = row.keys()
    fase_v1 = row["fase_v1"] if "fase_v1" in cols else None
    fase_v2 = row["fase_v2"] if "fase_v2" in cols else None
    return {
        "pool": row["pool"], "symbol": row["symbol"] or row["pool"][:8], "status": row["status"],
        "vol_24h_usd": vol_24h, "vol_72h_usd": vol_72h, "n_candles_24h": len(bars_24h),
        "n_vol_zero_24h": n_vol_zero_24h, "n_filled_24h": n_filled_24h, "liq_usd": liq_usd,
        "mc_atual": mc_atual, "horas_sem_fase": horas_sem_fase, "idade_dias": idade_dias,
        "fase_v1": fase_v1, "fase_v2": fase_v2,
        "destaque": bool(row["symbol"] and row["symbol"].upper() in DESTAQUE_SYMBOLS) or row["status"] == "dormente",
    }


def medir(db_path: Path, now: Optional[float] = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    con = _conectar_ro(db_path)
    try:
        rows = con.execute("SELECT * FROM pr_pools WHERE status IN ('ativo', 'dormente')").fetchall()
        return [medir_pool(con, row, now) for row in rows]
    finally:
        con.close()


def _fmt_usd(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "s/d"


_CABECALHO = ("| token | status | fase (v1/v2) | vol 24h | vol 72h | candles vol=0 (24h) | "
             "candles filled/lacuna (24h) | liquidez | MC | sem_fase (h) | idade (d) |")
_SEPARADOR = "|---|---|---|---|---|---|---|---|---|---|---|"


def formatar(linhas: list[dict[str, Any]]) -> str:
    out = ["# auditar_negociacao -- volume/liquidez/MC/fase/sem_fase, ativos e dormentes (SOMENTE LEITURA)", "",
          "Rotacao atual: MC<piso OU queda>96%, sem_fase>24-72h, nunca runner/pullback/posicao -- "
          "volume e holders NAO entram. Nenhum limiar novo escolhido aqui, so medicao.", "",
          "`candles filled/lacuna (24h)`: GT nunca reporta hora sem negociacao -- `fill_gaps` PREENCHE "
          "com candle parado (vol=0, marcado `filled`) pro detector contar duracao; isso entra sem "
          "filtro no ATR (`atr_before`, TR=0 do candle parado) e na media de volume da caixa (`_gatilhos`/"
          "`_check_zone`), e conta normal na contagem de candles da caixa (`Zone.length`). Quanto maior "
          "essa fracao, mais a caixa/ATR/media estao sendo medidos sobre silencio, nao negociacao real.", ""]
    destaque = [l for l in linhas if l["destaque"]]
    if destaque:
        out.append(f"## Destaque (DESSA/NIO/MAMESUKE/FOCO/CAPY/WASTED/XD/ANT/CHICO/dormentes, {len(destaque)})")
        out.append("")
        out.append(_CABECALHO)
        out.append(_SEPARADOR)
        for l in destaque:
            out.append(_linha_md(l))
        out.append("")
    out.append(f"## Todos os pools ativos/dormentes ({len(linhas)})")
    out.append("")
    out.append(_CABECALHO)
    out.append(_SEPARADOR)
    for l in sorted(linhas, key=lambda x: (x["status"], x["symbol"])):
        out.append(_linha_md(l))
    return "\n".join(out)


def _linha_md(l: dict[str, Any]) -> str:
    sem_fase = f"{l['horas_sem_fase']:.0f}" if l["horas_sem_fase"] is not None else "s/d (runner/pullback)"
    idade = f"{l['idade_dias']:.1f}" if l["idade_dias"] is not None else "s/d"
    mc = _fmt_usd(l["mc_atual"])
    liq = _fmt_usd(l["liq_usd"]) if l["liq_usd"] is not None else "s/d"
    fase = f"{l['fase_v1'] or 's/d'}/{l['fase_v2'] or 's/d'}"
    return (f"| {l['symbol']} | {l['status']} | {fase} | {_fmt_usd(l['vol_24h_usd'])} | {_fmt_usd(l['vol_72h_usd'])} | "
           f"{l['n_vol_zero_24h']}/{l['n_candles_24h']} | {l['n_filled_24h']}/{l['n_candles_24h']} | "
           f"{liq} | {mc} | {sem_fase} | {idade} |")


def executar(db_path: Path) -> str:
    return formatar(medir(db_path))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="auditar_negociacao: volume/liquidez/MC/sem_fase (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
