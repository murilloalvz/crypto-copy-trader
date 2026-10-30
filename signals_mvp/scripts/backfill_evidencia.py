"""PEDIDO 2026-10-29, item 3: preenche retroativamente `pr_trajetoria`/`pr_baseline` (FASES 1-2 de
`pos_runner/evidencia.py`) das ENTRADAs V1/V2 anteriores a essa instrumentacao, usando SO candles JA
em `pr_bars` -- ZERO chamada nova de rede (GT/DexPaprika/RPC). Reusa as MESMAS funcoes puras que o bot
ao vivo usa (`evidencia.calcular_trajetoria`/`candidatos_elegiveis`/`sortear_controles`/
`simular_controle`, `simulate_v1.simulate_v1`) -- nunca duplica a regra, nunca toca `pr1_signals`/
`pr2_signals` nem nenhuma saida oficial de V1/V2 (alerta/banca/CSV), e so roda pra ENTRADA cuja
`versao_config_v1`/`versao_config_v2` bate com o hash ATUAL (`ParamsV1().version`/
`load_params_v2().version`) -- MESMA regra de `live.py: _update_evidencia_v1/v2` (nunca mistura
versao congelada).

Sem cotacao SOL/USD em cache de processo (este script roda FORA do bot ao vivo, que so teria isso
depois de `LiveQuotes.series()` rodar nalgum ciclo): `sol_usd_at` sempre devolve `None` aqui --
`CostModel.slippage_pct` ja trata isso com o MESMO fallback conservador de 1% que o bot ao vivo usa
sempre que a cotacao ainda nao foi buscada (nunca um valor inventado, so o fallback que ja existia).

Quando o candle do pool/tf nao esta mais em `pr_bars` (nenhum jeito de calcular sem inventar), marca
`pre_instrumentacao=1` em vez de deixar a linha simplesmente ausente -- distingue "nunca vai ter esse
dado" de "ainda nao teve tempo" (ver `saude.py`/consistencia).

Faz backup (`Storage.backup_to`) ANTES de qualquer escrita, mesmo padrao de
`scripts/marcar_contaminados.py`. Idempotente -- rodar de novo so reprocessa o que ainda falta.

Uso (na VM):
    python -m signals_mvp.scripts.backfill_evidencia --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..storage import Storage
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.costs import CostModel
from ..pos_runner.evidencia import (
    N_CONTROLES_MINIMO,
    N_CONTROLES_PADRAO,
    calcular_trajetoria,
    candidatos_elegiveis,
    simular_controle,
    sortear_controles,
)
from ..pos_runner.live import DEX_OF_LAUNCHPAD, event_v1_from_json
from ..pos_runner.params_v1 import ParamsV1
from ..pos_runner.params_v2 import load_params_v2
from ..pos_runner.simulate_v1 import simulate_v1

_SOL_USD_SEMPRE_NONE = lambda _ts: None  # noqa: E731 - ver docstring do modulo


def _abrir_storage_no_arquivo(db_path: Path) -> Storage:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    return Storage(paths)


def _bars_de(storage: Storage, pool: str, tf: str) -> list[Bar]:
    return [Bar(int(t[0]), t[1], t[2], t[3], t[4], t[5], bool(t[6])) for t in storage.pr_bars(pool, tf)]


def _created(row: Any) -> Optional[float]:
    try:
        info = json.loads(row["info"] or "{}")
    except (TypeError, ValueError):
        return None
    value = info.get("criado_ts")
    return None if value is None else float(value)


def _candle_confiavel_cb(storage: Storage, bars: list[Bar], pool: str, peak: Optional[float]):
    from ..pos_runner import qualidade_candle
    divergentes = {int(r["candle_ts"]) for r in storage.pr1_dexpaprika_divergencias() if r["pool"] == pool}

    def cb(j: int) -> Optional[str]:
        bar = bars[j]
        anterior = bars[j - 1].close if j > 0 else None
        seguinte = bars[j + 1].open if j + 1 < len(bars) else None
        return qualidade_candle.motivo_suspeito(bar, anterior, peak, seguinte, bar.ts in divergentes)
    return cb


def _marcar_pre_instrumentacao(storage: Storage, versao: str, signal: Any, now: float, ja_existe_traj: bool,
                               ja_existe_base: bool) -> None:
    if not ja_existe_traj:
        storage.pr_trajetoria_upsert(
            versao, signal["id"], now, chain=signal["chain"], pool=signal["pool"], tf=signal["tf"],
            mint=signal["mint"], symbol=signal["symbol"], pre_instrumentacao=1,
        )
    if not ja_existe_base:
        storage.pr_baseline_upsert(
            versao, signal["id"], now, chain=signal["chain"], pool=signal["pool"], tf=signal["tf"],
            mint=signal["mint"], symbol=signal["symbol"], pre_instrumentacao=1,
        )


def _atualizar_trajetoria(storage: Storage, versao: str, signal: Any, pool_row: Any, bars: list[Bar], params: Any,
                          costs: CostModel, now: float) -> bool:
    """Mesma regra de `live.py: PosRunnerLive._atualizar_trajetoria` -- devolve True se gravou algo."""
    ev = event_v1_from_json(signal["event_json"])
    if ev.idx + 1 >= len(bars):
        return False
    dex = DEX_OF_LAUNCHPAD.get(signal["launchpad"], "desconhecido")
    confiavel = _candle_confiavel_cb(storage, bars, signal["pool"], ev.data.get("TOPO"))
    res = simulate_v1(bars, ev, params, costs, dex, pool_row["l_bc"], _SOL_USD_SEMPRE_NONE, candle_confiavel=confiavel)
    if res.entry_price is None or not res.risk_frac or res.risk_frac <= 0:
        return False
    calc = calcular_trajetoria(bars, ev.idx + 1, res.entry_ts, res.entry_price, res.risk_frac,
                               tf_seconds(signal["tf"]), res.legs, now)
    r = calc.retornos_r
    storage.pr_trajetoria_upsert(
        versao, signal["id"], now,
        chain=signal["chain"], pool=signal["pool"], tf=signal["tf"], mint=signal["mint"], symbol=signal["symbol"],
        t_entrada=res.entry_ts, preco_entrada=res.entry_price, risco_pct=100.0 * res.risk_frac,
        r_unidade=res.entry_price * res.risk_frac, fonte_candle=signal["fonte_candle"] or "gt",
        mfe_r=calc.mfe_r, mfe_h=calc.mfe_h, mae_r=calc.mae_r, mae_h=calc.mae_h,
        ret_r_1h=r.get(1), ret_r_2h=r.get(2), ret_r_4h=r.get(4), ret_r_8h=r.get(8),
        ret_r_24h=r.get(24), ret_r_48h=r.get(48), ret_r_72h=r.get(72),
        tocou_tp1=1 if calc.tocou_tp1 else 0, tocou_stop_antes_de_tp1=1 if calc.tocou_stop_antes_de_tp1 else 0,
        fechado=1 if calc.fechado else 0, pre_instrumentacao=0,
    )
    return True


def _atualizar_baseline(storage: Storage, versao: str, signal: Any, pool_row: Any, bars: list[Bar], params: Any,
                        costs: CostModel, now: float) -> bool:
    """Mesma regra de `live.py: PosRunnerLive._atualizar_baseline` -- devolve True se gravou algo."""
    baseline = storage.pr_baseline_get(versao, signal["id"])
    ev = event_v1_from_json(signal["event_json"])
    if baseline is None:
        created_ts = _created(pool_row)
        candidatos = candidatos_elegiveis(bars, created_ts, params.age_window_days, tf_seconds(signal["tf"]), ev.idx)
        if len(candidatos) < N_CONTROLES_MINIMO:
            return False
        escolhidos = sortear_controles(candidatos, signal["id"], versao, n=N_CONTROLES_PADRAO)
        controles = [{"idx": i, "ts": bars[i].ts, "status": "pendente", "r_controle": None} for i in escolhidos]
        storage.pr_baseline_upsert(
            versao, signal["id"], now, chain=signal["chain"], pool=signal["pool"], tf=signal["tf"],
            mint=signal["mint"], symbol=signal["symbol"], n_controles=len(controles),
            controles_json=json.dumps(controles), pre_instrumentacao=0,
        )
        baseline = storage.pr_baseline_get(versao, signal["id"])
    entry_price_sinal = signal["entry_price"]
    if not entry_price_sinal or signal["stop"] is None or signal["topo"] is None or signal["s_suporte"] is None:
        return False
    risco_pct_sinal = 100.0 * (1.0 - signal["stop"] / entry_price_sinal)
    topo_mult = signal["topo"] / entry_price_sinal
    s_mult = signal["s_suporte"] / entry_price_sinal
    dex = DEX_OF_LAUNCHPAD.get(signal["launchpad"], "desconhecido")
    controles = json.loads(baseline["controles_json"])
    mudou = False
    for c in controles:
        if c["status"] != "pendente":
            continue
        res = simular_controle(bars, c["idx"], risco_pct_sinal, topo_mult, s_mult, params, costs, dex,
                               pool_row["l_bc"], _SOL_USD_SEMPRE_NONE)
        if res is None or res.status == "em_aberto":
            continue
        c["status"] = res.status
        c["r_controle"] = res.r_mult if res.status == "fechado" else None
        mudou = True
    r_controle_medio: Optional[float] = None
    r_sinal: Optional[float] = None
    dif_pareada: Optional[float] = None
    if all(c["status"] != "pendente" for c in controles):
        valores = [c["r_controle"] for c in controles if c["r_controle"] is not None]
        if valores:
            r_controle_medio = sum(valores) / len(valores)
        if signal["status"] == "fechado" and signal["result_net"] is not None and risco_pct_sinal:
            r_sinal = 100.0 * signal["result_net"] / risco_pct_sinal
        if r_controle_medio is not None and r_sinal is not None:
            dif_pareada = r_sinal - r_controle_medio
    if mudou or dif_pareada is not None:
        storage.pr_baseline_upsert(versao, signal["id"], now, controles_json=json.dumps(controles),
                                   r_controle_medio=r_controle_medio, r_sinal=r_sinal, dif_pareada=dif_pareada)
        return True
    return False


def executar(db_path: Path, backup_dir: Optional[Path] = None) -> list[str]:
    storage = _abrir_storage_no_arquivo(db_path)
    try:
        dest = (backup_dir or (db_path.parent / "backups")) / f"pre_backfill_evidencia_{int(time.time())}.sqlite"
        storage.backup_to(dest)
        linhas = [f"backup: {dest}"]
        now = time.time()
        params_v1, params_v2 = ParamsV1(), load_params_v2()
        preenchidos_traj, preenchidos_base, marcados_pre, ainda_sem = 0, 0, 0, []
        for versao, sinais, params, versao_atual, campo_versao in (
            ("v1", storage.pr1_signals(), params_v1, params_v1.version, "versao_config_v1"),
            ("v2", storage.pr2_signals(), params_v2, params_v2.version, "versao_config_v2"),
        ):
            for s in sinais:
                if s["evento"] != "ENTRADA" or s["status"] == "cancelado" or s[campo_versao] != versao_atual:
                    continue
                traj = storage.pr_trajetoria_get(versao, s["id"])
                base = storage.pr_baseline_get(versao, s["id"])
                precisa_traj = traj is None or (not traj["fechado"] and not traj["pre_instrumentacao"])
                precisa_base = base is None or (base["dif_pareada"] is None and not base["pre_instrumentacao"])
                if not precisa_traj and not precisa_base:
                    continue
                bars = _bars_de(storage, s["pool"], s["tf"])
                if not bars:
                    _marcar_pre_instrumentacao(storage, versao, s, now, traj is not None, base is not None)
                    marcados_pre += 1
                    continue
                pool_row = storage.pr_pool(s["pool"])
                fez_traj = (_atualizar_trajetoria(storage, versao, s, pool_row, bars, params, CostModel(), now)
                           if precisa_traj else False)
                fez_base = (_atualizar_baseline(storage, versao, s, pool_row, bars, params, CostModel(), now)
                           if precisa_base else False)
                preenchidos_traj += int(fez_traj)
                preenchidos_base += int(fez_base)
                traj_depois = storage.pr_trajetoria_get(versao, s["id"])
                base_depois = storage.pr_baseline_get(versao, s["id"])
                if traj_depois is None or base_depois is None or (
                        base_depois["dif_pareada"] is None and not base_depois["pre_instrumentacao"]
                        and base_depois["n_controles"] == 0):
                    ainda_sem.append(f"{versao}:{s['id']} {s['symbol']} (pool {s['pool'][:8]}...)")
        linhas.append(f"trajetoria preenchida/atualizada: {preenchidos_traj} | baseline preenchida/atualizada: "
                      f"{preenchidos_base} | marcados pre_instrumentacao (sem candle em cache): {marcados_pre}")
        if ainda_sem:
            linhas.append(f"ainda sem trajetoria/baseline completa ({len(ainda_sem)}):")
            linhas.extend(f"  {item}" for item in ainda_sem[:20])
        else:
            linhas.append("nenhuma ENTRADA elegivel ficou sem trajetoria/baseline (preenchida ou pre_instrumentacao)")
        return linhas
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preenche retroativamente trajetoria/baseline (zero chamada nova).")
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (produção ou cópia)")
    args = parser.parse_args(argv)
    for linha in executar(Path(args.db)):
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
