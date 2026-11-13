"""PEDIDO 2026-11-10 (autorizado, Rodada 17, item 1): por sinal e origem, quantos candles corrompidos
existem nas janelas de 72h/7d pós-entrada, e quais toques (+5/+8/+10/+15/+20R) dependem de um desses
candles -- ou seja, dariam uma resposta DIFERENTE se o veto fosse o MESMO do caminho ao vivo
(`qualidade_candle.candle_confiavel_cb`, Rodada 17 item 1 parte 1) em vez do veto mais simples que os
scripts exploratórios já usam (`candles.candle_corrompido_provavel`). PAPER/READ-ONLY, SOMENTE LEITURA
no banco do bot -- zero chamada de rede, zero escrita em qualquer tabela. Detector/simulate/ParamsV3/
H1/critério de sinal NUNCA alterados.

Por que DOIS vetos diferentes existem (nunca escondido, ver docs/revisao-2026-11-10/PARTE_B_PIPELINE_
DADOS.md, achado P1): `candle_corrompido_provavel` (vol=0 OU high>10x AMBOS os vizinhos) já é usado
por `varredura_v3.py`/`simular_v3_carteira.py`/`saidas_parciais.py` (a grade de 24 variantes) pra
decidir toque/TP1/stop; `qualidade_candle.motivo_suspeito` é o veto MAIS AMPLO que o caminho ao vivo
usa (ohlc_incoerente, close muito acima do pico, candle isolado vs só 1 vizinho sem confirmação) e que
a Rodada 17 item 1 já aplicou em `horizonte_fixo.calcular_r_horizonte`. Este script mede o GAP entre
os dois: candles que o veto simples deixa passar mas o veto amplo vetaria -- e se esse gap muda a
resposta de algum toque específico.

Escopo explícito da checagem de "alvos da grade" (24 variantes de `saidas_parciais.py`): este script
NUNCA re-simula as 24 variantes com um veto diferente (isso duplicaria/alteraria a lógica congelada
por hash do pré-registro de saídas parciais, fora do que esta rodada autoriza) -- em vez disso, lista
quais sinais têm pelo menos 1 candle no "gap" dentro da janela de 72h/7d, como um sinal de RISCO
(precisa de reconferência manual se uma variante específica depender exatamente desse candle), nunca
uma prova de que o resultado de cada variante mudaria.

Uso (na VM, a partir da raiz do repo -- read-only, replay completo das 3 origens):
    nice -n 19 python -m signals_mvp.scripts.auditar_candles_corrompidos_sinais \
        --db signals_mvp/dados/estado.sqlite --csv auditoria_candles_corrompidos.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.candles import Bar, candle_corrompido_provavel
from ..pos_runner.horizonte_fixo import HORIZONTES_S
from ..pos_runner.qualidade_candle import candle_confiavel_cb
from . import retrospectivo_saida_fiel as rsf
from . import varredura_v3 as vv3
from .varredura_v3 import RAM_MINIMA_MB_PADRAO, SinalVarredura, checar_ram_ou_abortar

AVISO = "PAPER/READ-ONLY -- somente leitura, zero escrita, EXPLORATORIO/diagnostico."

# Alvos pedidos explicitamente (subconjunto de vv3.ALVOS_R -- nunca um numero novo inventado).
ALVOS_TOQUE: tuple[float, ...] = (5.0, 8.0, 10.0, 15.0, 20.0)


def _toque_causal_veto_pleno(bars: list[Bar], j0: int, entry_price: float, stop: float, alvo_r: float,
                            peak: Optional[float]) -> Optional[str]:
    """MESMA varredura de `varredura_v3._toque_causal`, mas pulando candles vetados pelo veto AMPLO
    (`qualidade_candle.candle_confiavel_cb`) em vez do veto simples (`candle_corrompido_provavel`) --
    nunca duplica a lógica de decisão (stop tem prioridade no mesmo candle, 'alvo' se high>=preco_alvo),
    só troca QUAL veto decide se o candle conta."""
    risk = entry_price - stop
    if risk <= 0:
        return None
    preco_alvo = entry_price + alvo_r * risk
    confiavel = candle_confiavel_cb(bars, peak)
    for idx in range(j0, len(bars)):
        if confiavel(idx) is not None:
            continue
        bar = bars[idx]
        if bar.low <= stop:
            return "stop"
        if bar.high >= preco_alvo:
            return "alvo"
    return None


def _candles_da_janela(sinal: SinalVarredura, horizonte_s: float) -> list[tuple[int, Bar]]:
    """(idx, bar) de TODO candle pós-entrada (idx >= j0) com ts <= t_entrada+horizonte -- a MESMA
    janela causal que `horizonte_fixo.calcular_r_horizonte` trunca, nunca um candle além do corte."""
    j0 = sinal.ev.idx + 1
    corte_ts = sinal.t_entrada + horizonte_s
    return [(idx, bar) for idx, bar in enumerate(sinal.bars) if idx >= j0 and bar.ts <= corte_ts]


class LinhaAuditoria:
    def __init__(self, origem: str, token: str, mint: str, pool: str) -> None:
        self.origem, self.token, self.mint, self.pool = origem, token, mint, pool
        self.n_corrompidos_simples: dict[str, int] = {"72h": 0, "7d": 0}
        self.n_corrompidos_pleno: dict[str, int] = {"72h": 0, "7d": 0}
        self.gap_candles: list[tuple[str, float, str]] = []   # (horizonte, ts, motivo)
        self.toques_divergentes: list[tuple[float, Optional[str], Optional[str]]] = []  # (alvo, atual, pleno)

    @property
    def exposto_grade(self) -> bool:
        return any(h == "72h" for h, _ts, _m in self.gap_candles) or any(
            h == "7d" for h, _ts, _m in self.gap_candles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origem": self.origem, "token": self.token, "mint": self.mint, "pool": self.pool,
            "n_corrompidos_simples_72h": self.n_corrompidos_simples["72h"],
            "n_corrompidos_pleno_72h": self.n_corrompidos_pleno["72h"],
            "n_corrompidos_simples_7d": self.n_corrompidos_simples["7d"],
            "n_corrompidos_pleno_7d": self.n_corrompidos_pleno["7d"],
            "n_gap_candles": len(self.gap_candles),
            "gap_candles_ts": ";".join(f"{h}:{int(ts)}:{m}" for h, ts, m in self.gap_candles),
            "toques_divergentes": ";".join(
                f"+{alvo:.0f}R:{atual or 's/d'}->  {pleno or 's/d'}" for alvo, atual, pleno in self.toques_divergentes),
            "exposto_grade_24_variantes": self.exposto_grade,
        }


def auditar_sinal(sinal: SinalVarredura, origem: str) -> LinhaAuditoria:
    linha = LinhaAuditoria(origem, sinal.token, sinal.mint, sinal.pool)
    peak = sinal.ev.data.get("TOPO")
    j0 = sinal.ev.idx + 1
    for nome_horizonte, horizonte_s in HORIZONTES_S.items():
        janela = _candles_da_janela(sinal, horizonte_s)
        if not janela:
            continue
        confiavel = candle_confiavel_cb(sinal.bars, peak)
        for idx, bar in janela:
            simples = candle_corrompido_provavel(sinal.bars, idx)
            motivo_pleno = confiavel(idx)
            pleno = motivo_pleno is not None
            if simples:
                linha.n_corrompidos_simples[nome_horizonte] += 1
            if pleno:
                linha.n_corrompidos_pleno[nome_horizonte] += 1
            if pleno and not simples:
                linha.gap_candles.append((nome_horizonte, float(bar.ts), motivo_pleno or ""))
    for alvo in ALVOS_TOQUE:
        atual = vv3._toque_causal(sinal.bars, j0, sinal.entry_price, sinal.stop, alvo)
        pleno = _toque_causal_veto_pleno(sinal.bars, j0, sinal.entry_price, sinal.stop, alvo, peak)
        if atual != pleno:
            linha.toques_divergentes.append((alvo, atual, pleno))
    return linha


def executar(db_path: Path, csv_path: Optional[Path] = None, progresso: bool = True,
            min_ram_mb: float = RAM_MINIMA_MB_PADRAO) -> str:
    checar_ram_ou_abortar(min_ram_mb)

    def status(msg: str) -> None:
        if progresso:
            print(f"[auditar_candles_corrompidos_sinais] {msg}", file=sys.stderr, flush=True)

    status("carregando ao_vivo...")
    ao_vivo = rsf.carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (universo_admitido, pode levar um tempo)...")
    replay = vv3.carregar_universo_admitido(db_path)
    status(f"replay_v3: {len(replay)} sinais. auditando candles por sinal...")

    linhas: list[LinhaAuditoria] = []
    for origem_label, sinais in (("ao_vivo", ao_vivo), ("retro_lote1", retro), ("replay_v3", replay)):
        for sinal in sinais:
            linhas.append(auditar_sinal(sinal, origem_label))
    status(f"{len(linhas)} sinais auditados. montando relatorio.")

    out = [f"# auditar_candles_corrompidos_sinais -- {AVISO}", "",
          "Veto SIMPLES (candle_corrompido_provavel: vol=0 OU high>10x AMBOS os vizinhos) -- ja usado "
          "pela varredura/grade. Veto AMPLO (qualidade_candle.motivo_suspeito) -- o MESMO do caminho "
          "ao vivo, agora tambem em horizonte_fixo.py (Rodada 17 item 1). 'gap' = candle que o AMPLO "
          "vetaria mas o SIMPLES deixa passar -- risco pras variantes/toques que so checam o simples.",
          ""]
    total_gap = sum(len(l.gap_candles) for l in linhas)
    total_divergente = sum(len(l.toques_divergentes) for l in linhas)
    expostos = sum(1 for l in linhas if l.exposto_grade)
    out.append(f"sinais auditados: {len(linhas)} | candles no gap (amplo-so): {total_gap} | "
              f"toques que divergem entre os 2 vetos: {total_divergente} | "
              f"sinais expostos (>=1 gap na janela, risco pra qualquer variante da grade): {expostos}")
    out.append("")
    for origem_label in ("ao_vivo", "retro_lote1", "replay_v3"):
        por_origem = [l for l in linhas if l.origem == origem_label]
        if not por_origem:
            out.append(f"## {origem_label}: 0 sinais")
            continue
        n_corrompidos_72h = sum(l.n_corrompidos_simples["72h"] for l in por_origem)
        n_gap_72h = sum(1 for l in por_origem for h, _ts, _m in l.gap_candles if h == "72h")
        out.append(f"## {origem_label}: {len(por_origem)} sinais | candles corrompidos (simples) em "
                  f"72h: {n_corrompidos_72h} | candles no gap em 72h: {n_gap_72h}")
        divergentes = [l for l in por_origem if l.toques_divergentes]
        if divergentes:
            out.append(f"  toques divergentes (token, pool, alvo, simples->amplo):")
            for l in divergentes[:50]:
                for alvo, atual, pleno in l.toques_divergentes:
                    out.append(f"    {l.token} ({l.pool[:8]}...) +{alvo:.0f}R: {atual or 's/d'} -> {pleno or 's/d'}")
            if len(divergentes) > 50:
                out.append(f"    ... e mais {len(divergentes) - 50} sinal(is) com divergencia (ver CSV)")
        expostos_origem = [l for l in por_origem if l.exposto_grade]
        if expostos_origem:
            out.append(f"  sinais expostos (gap na janela -- reconferir manualmente contra a grade de "
                      f"24 variantes se o resultado depender exatamente deste candle): "
                      f"{', '.join(f'{l.token} ({l.pool[:8]}...)' for l in expostos_origem[:20])}"
                      + (f", ... (+{len(expostos_origem) - 20})" if len(expostos_origem) > 20 else ""))
        out.append("")

    if csv_path is not None:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            campos = list(linhas[0].to_dict().keys()) if linhas else [
                "origem", "token", "mint", "pool", "n_corrompidos_simples_72h", "n_corrompidos_pleno_72h",
                "n_corrompidos_simples_7d", "n_corrompidos_pleno_7d", "n_gap_candles", "gap_candles_ts",
                "toques_divergentes", "exposto_grade_24_variantes"]
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            for l in linhas:
                writer.writerow(l.to_dict())
        out.append(f"(tabela completa, 1 linha por sinal, gravada em {csv_path})")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auditoria de candles corrompidos por sinal/origem (gap entre o veto simples ja "
                    "usado e o veto amplo do caminho ao vivo) -- PAPER/READ-ONLY/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--csv", type=Path, default=None, help="grava 1 linha por sinal em CSV")
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    args = parser.parse_args(argv)
    print(executar(args.db, csv_path=args.csv, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
