"""PEDIDO 2026-10-27 (item 2, pos-auditoria McRib/yagi): marca retroativamente, de forma IDEMPOTENTE,
os trades que o OPERADOR confirmou contaminados (via `scripts/auditar_trades.py` + leitura humana) com
a tag `contaminado_candle` em `tags` -- nunca apaga/reescreve nenhum outro campo (`entry_price`,
`result_net`, `status`, etc. continuam exatamente como estavam). Faz backup (`Storage.backup_to`,
API nativa do SQLite) ANTES de qualquer escrita. A lista de trades e EXPLICITA (`--trade versao:id`),
nunca re-derivada por heuristica aqui -- so o operador que leu a auditoria decide o que marcar.

A regra de exclusao pre-declarada (`analise/condicional.py: _contaminado_candle`) exclui de H1-H8
qualquer sinal com esta tag (ver `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`).

Uso (na VM):
    python -m signals_mvp.scripts.marcar_contaminados --db dados/estado.sqlite \\
        --trade v1:6 --trade v2:2 --trade v2:1
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path
from typing import Optional, Sequence

from ..config import make_paths
from ..storage import Storage

TAG = "contaminado_candle"


def _abrir_storage_no_arquivo(db_path: Path) -> Storage:
    """`make_paths()` so sabe montar `<base>/dados/estado.sqlite` -- aqui o operador aponta o arquivo
    exato (produção ou uma cópia com outro nome), então sobrescrevemos so `db`/`dados` do template."""
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    return Storage(paths)


def _marcar_um(storage: Storage, versao: str, signal_id: int) -> str:
    sinal_fn = storage.pr1_signal if versao == "v1" else storage.pr2_signal
    update_fn = storage.pr1_update_signal if versao == "v1" else storage.pr2_update_signal
    sinal = sinal_fn(signal_id)
    if sinal is None:
        return f"{versao}:{signal_id} -- NAO ENCONTRADO (nada feito)"
    tags = json.loads(sinal["tags"] or "[]")
    if TAG in tags:
        return f"{versao}:{signal_id} {sinal['symbol']} -- ja estava marcado (idempotente, nada mudou)"
    tags.append(TAG)
    update_fn(signal_id, tags=json.dumps(tags))
    return f"{versao}:{signal_id} {sinal['symbol']} -- marcado `{TAG}`"


def marcar(db_path: Path, trades: Sequence[tuple[str, int]], backup_dir: Optional[Path] = None) -> list[str]:
    storage = _abrir_storage_no_arquivo(db_path)
    try:
        dest = (backup_dir or (db_path.parent / "backups")) / f"pre_marcar_contaminados_{int(time.time())}.sqlite"
        storage.backup_to(dest)
        linhas = [f"backup: {dest}"]
        for versao, signal_id in trades:
            linhas.append(_marcar_um(storage, versao, signal_id))
        return linhas
    finally:
        storage.close()


def _parse_trade(valor: str) -> tuple[str, int]:
    versao, _, id_txt = valor.partition(":")
    if versao not in ("v1", "v2") or not id_txt.isdigit():
        raise argparse.ArgumentTypeError(f"formato esperado v1:<id> ou v2:<id>, recebido {valor!r}")
    return versao, int(id_txt)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Marca retroativamente (idempotente, com backup antes) trades confirmados "
                    "contaminados pela auditoria de candles."
    )
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (produção ou cópia)")
    parser.add_argument("--trade", action="append", type=_parse_trade, required=True, dest="trades",
                        help="versao:id (ex. v1:6); repita a flag para mais de 1 trade")
    args = parser.parse_args(argv)
    for linha in marcar(Path(args.db), args.trades):
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
