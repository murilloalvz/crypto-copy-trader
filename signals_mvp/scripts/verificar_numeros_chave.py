"""PEDIDO 2026-11-10 (autorizado, Rodada 17, item 0): read-only, `--db`, recalcula do banco e
imprime com PASS/FAIL + tolerancia os numeros-chave pedidos nesta rodada. Zero chamada de rede,
zero escrita em qualquer tabela. Detector/ParamsV1/V2/V3, H1 e os hashes congelados
(`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`) nunca tocados.

Baseline numerico: o pedido verbatim desta rodada deu, por extenso, SO 3 pares numero-alvo --
"nº sinais/tokens por origem (ao_vivo 15/6, retro_lote1 38/16, replay_v3 88/30)". Essas 3 comparacoes
usam PASS/FAIL com tolerancia 0 (contagem inteira, precisa bater exato) contra `BASELINE_SINAIS_
TOKENS` abaixo. As demais metricas pedidas (vencidos 72h, R@72h medio/mediano por origem, P(+NR
antes de -1R) para N=1,2,3,5,8,10,15,20, distancia media ao topo anterior, contagem aberto/
perdido_offline) sao RECALCULADAS e IMPRESSAS, mas o pedido nunca deu um numero-alvo explicito pra
elas -- reportadas como [INFO], NUNCA um baseline inventado que ninguem citou por escrito. Ver
`docs/revisao-2026-11-10/PARTE_A_VERIFICACAO_NUMEROS.md`, achado P1 ("nº operacionais citados em
conversas nao tem trilha de auditoria commitada"): este script existe pra fechar exatamente esse
buraco daqui pra frente -- toda vez que rodar, a saida e um artefato comparavel, nunca so prosa.

Limitacao desta sessao (declare sem rodeio, mesma logica da Parte A da Rodada 16): este checkout
(sessao cloud isolada) NAO tem acesso ao banco SQLite ao vivo da VM (`.gitignore` exclui `*.sqlite`/
`*.db`) -- o script abaixo e o ENTREGAVEL, pronto pra rodar na VM contra o banco real; o resultado
PASS/FAIL de verdade (inclusive se os 15/6, 38/16, 88/30 citados reproduzem ou nao) so existe quando
o operador roda isto lá (ver item 8 desta rodada pro comando exato + tempo estimado).

Reusa `rsf.carregar_ao_vivo`/`vv3.carregar_retro_lote1`/`vv3.carregar_universo_admitido` (replay_v3)
pra carregar os sinais, `rsf.agregar_horizonte` pro vencido/R@72h, `vv3.calcular_equilibrio_empirico`
pra curva de toque, e `auditoria_fidelidade_v3.resumo_b1_topo_anterior` (via `_de_sinal_varredura`,
conversao em memoria, sem 2o replay do banco) pra distancia ao topo -- zero logica nova duplicada.

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.verificar_numeros_chave --db signals_mvp/dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path
from typing import Optional

from ..config import make_paths
from ..pos_runner.costs import CostModel
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage
from . import auditoria_fidelidade_v3 as afv3
from . import retrospectivo_saida_fiel as rsf
from . import varredura_v3 as vv3
from .varredura_v3 import RAM_MINIMA_MB_PADRAO, checar_ram_ou_abortar

AVISO = "PAPER/READ-ONLY -- somente leitura, zero escrita, EXPLORATORIO/diagnostico."

# Unico baseline numerico citado por extenso no pedido verbatim desta rodada (item 0) -- tolerancia
# 0 (contagem inteira). (n_sinais, n_tokens_distintos_por_mint).
BASELINE_SINAIS_TOKENS: dict[str, tuple[int, int]] = {
    "ao_vivo": (15, 6), "retro_lote1": (38, 16), "replay_v3": (88, 30),
}


def _linha_pass_fail(rotulo: str, esperado: int, obtido: int) -> str:
    status = "PASS" if esperado == obtido else "FAIL"
    diff = obtido - esperado
    sinal = "+" if diff > 0 else ""
    return f"  [{status}] {rotulo}: esperado={esperado} obtido={obtido} (diff={sinal}{diff})"


def _fmt(v: Optional[float], casas: int = 4) -> str:
    return f"{v:.{casas}f}" if v is not None else "s/d"


def verificar_origem(label: str, sinais: list[vv3.SinalVarredura], now: float) -> list[str]:
    out = [f"## {label}", ""]
    esperado_sinais, esperado_tokens = BASELINE_SINAIS_TOKENS[label]
    n_sinais = len(sinais)
    n_tokens = len({s.mint for s in sinais})
    out.append(_linha_pass_fail("n sinais", esperado_sinais, n_sinais))
    out.append(_linha_pass_fail("n tokens distintos (por mint, nunca por symbol/ticker)",
                                esperado_tokens, n_tokens))
    if not sinais:
        out.append("  (sem sinais nesta origem -- demais metricas nao se aplicam)")
        out.append("")
        return out

    params = load_params_v3()
    costs = CostModel()
    r72 = rsf.agregar_horizonte(sinais, "72h", now, params, costs)
    out.append(f"  [INFO] vencidos 72h (resolvido+marcado, com ou sem TP1): {r72.n_vencido} "
              f"(pendente={r72.n_pendente} sem_dado={r72.n_sem_dado})")
    out.append(f"  [INFO] R@72h (saida oficial A, horizonte_fixo.calcular_r_horizonte) -- "
              f"medio={_fmt(r72.saida_atual_a.media)} mediana={_fmt(r72.saida_atual_a.mediana)} "
              f"(n={r72.saida_atual_a.n})")
    out.append(f"  [INFO] R@72h (saida FIEL, retrospectivo_saida_fiel, Rodada 12) -- "
              f"medio={_fmt(r72.saida_fiel.media)} mediana={_fmt(r72.saida_fiel.mediana)} "
              f"(n={r72.saida_fiel.n})")

    equilibrio = vv3.calcular_equilibrio_empirico(sinais, params)
    curva = ", ".join(
        f"+{int(alvo)}R={equilibrio[alvo]['p_empirico_pct']:.1f}%"
        if equilibrio[alvo]["p_empirico_pct"] is not None else f"+{int(alvo)}R=s/d"
        for alvo in vv3.ALVOS_R)
    out.append(f"  [INFO] P(+NR antes de -1R), equilibrio EMPIRICO K=20 (N=1,2,3,5,8,10,15,20): {curva}")

    sinais_auditoria = [s for s in (afv3._de_sinal_varredura(sig, label) for sig in sinais) if s is not None]
    if sinais_auditoria:
        b1 = afv3.resumo_b1_topo_anterior(sinais_auditoria)
        out.append(f"  [INFO] distancia media ao topo anterior: {_fmt(b1.distancia_pct_media, 1)}% "
                  f"| em unidades de R: {_fmt(b1.distancia_r_media, 2)} (n={b1.n})")
    out.append("")
    return out


def verificar_aberto_perdido_offline(db_path: Path) -> list[str]:
    """Contagem aberto/perdido_offline -- propriedade do fluxo AO VIVO (`pr3_signals.status`); retro_
    lote1/replay_v3 sao replays totalmente resolvidos, sem essa nocao de posicao aberta."""
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        n_aberto = len(storage.pr3_signals(status="aberto"))
        n_perdido_offline = len(storage.pr3_signals(status="perdido_offline"))
    finally:
        storage.close()
    return ["## V3 ao vivo -- status persistido (pr3_signals)", "",
          f"  [INFO] aberto: {n_aberto} | perdido_offline: {n_perdido_offline}", ""]


def executar(db_path: Path, now: Optional[float] = None, progresso: bool = True,
            min_ram_mb: float = RAM_MINIMA_MB_PADRAO) -> str:
    checar_ram_ou_abortar(min_ram_mb)
    now = now if now is not None else time.time()

    def status(msg: str) -> None:
        if progresso:
            print(f"[verificar_numeros_chave] {msg}", file=sys.stderr, flush=True)

    status("carregando ao_vivo...")
    ao_vivo = rsf.carregar_ao_vivo(db_path)
    status(f"ao_vivo: {len(ao_vivo)} sinais. carregando retro_lote1...")
    retro = vv3.carregar_retro_lote1(db_path)
    status(f"retro_lote1: {len(retro)} sinais. carregando replay_v3 (pode levar um tempo)...")
    replay = vv3.carregar_universo_admitido(db_path)
    status(f"replay_v3: {len(replay)} sinais. calculando metricas...")

    out = [f"# verificar_numeros_chave -- {AVISO}", "",
          "PASS/FAIL com tolerancia 0 so pra n_sinais/n_tokens (unico baseline numerico citado por "
          "extenso no pedido). As demais linhas [INFO] sao recalculadas e impressas sem comparacao "
          "-- o pedido nao deu numero-alvo explicito pra elas (ver docstring do script).", ""]
    out.extend(verificar_origem("ao_vivo", ao_vivo, now))
    out.extend(verificar_origem("retro_lote1", retro, now))
    out.extend(verificar_origem("replay_v3", replay, now))
    out.extend(verificar_aberto_perdido_offline(db_path))
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recalcula do banco e compara (PASS/FAIL) os numeros-chave citados na Rodada "
                    "17 -- PAPER/READ-ONLY/EXPLORATORIO.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sem-progresso", action="store_true", help="nao imprime progresso em stderr")
    parser.add_argument("--min-ram-mb", type=float, default=RAM_MINIMA_MB_PADRAO,
                        help="aborta se a RAM disponivel ficar abaixo disso (MB)")
    args = parser.parse_args(argv)
    print(executar(args.db, progresso=not args.sem_progresso, min_ram_mb=args.min_ram_mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
