"""PEDIDO 2026-10-30 (FASE 1c): auditoria + tag das ENTRADAs V1/V2 ja existentes cujo alerta saiu
atrasado em relacao ao fechamento do candle-gatilho -- mesmo limiar que `live.py: _entry_v1`/
`_entry_v2` ja usam pra decidir se alertam (`_late`, `max(300s, step/2)`), NUNCA um numero novo.

So leitura de `pr_bars`/rede: ZERO chamada nova. "Atraso" = `alert_ts` (quando o Telegram confirmou
o envio, ou `ts_alerta` se o envio falhou -- o momento em que o BOT decidiu alertar, o mais proximo
que existe do "agora" causal daquele ciclo) menos `ts_fechamento` (fechamento do candle-gatilho, ja
= `ev.decision_ts`). Sinal sem `alert_ts` NEM `ts_alerta` (Telegram nunca tentou) fica "sem_dado",
nunca um atraso inventado.

Escreve (nunca apaga, nunca muda numero de trade/R/preco):
- tag `entrada_atrasada` em `tags` (append, idempotente) quando atraso > limiar;
- `atraso_candles` (NULL ainda, sinais anteriores a esta entrega -- ver storage.py) estimado a partir
  de `alert_ts`/`ts_alerta`, so quando ainda NULL (nunca sobrescreve um valor ja gravado ao vivo por
  `_entry_v1`/`_entry_v2`, que e mais preciso: usa o `now` real do ciclo, nao o `alert_ts` depois).

Faz backup (`Storage.backup_to`) ANTES de qualquer escrita, mesmo padrao de
`scripts/backfill_evidencia.py`. Idempotente -- rodar de novo so reprocessa o que ainda falta.

Uso (na VM):
    python -m signals_mvp.scripts.auditar_atraso_entradas --db dados/estado.sqlite
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..pos_runner.candles import tf_seconds
from ..storage import Storage

TAG = "entrada_atrasada"


def _abrir_storage_no_arquivo(db_path: Path) -> Storage:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    return Storage(paths)


def _limiar(tf: str) -> float:
    """MESMO limiar de `live.py: _entry_v1`/`_entry_v2` (`_late`, `max(300.0, step/2)`)."""
    return max(300.0, tf_seconds(tf) / 2.0)


def _atraso_s(s: Any) -> Optional[float]:
    momento = s["alert_ts"] if s["alert_ts"] is not None else s["ts_alerta"]
    if momento is None or s["ts_fechamento"] is None:
        return None
    return float(momento) - float(s["ts_fechamento"])


def _auditar_versao(storage: Storage, versao: str, sinais: list, update_fn) -> tuple[int, int, int]:
    atrasados, estimados, sem_dado = 0, 0, 0
    for s in sinais:
        if s["evento"] != "ENTRADA":
            continue
        atraso = _atraso_s(s)
        if atraso is None:
            sem_dado += 1
            continue
        campos: dict[str, Any] = {}
        if s["atraso_candles"] is None:
            campos["atraso_candles"] = atraso / tf_seconds(s["tf"])
            estimados += 1
        tags = json.loads(s["tags"] or "[]")
        if atraso > _limiar(s["tf"]):
            atrasados += 1
            if TAG not in tags:
                tags.append(TAG)
                campos["tags"] = json.dumps(tags)
        if campos:
            update_fn(s["id"], **campos)
    return atrasados, estimados, sem_dado


def executar(db_path: Path, backup_dir: Optional[Path] = None) -> list[str]:
    storage = _abrir_storage_no_arquivo(db_path)
    try:
        dest = (backup_dir or (db_path.parent / "backups")) / f"pre_auditar_atraso_entradas_{int(time.time())}.sqlite"
        storage.backup_to(dest)
        linhas = [f"backup: {dest}"]
        atraso_v1, estim_v1, semd_v1 = _auditar_versao(storage, "v1", storage.pr1_signals(), storage.pr1_update_signal)
        atraso_v2, estim_v2, semd_v2 = _auditar_versao(storage, "v2", storage.pr2_signals(), storage.pr2_update_signal)
        linhas.append(f"V1: {atraso_v1} ENTRADA(s) marcada(s) '{TAG}' | atraso_candles estimado em "
                     f"{estim_v1} linha(s) | sem_dado (nunca alertado): {semd_v1}")
        linhas.append(f"V2: {atraso_v2} ENTRADA(s) marcada(s) '{TAG}' | atraso_candles estimado em "
                     f"{estim_v2} linha(s) | sem_dado (nunca alertado): {semd_v2}")
        linhas.append(f"total ENTRADA(s) atrasada(s) hoje: {atraso_v1 + atraso_v2}")
        return linhas
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audita/tagueia ENTRADAs V1/V2 atrasadas (so leitura de rede).")
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (producao ou copia)")
    args = parser.parse_args(argv)
    for linha in executar(Path(args.db)):
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
