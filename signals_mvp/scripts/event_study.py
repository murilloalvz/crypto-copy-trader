"""PEDIDO 2026-11-03 (continuacao -- pendente 4). SOMENTE LEITURA, zero chamada de rede.

Event study EXPLORATORIO: retorno (% do preco, nunca em R) a +1h/+6h/+24h/+72h apos a entrada de cada
sinal LIMPO (V1/V2/V3, mesma exclusao de `analise.condicional`: `contaminado_candle` fora; risco<3%
nunca entra no efeito pareado -- so reportado no retorno bruto do sinal, que nao depende do risco)
CONTRA os MESMOS 10 controles pareados que `evidencia.py` ja usa para H1 (`candidatos_elegiveis`/
`sortear_controles`/`seed_de_entrada`, MESMA janela de idade da versao, MESMA seed por sinal -- nunca
uma amostra nova/diferente da que H1 ja usa). Nunca grava nada, nunca soma a H1/H2-H7 -- diagnostico
puro, N pequeno.

Efeito pareado por horizonte = retorno do sinal - media dos controles elegiveis daquele sinal (MESMA
logica de `dif_pareada` do H1, nunca duplicada com outra formula). Para medir incerteza SEM inflar o
N (varios sinais do MESMO token nao sao independentes), o bootstrap e em BLOCOS POR TOKEN (mesmo
metodo de `analise.condicional.bootstrap_media_e_limite_inferior` -- reamostra tokens com reposicao,
nunca sinais individuais): devolve a media observada e o limite inferior unilateral (90%, MESMA
confianca do H1). Reporta tambem N de tokens distintos -- nunca escondido.

Uso (na VM):
    python -m signals_mvp.scripts.event_study --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..analise.condicional import CONFIANCA_H1, N_BOOTSTRAP_PADRAO, SEED_PADRAO, _contaminado_candle, _risco_irrealista
from ..config import make_paths
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.evidencia import candidatos_elegiveis, seed_de_entrada, sortear_controles
from ..pos_runner.params_v1 import load_params_v1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.params_v3 import load_params_v3
from ..storage import Storage

AVISO = "exploratorio; efeito pareado contra os MESMOS controles do H1; nunca soma a H1/H2-H7"
HORIZONTES_H: tuple[int, ...] = (1, 6, 24, 72)


def _signals_de(storage: Storage, versao: str) -> list[Any]:
    return {"v1": storage.pr1_signals, "v2": storage.pr2_signals, "v3": storage.pr3_signals}[versao]()


def _params_de(versao: str) -> Any:
    return {"v1": load_params_v1, "v2": load_params_v2, "v3": load_params_v3}[versao]()


def _created_ts(info_json: Optional[str]) -> Optional[float]:
    try:
        info = json.loads(info_json or "{}")
    except ValueError:
        info = {}
    v = info.get("criado_ts") if isinstance(info, dict) else None
    return None if v is None else float(v)


def _bar_idx_por_ts(bars: list[Bar], ts: Optional[float]) -> Optional[int]:
    if ts is None:
        return None
    for idx, bar in enumerate(bars):
        if bar.ts == ts:
            return idx
    return None


def _retorno_pct(bars: list[Bar], entrada_idx: int, entry_price: Optional[float], step: int, h: int) -> Optional[float]:
    """MESMA aritmetica de indice de `evidencia.calcular_trajetoria` (`offset_candles =
    round(h*3600/step); idx = entrada_idx + offset_candles - 1`) -- so devolve % bruto em vez de R."""
    if not entry_price:
        return None
    offset = round(h * 3600.0 / step)
    idx = entrada_idx + offset - 1
    if not (0 <= idx < len(bars)):
        return None
    return 100.0 * (bars[idx].close / entry_price - 1.0)


def medir_sinal(storage: Storage, versao: str, s: Any, bars: list[Bar], params: Any) -> Optional[dict[str, Any]]:
    traj = storage.pr_trajetoria_get(versao, s["id"])
    if traj is None or traj["t_entrada"] is None or s["entry_price"] is None:
        return None
    entry_ts, entry_price = traj["t_entrada"], s["entry_price"]
    j0 = _bar_idx_por_ts(bars, entry_ts)
    if j0 is None:
        return None
    step = tf_seconds(s["tf"] or "1h")
    retorno_sinal = {h: _retorno_pct(bars, j0, entry_price, step, h) for h in HORIZONTES_H}

    pool_row = storage.pr_pool(s["pool"])
    created_ts = _created_ts(pool_row["info"]) if pool_row is not None else None
    candidatos = candidatos_elegiveis(bars, created_ts, params.age_window_days, step, excluir_idx=max(j0 - 1, 0))
    controles_idx = sortear_controles(candidatos, s["id"], versao)
    retornos_controles: dict[int, list[float]] = {h: [] for h in HORIZONTES_H}
    for idx in controles_idx:
        entrada_ctrl = idx + 1
        if entrada_ctrl >= len(bars):
            continue
        preco_ctrl = bars[entrada_ctrl].open
        for h in HORIZONTES_H:
            r = _retorno_pct(bars, entrada_ctrl, preco_ctrl, step, h)
            if r is not None:
                retornos_controles[h].append(r)
    return {
        "token": s["symbol"] or (s["mint"] or "")[:8], "versao": versao,
        "retorno_sinal": retorno_sinal,
        "retorno_controles_medio": {h: (statistics.fmean(vs) if vs else None) for h, vs in retornos_controles.items()},
        "n_controles": {h: len(vs) for h, vs in retornos_controles.items()},
    }


def medir_versao(storage: Storage, versao: str) -> list[dict[str, Any]]:
    params = _params_de(versao)
    out: list[dict[str, Any]] = []
    bars_cache: dict[str, list[Bar]] = {}
    for s in _signals_de(storage, versao):
        if s["evento"] != "ENTRADA" or s["status"] != "fechado":
            continue
        if _contaminado_candle(s) or _risco_irrealista(s):
            continue
        tf = s["tf"] or "1h"
        bars = bars_cache.setdefault(f"{s['pool']}|{tf}", [Bar(*row) for row in storage.pr_bars(s["pool"], tf)])
        r = medir_sinal(storage, versao, s, bars, params)
        if r is not None:
            out.append(r)
    return out


def _bootstrap_media_por_token(valores_por_token: dict[str, list[float]], n_bootstrap: int = N_BOOTSTRAP_PADRAO,
                               seed: int = SEED_PADRAO, confianca: float = CONFIANCA_H1) -> tuple[float, float, int]:
    """MESMO metodo de `analise.condicional.bootstrap_media_e_limite_inferior` (reamostra TOKENS com
    reposicao, nunca sinais individuais -- preserva a correlacao entre sinais do mesmo token), so
    generico sobre `dict[token, valores]` em vez de `Sequence[SinalResolvido]` (nunca forca o efeito
    pareado deste event study dentro do dataclass confirmatorio `SinalResolvido`)."""
    chaves = sorted(valores_por_token)
    n = len(chaves)
    todos = [v for vs in valores_por_token.values() for v in vs]
    if n == 0 or not todos:
        return 0.0, 0.0, 0
    media_observada = float(np.mean(todos))
    rng = np.random.default_rng(seed)
    medias = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        escolhidos = rng.integers(0, n, size=n)
        valores = [v for idx in escolhidos for v in valores_por_token[chaves[idx]]]
        medias[i] = float(np.mean(valores)) if valores else 0.0
    limite_inferior = float(np.percentile(medias, 100 * (1 - confianca)))
    return media_observada, limite_inferior, n


def efeito_pareado_por_horizonte(resultados: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Para cada horizonte: efeito pareado (retorno do sinal - media dos controles DAQUELE sinal) em
    blocos por TOKEN, media observada + limite inferior (bootstrap), N de sinais e N de tokens
    distintos com pelo menos 1 efeito valido."""
    out: dict[int, dict[str, Any]] = {}
    for h in HORIZONTES_H:
        por_token: dict[str, list[float]] = {}
        for r in resultados:
            rs, rc = r["retorno_sinal"][h], r["retorno_controles_medio"][h]
            if rs is None or rc is None:
                continue
            por_token.setdefault(r["token"], []).append(rs - rc)
        media, limite_inferior, n_tokens = _bootstrap_media_por_token(por_token)
        n_sinais = sum(len(v) for v in por_token.values())
        out[h] = {"media": media, "limite_inferior_90": limite_inferior, "n_sinais": n_sinais, "n_tokens": n_tokens}
    return out


def formatar(resultados: list[dict[str, Any]]) -> str:
    out = [f"# event_study -- retorno vs controles pareados ({AVISO})", "",
          f"Horizontes: {', '.join(f'+{h}h' for h in HORIZONTES_H)}. Controles: os MESMOS 10 por sinal "
          f"que `evidencia.py`/H1 ja usam (mesma seed, mesma janela de idade).", ""]
    for versao in ("v1", "v2", "v3"):
        res_v = [r for r in resultados if r["versao"] == versao]
        tokens = {r["token"] for r in res_v}
        out.append(f"## {versao.upper()} (n={len(res_v)} sinal(is), {len(tokens)} token(s) distinto(s))")
        efeitos = efeito_pareado_por_horizonte(res_v)
        for h in HORIZONTES_H:
            e = efeitos[h]
            out.append(f"  +{h}h: efeito pareado médio={e['media']:+.2f}pp | limite inferior (90%)="
                      f"{e['limite_inferior_90']:+.2f}pp | n={e['n_sinais']} sinais, {e['n_tokens']} token(s)")
        out.append("")
    tokens_total = {r["token"] for r in resultados}
    out.append(f"## Todas as versões (n={len(resultados)} sinal(is), {len(tokens_total)} token(s) distinto(s))")
    efeitos_total = efeito_pareado_por_horizonte(resultados)
    for h in HORIZONTES_H:
        e = efeitos_total[h]
        out.append(f"  +{h}h: efeito pareado médio={e['media']:+.2f}pp | limite inferior (90%)="
                  f"{e['limite_inferior_90']:+.2f}pp | n={e['n_sinais']} sinais, {e['n_tokens']} token(s)")
    out.append("")
    out.append("Por sinal (retorno do sinal / média dos controles, pp):")
    out.append("")
    out.append("| token | versão | " + " | ".join(f"+{h}h (sinal/controles)" for h in HORIZONTES_H) + " |")
    out.append("|---|---|" + "---|" * len(HORIZONTES_H))
    for r in resultados:
        celulas = []
        for h in HORIZONTES_H:
            rs, rc = r["retorno_sinal"][h], r["retorno_controles_medio"][h]
            rs_txt = f"{rs:+.1f}%" if rs is not None else "s/d"
            rc_txt = f"{rc:+.1f}% (n={r['n_controles'][h]})" if rc is not None else "s/d"
            celulas.append(f"{rs_txt} / {rc_txt}")
        out.append(f"| {r['token']} | {r['versao']} | " + " | ".join(celulas) + " |")
    out.append("")
    out.append(f"({AVISO})")
    return "\n".join(out)


def executar(db_path: Path) -> str:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    storage = Storage(paths)
    try:
        resultados = [r for v in ("v1", "v2", "v3") for r in medir_versao(storage, v)]
        return formatar(resultados)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="event_study: retorno vs 10 controles pareados, bootstrap por token (leitura).")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args(argv)
    print(executar(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
