"""PEDIDO 2026-11-05 (autorizado, rodada 11, Parte B9): confere o detector V3 (`ParamsV3` CONGELADO,
`56762db29cd6`) contra exemplos QUE O OPERADOR fornece num CSV (`--exemplos`) -- NUNCA inventa casos
aqui (seria o proprio script "inventando a prova"); so le o que o operador escreveu e reporta se a
V3 gera ENTRADA dentro da janela esperada, e em que horario. PAPER/READ-ONLY -- zero chamada de
rede, zero escrita em qualquer tabela, NUNCA altera detector/parametros/criterio de sinal.

Formato do CSV (`--exemplos`), cabecalho EXATO obrigatorio:
  token_ou_pool -- symbol OU endereco do pool (resolvido em `pr_pools`; symbol com mais de 1 match
                   reporta TODOS os pools candidatos, nunca escolhe um sozinho)
  inicio        -- timestamp ISO8601 (UTC) ou epoch em segundos -- inicio da janela esperada
  fim           -- timestamp ISO8601 (UTC) ou epoch em segundos -- fim da janela esperada
  esperado      -- 'sinal' | 'descartar' | 'indefinido' | 'fora_do_setup'. SO 'sinal'/'descartar'
                   contam acerto/erro (bateu/divergiu); 'indefinido' (operador nao tem certeza) e
                   'fora_do_setup' (caso fora do escopo da V3, ex.: outro tipo de padrao) sao
                   listados EM SECAO SEPARADA, informativos, NUNCA contam como acerto nem erro.
  nota          -- texto livre (motivo/contexto; nunca interpretado pelo script, so impresso de volta)

Modelo (cabecalho + 1 linha PLACEHOLDER, nunca um caso real) em
`signals_mvp/scripts/exemplos_v3_modelo.csv` (NUNCA em `dados/`, que e gitignored -- precisa estar
versionado pra ser "entregue" de verdade, como o pedido exige).

Uso (na VM, a partir da raiz do repo):
    python -m signals_mvp.scripts.testar_exemplos_v3 --db signals_mvp/dados/estado.sqlite \
        --exemplos meus_exemplos.csv
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v3 import load_params_v3
from .avaliar_v3_retro import _conectar_ro, _created_ts
from .sensibilidade_parametros import _bars_do_pool

AVISO = ("PAPER/READ-ONLY -- confere a V3 CONGELADA contra exemplos do operador, NUNCA inventa "
        "caso, NUNCA altera detector/parametros/criterio de sinal.")

COLUNAS_OBRIGATORIAS = ("token_ou_pool", "inicio", "fim", "esperado", "nota")
ESPERADOS_AVALIAVEIS = ("sinal", "descartar")       # contam acerto/erro
ESPERADOS_INFORMATIVOS = ("indefinido", "fora_do_setup")   # listados a parte, NUNCA contam


def _parse_ts(valor: str) -> float:
    valor = valor.strip()
    try:
        return float(valor)
    except ValueError:
        pass
    dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@dataclasses.dataclass
class CasoExemplo:
    token_ou_pool: str
    inicio: float
    fim: float
    esperado: str
    nota: str


def carregar_exemplos(path: Path) -> list[CasoExemplo]:
    """Nunca inventa um caso -- so le o que esta no CSV do operador. Levanta `ValueError` explicito
    se faltar alguma coluna obrigatoria (nunca segue adiante com dado ausente silenciosamente)."""
    casos: list[CasoExemplo] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        faltando = set(COLUNAS_OBRIGATORIAS) - set(reader.fieldnames or [])
        if faltando:
            raise ValueError(f"CSV de exemplos sem as colunas obrigatorias: {sorted(faltando)}")
        for row in reader:
            if not (row.get("token_ou_pool") or "").strip():
                continue
            casos.append(CasoExemplo(
                token_ou_pool=row["token_ou_pool"].strip(), inicio=_parse_ts(row["inicio"]),
                fim=_parse_ts(row["fim"]), esperado=row["esperado"].strip().lower(),
                nota=(row.get("nota") or "").strip(),
            ))
    return casos


def _resolver_pools(con, token_ou_pool: str) -> list[str]:
    rows = con.execute("SELECT DISTINCT pool FROM pr_pools WHERE pool=? OR symbol=? OR mint=?",
                       (token_ou_pool, token_ou_pool, token_ou_pool)).fetchall()
    return [r["pool"] for r in rows]


@dataclasses.dataclass
class ResultadoCaso:
    caso: CasoExemplo
    pools_candidatos: list[str]
    sinal_gerado: bool
    horarios_sinal: list[float]
    bateu_esperado: Optional[bool]


def testar_caso(con, params, caso: CasoExemplo) -> ResultadoCaso:
    pools = _resolver_pools(con, caso.token_ou_pool)
    if not pools:
        return ResultadoCaso(caso, [], False, [], None)
    horarios: list[float] = []
    tf = params.timeframes[0]
    for pool in pools:
        row = con.execute("SELECT l_bc, grad_ts, info FROM pr_pools WHERE pool=?", (pool,)).fetchone()
        if row is None:
            continue
        bars = _bars_do_pool(con, pool, tf)
        if not bars:
            continue
        created_ts = _created_ts(row["info"])
        det = DetectorV1(params, tf, row["l_bc"], row["grad_ts"], created_ts)
        for bar in bars:
            for ev in det.update(bar):
                if ev.kind != "ENTRADA":
                    continue
                if caso.inicio <= ev.ts <= caso.fim:
                    horarios.append(float(ev.ts))
    sinal_gerado = len(horarios) > 0
    bateu: Optional[bool] = None
    if caso.esperado in ESPERADOS_AVALIAVEIS:
        bateu = sinal_gerado == (caso.esperado == "sinal")
    return ResultadoCaso(caso, pools, sinal_gerado, sorted(horarios), bateu)


def _linha_caso(r: ResultadoCaso, status: str) -> list[str]:
    c = r.caso
    if not r.pools_candidatos:
        linha = [f"- {c.token_ou_pool}: POOL NAO ENCONTRADO em pr_pools (nunca inventa um match) "
                f"-- esperado={c.esperado} | {status}"]
    else:
        pools_txt = ", ".join(r.pools_candidatos)
        horarios_txt = (", ".join(datetime.fromtimestamp(h, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                                  for h in r.horarios_sinal) if r.horarios_sinal else "nenhum")
        linha = [f"- {c.token_ou_pool} (pool(s)={pools_txt}): esperado={c.esperado} | "
                f"sinal_gerado={r.sinal_gerado} | horarios={horarios_txt} | {status}"]
    if c.nota:
        linha.append(f"    nota: {c.nota}")
    return linha


def formatar(resultados: list[ResultadoCaso]) -> str:
    out = ["# testar_exemplos_v3 -- confere a V3 congelada contra exemplos do operador", "",
          f"AVISO: {AVISO}", ""]
    avaliados = [r for r in resultados if r.caso.esperado in ESPERADOS_AVALIAVEIS]
    informativos = [r for r in resultados if r.caso.esperado in ESPERADOS_INFORMATIVOS]
    nao_reconhecidos = [r for r in resultados
                        if r.caso.esperado not in ESPERADOS_AVALIAVEIS + ESPERADOS_INFORMATIVOS]
    n_ok = sum(1 for r in avaliados if r.bateu_esperado)
    out.append(f"casos avaliados (esperado='sinal'/'descartar'): bateu {n_ok}/{len(avaliados)}")
    out.append("")
    for r in avaliados:
        out.extend(_linha_caso(r, "OK" if r.bateu_esperado else "DIVERGIU"))
    out.append("")
    if informativos:
        out.append("Casos informativos (esperado='indefinido'/'fora_do_setup') -- NUNCA contam "
                  "como acerto nem erro, so reportados:")
        for r in informativos:
            out.extend(_linha_caso(r, "informativo (nao avaliado)"))
        out.append("")
    if nao_reconhecidos:
        out.append("Casos com 'esperado' NAO RECONHECIDO (nunca inventa categoria -- revisar o "
                  f"CSV; valores validos: {', '.join(ESPERADOS_AVALIAVEIS + ESPERADOS_INFORMATIVOS)}):")
        for r in nao_reconhecidos:
            out.extend(_linha_caso(r, "s/d (esperado nao reconhecido)"))
        out.append("")
    return "\n".join(out)


def executar(db_path: Path, exemplos_path: Path) -> str:
    con = _conectar_ro(db_path)
    try:
        params = load_params_v3()
        casos = carregar_exemplos(exemplos_path)
        resultados = [testar_caso(con, params, c) for c in casos]
        return formatar(resultados)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Confere a V3 congelada contra exemplos do operador -- PAPER/so leitura.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--exemplos", required=True, type=Path,
                        help="CSV: token_ou_pool,inicio,fim,esperado,nota (ver scripts/exemplos_v3_modelo.csv)")
    args = parser.parse_args(argv)
    print(executar(args.db, args.exemplos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
