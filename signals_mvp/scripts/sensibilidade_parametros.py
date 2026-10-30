"""PEDIDO 2026-10-29 (auditoria+sensibilidade+sombra+radar), item 2: SENSIBILIDADE offline dos
parametros de gatilho/entrada/stop/saida da V1/V2 (ver `docs/pos-runner-v1/AUDITORIA_PARAMETROS.md`).

SOMENTE LEITURA, zero chamada nova a GeckoTerminal/DexPaprika/RPC: le os candles JA guardados em
`pr_bars` (abre o SQLite em `file:...?mode=ro`, igual a `scripts/auditar_trades.py` -- nunca passa
por `Storage`, que roda migracao no `__init__`) e roda o MESMO `DetectorV1` em memoria, variando UM
parametro por vez (um passo "relaxado" -- mais permissivo -- e um "restrito" -- mais estrito).
NUNCA escreve nada; NUNCA toca `ParamsV1`/`pos_runner_v1.yaml`/`pos_runner_v2.yaml` (constroi objetos
`ParamsV1` temporarios em memoria via `dataclasses.replace`, a config congelada nunca e lida de volta
no disco nem gravada).

O que conta como "sinal": evento `ENTRADA` do detector (gatilho real, nao WATCHLIST/TESTE/RUNNER).
"Near-miss" = zona que ficou `armed` (emitiu WATCHLIST) na rodada BASE mas nunca gerou ENTRADA, e que
PASSA a gerar ENTRADA na rodada com o parametro RELAXADO (mesmo `zona` id -- valido quando o
parametro testado e interno a zona/gatilho; para os 3 parametros que mudam quando a propria
onda/zona COMECA -- `drop_min`, `drop_max`, `runner_min_mc` -- o id de zona pode nao alinhar entre as
2 rodadas, o que SUBESTIMA o near-miss desses 3; documentado explicitamente no relatorio, nao
corrigido aqui por seria um matcher muito mais complexo para o que o pedido exige).

Parametros cujo VALOR muda mas nunca pode mudar se um ENTRADA aparece (so afetam exaustao/stop/
tag, nunca o gatilho em si) ficam de fora desta tabela, com nota: `tp1_frac`, `exhaustion_wick_mult`,
`exhaustion_doji_frac`, `stop_below_wick_pct`, `risk_min`/`risk_max` (ATRIBUTO), `peak_attr_mc`
(ATRIBUTO), `l_bc_suspeito_baixo_usd`/`l_bc_suspeito_alto_usd` (so tag, nunca bloqueia).

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.sensibilidade_parametros --db dados/estado.sqlite --versao v1
    python -m signals_mvp.scripts.sensibilidade_parametros --db dados/estado.sqlite --versao v2

PEDIDO 2026-10-30 (passos mais largos): `--passo largo` (padrao continua `--passo padrao`, output
IDENTICO ao de antes) acrescenta uma 2a secao so com valores ABSOLUTOS mais distantes da base, na
MESMA direcao "relaxada" ja documentada acima, para 4 parametros: `zone_min_candles` 12->8/6/4,
idade minima 2d->1,5/1,0, `drop_min` 80%->75/70, `recover_mult` 1,25->1,15/1,05. Mesma mecanica
(SOMENTE LEITURA, `dataclasses.replace` em memoria, nunca grava `ParamsV1`/yaml/hash) -- uma
combinacao invalida (ex.: `recover_mult=1,05` bate no piso `> 1+test_zone`) e pulada, nunca forcada.
    python -m signals_mvp.scripts.sensibilidade_parametros --db dados/estado.sqlite --versao v1 --passo largo
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..pos_runner.candles import Bar
from ..pos_runner.detector_v1 import DetectorV1
from ..pos_runner.params_v1 import ParamsV1, load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.qualidade_v1 import avaliar_qualidade


def _conectar_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _bars_do_pool(con: sqlite3.Connection, pool: str, tf: str) -> list[Bar]:
    rows = con.execute(
        "SELECT ts,o,h,l,c,v,filled FROM pr_bars WHERE pool=? AND tf=? ORDER BY ts", (pool, tf)
    ).fetchall()
    return [Bar(int(r["ts"]), r["o"], r["h"], r["l"], r["c"], r["v"], bool(r["filled"])) for r in rows]


def _pools_acompanhados(con: sqlite3.Connection) -> list[sqlite3.Row]:
    """"Pools acompanhados" = status ativo em `pr_pools` (mesmo universo do heartbeat/saude.py)."""
    return con.execute("SELECT pool, l_bc, grad_ts, info FROM pr_pools WHERE status='ativo'").fetchall()


def _fases_cache(con: sqlite3.Connection, pools: list[str]) -> tuple[int, int]:
    """PEDIDO 2026-10-30: conta, dentro do MESMO universo em cache usado pela sensibilidade (pools
    com candles em `pr_bars` p/ este tf), quantos estao sem_fase/dead vs em fase ativa (runner OU
    pullback, V1 OU V2) -- le `pr_pools.fase_v1`/`fase_v2`, a MESMA coluna persistida a cada ciclo
    que ja alimenta o heartbeat/`saude.py` (nunca recalculada aqui, zero logica nova de fase)."""
    if not pools:
        return 0, 0
    placeholders = ",".join("?" for _ in pools)
    rows = con.execute(f"SELECT fase_v1, fase_v2 FROM pr_pools WHERE pool IN ({placeholders})", pools).fetchall()
    sem_fase = ativa = 0
    for r in rows:
        f1 = r["fase_v1"] or "sem_fase"
        f2 = r["fase_v2"] or "sem_fase"
        if f1 in ("runner", "pullback") or f2 in ("runner", "pullback"):
            ativa += 1
        else:
            sem_fase += 1
    return sem_fase, ativa


def _created_ts(info_json: Optional[str]) -> Optional[float]:
    try:
        info = json.loads(info_json or "{}")
    except ValueError:
        info = {}
    v = info.get("criado_ts") if isinstance(info, dict) else None
    return None if v is None else float(v)


@dataclasses.dataclass(frozen=True)
class VariacaoParametro:
    nome: str
    passo_relaxado: Any   # valor do PASSO (somado ao valor base) na direcao MAIS PERMISSIVA
    passo_restrito: Any   # valor do PASSO na direcao MAIS RESTRITIVA
    descricao: str


# Direcao "relaxada" documentada por parametro -- ver docstring do modulo e AUDITORIA_PARAMETROS.md.
VARIACOES: tuple[VariacaoParametro, ...] = (
    VariacaoParametro("zone_min_candles", -1, +1, "minimo de candles da caixa, ±1 candle"),
    VariacaoParametro("wicks_min", -1, +1, "minimo de wicks de rejeicao, ±1"),
    VariacaoParametro("wicks_max", +1, -1, "maximo de wicks de rejeicao, ±1"),
    VariacaoParametro("test_zone", +0.02, -0.02, "proximidade do suporte, ±2pp"),
    VariacaoParametro("recover_mult", -0.05, +0.05, "multiplicador de recuperacao da zona, ±0.05x"),
    VariacaoParametro("power_atr_mult", -0.5, +0.5, "multiplicador do ATR p/ power candle, ±0.5x"),
    VariacaoParametro("vol_mult", -0.5, +0.5, "multiplicador de volume, ±0.5x"),
    VariacaoParametro("drop_min", -0.02, +0.02, "queda minima p/ iniciar a zona, ±2pp"),
    VariacaoParametro("drop_max", +0.02, -0.02, "queda maxima antes de invalidar a onda, ±2pp"),
    VariacaoParametro("runner_min_mc", -30_000.0, +30_000.0, "pico minimo (fase runner), ±10%"),
    VariacaoParametro("min_mc_usd", -10_000.0, +10_000.0, "MC atual minimo (anti-lixo), ±10%"),
    VariacaoParametro("candle_wick_ratio_max", +0.5, -0.5, "teto de wick do 1o candle (dado_invalido), ±0.5x"),
    VariacaoParametro("l_bc_floor_usd", -1_000.0, +1_000.0, "piso de L_bc (dado_invalido), ±1000 USD"),
    VariacaoParametro("l_bc_ceiling_usd", +1_000_000.0, -1_000_000.0, "teto de L_bc (dado_invalido), ±1M USD"),
    # periodo do ATR: a direcao de permissividade NAO e monotonica (so muda a magnitude do ATR
    # medido, nunca um teto/piso fixo) -- reportado sem rotulo relaxado/restrito, so o delta nas 2
    # direcoes (±5 candles); near-miss nao e computado para este parametro.
    VariacaoParametro("atr_period", -5, +5, "periodo do ATR, ±5 candles (sem direcao clara)"),
)
AGE_MIN_STEP = 0.5   # dias
AGE_MAX_STEP = 1.0   # dias


def _aplicar_delta(base: ParamsV1, nome: str, delta: Any) -> Optional[ParamsV1]:
    novo_valor = getattr(base, nome) + delta
    if isinstance(getattr(base, nome), int):
        novo_valor = int(round(novo_valor))
    try:
        return dataclasses.replace(base, **{nome: novo_valor})
    except ValueError:
        return None   # combinacao invalida (ex.: wicks_min > wicks_max) -- pulada, nunca forcada


def _variar_idade(base: ParamsV1, qual: str, delta: float) -> Optional[ParamsV1]:
    lo, hi = base.age_window_days
    novo = (lo + delta, hi) if qual == "min" else (lo, hi + delta)
    try:
        return dataclasses.replace(base, age_window_days=novo)
    except ValueError:
        return None


def _aplicar_absoluto(base: ParamsV1, nome: str, valor: Any) -> Optional[ParamsV1]:
    """PEDIDO 2026-10-30 (`--passo largo`): mesma mecanica de `_aplicar_delta`, so que recebe o
    valor FINAL (absoluto), nao um delta -- mais claro pros 4 parametros pedidos (ex.:
    `zone_min_candles=8`, nao "delta -4")."""
    if isinstance(getattr(base, nome), int):
        valor = int(round(valor))
    try:
        return dataclasses.replace(base, **{nome: valor})
    except ValueError:
        return None   # combinacao invalida -- pulada, nunca forcada (mesma regra de `_aplicar_delta`)


def _construir_idade_min_absoluta(base: ParamsV1, valor: float) -> Optional[ParamsV1]:
    lo, hi = base.age_window_days
    try:
        return dataclasses.replace(base, age_window_days=(valor, hi))
    except ValueError:
        return None


@dataclasses.dataclass(frozen=True)
class VariacaoLarga:
    nome: str
    valores: tuple   # valores ABSOLUTOS, na MESMA direcao "relaxada" de VARIACOES, so mais distante
    descricao: str
    construir: Any   # (base, valor) -> Optional[ParamsV1]


# PEDIDO 2026-10-30: passos mais largos, so para estes 4 parametros, SEMPRE na direcao "relaxada"
# ja documentada em VARIACOES (box menor/idade minima menor/queda-minima menor/recover_mult menor =
# mais permissivo) -- nunca um parametro novo, nunca uma direcao nova.
def _construtor_absoluto(nome: str):
    return lambda base, valor: _aplicar_absoluto(base, nome, valor)


VARIACOES_LARGAS: tuple[VariacaoLarga, ...] = (
    VariacaoLarga("zone_min_candles", (8, 6, 4), "minimo de candles da caixa (base 12)",
                 _construtor_absoluto("zone_min_candles")),
    VariacaoLarga("age_window_days (minimo)", (1.5, 1.0), "idade minima em dias (base 2,0)",
                 _construir_idade_min_absoluta),
    VariacaoLarga("drop_min", (0.75, 0.70), "queda minima p/ iniciar a zona (base 80%)",
                 _construtor_absoluto("drop_min")),
    VariacaoLarga("recover_mult", (1.15, 1.05), "multiplicador de recuperacao da zona (base 1,25x)",
                 _construtor_absoluto("recover_mult")),
)


def _pool_elegivel(bars: list[Bar], params: ParamsV1) -> bool:
    """Mesmo gate de `live.py: _detector_v1`/`_detector_v2` ANTES do detector existir:
    `dado_invalido` (candle_wick_ratio_max/l_bc_floor_usd/l_bc_ceiling_usd) e MC atual < min_mc_usd."""
    qual = avaliar_qualidade(bars, params)
    if not qual.valido:
        return False
    mc_atual = bars[-1].close if bars else None
    if mc_atual is not None and mc_atual < params.min_mc_usd:
        return False
    return True


def _rodar(bars: list[Bar], params: ParamsV1, l_bc: Optional[float], grad_ts: Optional[float],
          created_ts: Optional[float]) -> tuple[int, set, set]:
    """(n_entradas, zonas_armadas_sem_entrada, zonas_com_entrada) -- 0/vazio/vazio se o pool nem
    chega a ganhar detector (gate de qualidade/MC, replica `_pool_elegivel`)."""
    if not bars or not _pool_elegivel(bars, params):
        return 0, set(), set()
    det = DetectorV1(params, params.timeframes[0], l_bc, grad_ts, created_ts)
    for bar in bars:
        det.update(bar)
    armadas = {e.data.get("zona") for e in det.events if e.kind == "WATCHLIST"}
    com_entrada = {e.data.get("zona") for e in det.events if e.kind == "ENTRADA"}
    n_entradas = sum(1 for e in det.events if e.kind == "ENTRADA")
    return n_entradas, armadas - com_entrada, com_entrada


def _coletar_pools(con: sqlite3.Connection, tf: str) -> list[tuple]:
    out = []
    for row in _pools_acompanhados(con):
        if row["l_bc"] is None:
            continue
        bars = _bars_do_pool(con, row["pool"], tf)
        if bars:
            out.append((row["pool"], bars, row["l_bc"], row["grad_ts"], _created_ts(row["info"])))
    return out


def _linha_variacao(pools: list[tuple], base: ParamsV1, base_por_pool: dict, nome: str, descricao: str,
                    passo_relaxado: Any, passo_restrito: Any, params_relaxado: Optional[ParamsV1],
                    params_restrito: Optional[ParamsV1]) -> dict[str, Any]:
    linha: dict[str, Any] = {"parametro": nome, "descricao": descricao}
    for direcao, params_var in (("relaxado", params_relaxado), ("restrito", params_restrito)):
        if params_var is None:
            linha[direcao] = None
            continue
        delta_entradas, near_miss = 0, 0
        for pool, bars, l_bc, grad_ts, created_ts in pools:
            n_base, sem_entrada_base, _ = base_por_pool[pool]
            n_var, _, com_entrada_var = _rodar(bars, params_var, l_bc, grad_ts, created_ts)
            delta_entradas += n_var - n_base
            if direcao == "relaxado" and sem_entrada_base:
                near_miss += len(sem_entrada_base & com_entrada_var)
        linha[direcao] = {"delta_sinais": delta_entradas, "near_miss": near_miss if direcao == "relaxado" else None}
    return linha


def avaliar_sensibilidade(con: sqlite3.Connection, base: ParamsV1) -> list[dict[str, Any]]:
    pools = _coletar_pools(con, base.timeframes[0])
    base_por_pool = {pool: _rodar(bars, base, l_bc, grad_ts, created_ts)
                     for pool, bars, l_bc, grad_ts, created_ts in pools}
    linhas = []
    for v in VARIACOES:
        p_relax = _aplicar_delta(base, v.nome, v.passo_relaxado)
        p_restr = _aplicar_delta(base, v.nome, v.passo_restrito)
        linhas.append(_linha_variacao(pools, base, base_por_pool, v.nome, v.descricao,
                                      v.passo_relaxado, v.passo_restrito, p_relax, p_restr))
    # idade (tupla, min e max separados -- min relaxa diminuindo, max relaxa aumentando)
    p_min_relax = _variar_idade(base, "min", -AGE_MIN_STEP)
    p_min_restr = _variar_idade(base, "min", +AGE_MIN_STEP)
    linhas.append(_linha_variacao(pools, base, base_por_pool, "age_window_days (minimo)",
                                  f"idade minima, ±{AGE_MIN_STEP}d", -AGE_MIN_STEP, +AGE_MIN_STEP,
                                  p_min_relax, p_min_restr))
    p_max_relax = _variar_idade(base, "max", +AGE_MAX_STEP)
    p_max_restr = _variar_idade(base, "max", -AGE_MAX_STEP)
    linhas.append(_linha_variacao(pools, base, base_por_pool, "age_window_days (maximo)",
                                  f"idade maxima, ±{AGE_MAX_STEP}d", +AGE_MAX_STEP, -AGE_MAX_STEP,
                                  p_max_relax, p_max_restr))
    return linhas


def avaliar_sensibilidade_larga(con: sqlite3.Connection, base: ParamsV1) -> list[dict[str, Any]]:
    """PEDIDO 2026-10-30 (`--passo largo`): mesmos pools/base da tabela padrao, varios passos
    ABSOLUTOS por parametro (nao so um relaxado/restrito) -- so os 4 parametros pedidos."""
    pools = _coletar_pools(con, base.timeframes[0])
    base_por_pool = {pool: _rodar(bars, base, l_bc, grad_ts, created_ts)
                     for pool, bars, l_bc, grad_ts, created_ts in pools}
    linhas = []
    for v in VARIACOES_LARGAS:
        passos = []
        for valor in v.valores:
            params_var = v.construir(base, valor)
            if params_var is None:
                passos.append({"valor": valor, "delta_sinais": None, "near_miss": None})
                continue
            delta_entradas, near_miss = 0, 0
            for pool, bars, l_bc, grad_ts, created_ts in pools:
                n_base, sem_entrada_base, _ = base_por_pool[pool]
                n_var, _, com_entrada_var = _rodar(bars, params_var, l_bc, grad_ts, created_ts)
                delta_entradas += n_var - n_base
                if sem_entrada_base:
                    near_miss += len(sem_entrada_base & com_entrada_var)
            passos.append({"valor": valor, "delta_sinais": delta_entradas, "near_miss": near_miss})
        linhas.append({"parametro": v.nome, "descricao": v.descricao, "passos": passos})
    return linhas


def formatar_markdown_largo(versao: str, linhas: list[dict[str, Any]]) -> str:
    out = [f"## Passos largos (--passo largo) — POS-RUNNER-{versao.upper()}", "",
          "Mesma direcao \"relaxada\" ja documentada acima, so mais distante da base; valor ABSOLUTO "
          "(nao delta). Combinacao invalida = pulada (nunca forcada).", "",
          "| parametro | valor base -> novo | Δ sinais | near-miss |", "|---|---|---|---|"]
    for linha in linhas:
        for passo in linha["passos"]:
            if passo["delta_sinais"] is None:
                out.append(f"| {linha['parametro']} ({linha['descricao']}) | -> {passo['valor']} | "
                          "pulado (combinacao invalida) | – |")
            else:
                out.append(f"| {linha['parametro']} ({linha['descricao']}) | -> {passo['valor']} | "
                          f"{passo['delta_sinais']:+d} | {passo['near_miss']} |")
    return "\n".join(out)


def formatar_markdown(versao: str, n_pools: int, linhas: list[dict[str, Any]], sem_fase: int,
                      fase_ativa: int) -> str:
    out = [f"# Sensibilidade de parametros — POS-RUNNER-{versao.upper()}", "",
          f"Pools acompanhados com candles em cache: {n_pools} (sem_fase/dead: {sem_fase} | "
          f"fase ativa [runner/pullback, V1 ou V2]: {fase_ativa}).", "",
          "| parametro | passo | relaxado: Δ sinais | relaxado: near-miss | restrito: Δ sinais |",
          "|---|---|---|---|---|"]
    for linha in linhas:
        relax = linha["relaxado"]
        restr = linha["restrito"]
        relax_txt = f"{relax['delta_sinais']:+d}" if relax else "pulado (combinacao invalida)"
        near_miss_txt = str(relax["near_miss"]) if relax else "–"
        restr_txt = f"{restr['delta_sinais']:+d}" if restr else "pulado (combinacao invalida)"
        out.append(f"| {linha['parametro']} | {linha['descricao']} | {relax_txt} | {near_miss_txt} | {restr_txt} |")
    out.append("")
    out.append("Fora desta tabela (nunca mudam SE um sinal/ENTRADA aparece, so afetam saida/tag -- ver "
              "docs/pos-runner-v1/AUDITORIA_PARAMETROS.md): `tp1_frac`, `exhaustion_wick_mult`, "
              "`exhaustion_doji_frac`, `stop_below_wick_pct`, `risk_min`/`risk_max` (atributo), "
              "`peak_attr_mc` (atributo), `l_bc_suspeito_baixo_usd`/`l_bc_suspeito_alto_usd` (so tag).")
    out.append("")
    out.append("Near-miss de `drop_min`/`drop_max`/`runner_min_mc` e SUBESTIMADO (podem deslocar onde a "
              "propria onda/zona comeca, desalinhando o id de zona entre as 2 rodadas) -- ver docstring "
              "do modulo.")
    return "\n".join(out)


def executar(db_path: Path, versao: str, passo: str = "padrao") -> str:
    con = _conectar_ro(db_path)
    try:
        base = load_params_v1() if versao == "v1" else load_params_v2()
        pools = _coletar_pools(con, base.timeframes[0])
        linhas = avaliar_sensibilidade(con, base)
        sem_fase, fase_ativa = _fases_cache(con, [p[0] for p in pools])
        texto = formatar_markdown(versao, len(pools), linhas, sem_fase, fase_ativa)
        if passo == "largo":
            linhas_largas = avaliar_sensibilidade_larga(con, base)
            texto = texto + "\n\n" + formatar_markdown_largo(versao, linhas_largas)
        return texto
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sensibilidade offline dos parametros V1/V2 (PAPER / so leitura).")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--versao", choices=("v1", "v2"), default="v1")
    parser.add_argument("--passo", choices=("padrao", "largo"), default="padrao",
                        help="padrao (default): so a tabela ja existente. largo: acrescenta passos "
                             "mais distantes p/ zone_min_candles/idade minima/drop_min/recover_mult.")
    args = parser.parse_args(argv)
    print(executar(args.db, args.versao, args.passo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
