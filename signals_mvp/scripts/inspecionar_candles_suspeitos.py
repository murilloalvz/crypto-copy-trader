"""PEDIDO 2026-11-12 (autorizado, Rodada 18, item 1): inspeção visual/tabular, candle a candle, dos
sinais que `auditar_candles_corrompidos_sinais.py` já marcou como "expostos" (>=1 candle no gap entre
o veto simples e o veto amplo dentro da janela 72h/7d) -- ou de tickers específicos passados em
`--tokens`. Para cada toque +5/+8/+10/+15/+20R (`ALVOS_TOQUE`, mesmo conjunto da Rodada 17) e para
cada candle marcado pelo veto amplo, imprime a JANELA de candles em torno (OHLCV, razão do high
contra os 2 vizinhos, volume, motivo do veto, e a divergência contra a 2ª fonte DexPaprika quando
`pr1_dexpaprika_divergencias` tiver dado pra aquele candle/pool) e diz se o preço no candle decisivo é
PLAUSÍVEL (continuidade com os vizinhos -- nenhum motivo do veto amplo -- e volume>0) ou PROVÁVEL
ARTEFATO (motivo do veto amplo presente, e/ou volume=0). PAPER/READ-ONLY -- somente leitura no banco
do bot, zero chamada de rede, zero escrita em qualquer tabela. Detector/ParamsV1/V2/V3, H1 e os
hashes congelados (279b79ffa3f0/d57b4331d51d/56762db29cd6) NUNCA alterados -- este script nunca
re-decide nada, só mostra o candle por trás de um número já calculado.

Reusa `auditar_candles_corrompidos_sinais.auditar_sinal` (pra achar quem está "exposto", sem duplicar
a lógica de gap) e `qualidade_candle.candle_confiavel_cb`/`candles.candle_corrompido_provavel`/
`pr1_dexpaprika_divergencias` (MESMO cruzamento que o caminho ao vivo já usa, `live.py:
_candle_confiavel_cb`) -- zero veto novo inventado aqui.

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.inspecionar_candles_suspeitos --db signals_mvp/dados/estado.sqlite
    # só os tickers já vistos como suspeitos numa rodada anterior:
    python -m signals_mvp.scripts.inspecionar_candles_suspeitos --db signals_mvp/dados/estado.sqlite \
        --tokens PEAK,HIGH,paws
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import make_paths
from ..pos_runner.candles import Bar, candle_corrompido_provavel
from ..pos_runner.qualidade_candle import candle_confiavel_cb
from ..storage import Storage
from . import auditar_candles_corrompidos_sinais as acs
from . import retrospectivo_saida_fiel as rsf
from . import varredura_v3 as vv3
from .varredura_v3 import RAM_MINIMA_MB_PADRAO, SinalVarredura, checar_ram_ou_abortar

AVISO = "PAPER/READ-ONLY -- somente leitura, zero escrita, EXPLORATORIO/diagnostico."
RAIO_JANELA = 3   # candles pra cada lado do candle decisivo/marcado, na impressão


def _divergencias_por_pool(storage: Storage, pool: str) -> dict[int, list[Any]]:
    """{candle_ts: [linhas de pr1_dexpaprika_divergencias]} -- MESMA tabela/filtro por pool que
    `live.py: _candle_confiavel_cb` já usa (compartilhada por V1/V2/V3, nunca versionada)."""
    out: dict[int, list[Any]] = {}
    for r in storage.pr1_dexpaprika_divergencias():
        if r["pool"] != pool:
            continue
        out.setdefault(int(r["candle_ts"]), []).append(r)
    return out


def _divergencia_max_por_ts(div_por_ts: dict[int, list[Any]]) -> dict[int, float]:
    return {ts: max(r["diff_pct"] for r in linhas) for ts, linhas in div_por_ts.items()}


def _toque_decisivo(bars: list[Bar], j0: int, entry_price: float, stop: float, alvo_r: float,
                    vetado_fn: Callable[[int], bool]) -> Optional[tuple[str, int]]:
    """MESMA varredura causal de `varredura_v3._toque_causal`/`auditar_candles_corrompidos_sinais.
    _toque_causal_veto_pleno`, mas devolve tambem o INDICE do candle que decidiu -- só pra poder
    mostrar a janela em volta dele (nunca usado pra decidir nada, só pra exibir)."""
    risk = entry_price - stop
    if risk <= 0:
        return None
    preco_alvo = entry_price + alvo_r * risk
    for idx in range(j0, len(bars)):
        if vetado_fn(idx):
            continue
        bar = bars[idx]
        if bar.low <= stop:
            return "stop", idx
        if bar.high >= preco_alvo:
            return "alvo", idx
    return None


def _fmt_bar(idx: int, bar: Bar, destaque: bool, motivo: Optional[str],
            div_rows: Optional[list[Any]]) -> str:
    marca = ">>" if destaque else "  "
    divs = "; ".join(
        f"{r['campo']}:GT={r['valor_gt']:.6g} DexPaprika={r['valor_dexpaprika']:.6g} diff={r['diff_pct']:.1f}%"
        for r in (div_rows or [])) or "sem dado DexPaprika"
    motivo_txt = motivo or "confiavel (veto amplo)"
    return (f"{marca} idx={idx} ts={bar.ts} O={bar.open:.6g} H={bar.high:.6g} L={bar.low:.6g} "
          f"C={bar.close:.6g} V={bar.volume:.6g} | veto_amplo={motivo_txt} | {divs}")


def _janela(bars: list[Bar], idx: int, raio: int = RAIO_JANELA) -> list[int]:
    return list(range(max(0, idx - raio), min(len(bars), idx + raio + 1)))


def _imprimir_janela(bars: list[Bar], idx_central: int, confiavel: Callable[[int], Optional[str]],
                     div_por_ts: dict[int, list[Any]]) -> list[str]:
    out = []
    for idx in _janela(bars, idx_central):
        bar = bars[idx]
        motivo = confiavel(idx)
        out.append(_fmt_bar(idx, bar, idx == idx_central, motivo, div_por_ts.get(int(bar.ts))))
    return out


def _veredito(bar: Bar, motivo: Optional[str]) -> str:
    razoes = []
    if motivo is not None:
        razoes.append(f"veto amplo: {motivo}")
    if bar.volume <= 0:
        razoes.append("volume=0")
    if razoes:
        return f"PROVAVEL ARTEFATO ({'; '.join(razoes)})"
    return "PLAUSIVEL (continuidade com vizinhos, volume>0, sem motivo do veto amplo)"


def inspecionar_sinal(sinal: SinalVarredura, origem: str, storage: Storage) -> list[str]:
    out = [f"## {origem} -- {sinal.token} (mint={sinal.mint}, pool={sinal.pool})", ""]
    peak = sinal.ev.data.get("TOPO")
    j0 = sinal.ev.idx + 1
    div_por_ts = _divergencias_por_pool(storage, sinal.pool)
    divergencia_max = _divergencia_max_por_ts(div_por_ts)
    confiavel = candle_confiavel_cb(sinal.bars, peak, divergencia_max)

    def vetado_simples(idx: int) -> bool:
        return candle_corrompido_provavel(sinal.bars, idx)

    def vetado_amplo(idx: int) -> bool:
        return confiavel(idx) is not None

    out.append(f"entry_price={sinal.entry_price:.6g} stop={sinal.stop:.6g} topo={sinal.topo:.6g}")
    out.append("")
    for alvo in acs.ALVOS_TOQUE:
        simples = _toque_decisivo(sinal.bars, j0, sinal.entry_price, sinal.stop, alvo, vetado_simples)
        pleno = _toque_decisivo(sinal.bars, j0, sinal.entry_price, sinal.stop, alvo, vetado_amplo)
        out.append(f"### toque +{alvo:.0f}R")
        if simples is None and pleno is None:
            out.append("  (nunca decide em nenhum dos 2 vetos, nesta janela)")
            out.append("")
            continue
        if simples is not None:
            status_s, idx_s = simples
            bar_s = sinal.bars[idx_s]
            motivo_s = confiavel(idx_s)
            out.append(f"  veto SIMPLES decide '{status_s}' no idx={idx_s} (ts={bar_s.ts}) -- "
                      f"{_veredito(bar_s, motivo_s)}")
            out.extend(f"    {linha}" for linha in _imprimir_janela(sinal.bars, idx_s, confiavel, div_por_ts))
        else:
            out.append("  veto SIMPLES: nunca decide nesta janela")
        if pleno is not None:
            status_p, idx_p = pleno
            if simples is not None and idx_p == simples[1] and pleno[0] == simples[0]:
                out.append(f"  veto AMPLO decide IGUAL ao simples (idx={idx_p}, '{status_p}')")
            else:
                bar_p = sinal.bars[idx_p]
                motivo_p = confiavel(idx_p)
                out.append(f"  veto AMPLO decide '{status_p}' no idx={idx_p} (ts={bar_p.ts}) -- "
                          f"{_veredito(bar_p, motivo_p)}")
                out.extend(f"    {linha}" for linha in _imprimir_janela(sinal.bars, idx_p, confiavel, div_por_ts))
        else:
            out.append("  veto AMPLO: nunca decide nesta janela (candle(s) decisivo(s) do simples foram vetados)")
        out.append("")

    linha_auditoria = acs.auditar_sinal(sinal, origem)
    if linha_auditoria.gap_candles:
        out.append("### candles no GAP (vetados pelo amplo, passam no simples) dentro de 72h/7d")
        vistos: set[int] = set()
        for _horizonte, ts, motivo in linha_auditoria.gap_candles:
            idx_gap = next((i for i, b in enumerate(sinal.bars) if b.ts == ts), None)
            if idx_gap is None or idx_gap in vistos:
                continue
            vistos.add(idx_gap)
            out.append(f"  candle idx={idx_gap} ts={ts} -- motivo={motivo}")
            out.extend(f"    {linha}" for linha in _imprimir_janela(sinal.bars, idx_gap, confiavel, div_por_ts))
        out.append("")
    return out


def executar(db_path: Path, tokens: Optional[list[str]] = None, progresso: bool = True,
            min_ram_mb: float = RAM_MINIMA_MB_PADRAO) -> str:
    checar_ram_ou_abortar(min_ram_mb)
    tokens_filtro = {t.strip() for t in tokens} if tokens else None

    def status(msg: str) -> None:
        if progresso:
            print(f"[inspecionar_candles_suspeitos] {msg}", file=sys.stderr, flush=True)

    status("carregando ao_vivo...")
    ao_vivo = rsf.carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo)...")
    replay = vv3.carregar_universo_admitido(db_path)
    status(f"replay_v3: {len(replay)} sinais. selecionando sinais a inspecionar...")

    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        out = [f"# inspecionar_candles_suspeitos -- {AVISO}", ""]
        n_inspecionados = 0
        for origem_label, sinais in (("ao_vivo", ao_vivo), ("retro_lote1", retro), ("replay_v3", replay)):
            for sinal in sinais:
                if tokens_filtro is not None:
                    selecionado = sinal.token in tokens_filtro
                else:
                    selecionado = acs.auditar_sinal(sinal, origem_label).exposto_grade
                if not selecionado:
                    continue
                out.extend(inspecionar_sinal(sinal, origem_label, storage))
                n_inspecionados += 1
        if n_inspecionados == 0:
            out.append("(nenhum sinal exposto -- ou nenhum ticker de --tokens encontrado -- nesta base)")
        else:
            out.insert(1, f"{n_inspecionados} sinal(is) inspecionado(s).")
            out.insert(2, "")
        return "\n".join(out)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspeciona candle a candle os sinais 'expostos' (ou tickers escolhidos) -- "
                    "PAPER/READ-ONLY/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--tokens", type=str, default=None,
                        help="lista separada por virgula de tickers (ex.: PEAK,HIGH,paws) -- "
                             "por padrao, inspeciona todo sinal 'exposto' (>=1 candle no gap)")
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    args = parser.parse_args(argv)
    tokens = args.tokens.split(",") if args.tokens else None
    print(executar(args.db, tokens=tokens, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
