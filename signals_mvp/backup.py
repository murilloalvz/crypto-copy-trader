"""Backup diario do estado.sqlite (PEDIDO ADICIONAL FASE 6, item 1).

Usa a API de backup nativa do SQLite (`Storage.backup_to`, `sqlite3.Connection.backup`) -- consistente
com o banco em uso mesmo em modo WAL com escrita concorrente, nunca uma copia de arquivo "crua" que
poderia pegar uma escrita no meio. Guardado em `backups/` (fora de `dados/`, no .gitignore -- nunca vai
pro git). Retencao configuravel (padrao 7 dias): backups mais antigos sao apagados a cada rodada, DEPOIS
de confirmar que o novo terminou sem erro (nunca apaga antes).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("signals_mvp.backup")

RETENCAO_DIAS_PADRAO = 7
INTERVALO_S_PADRAO = 86400.0   # 1x por dia (a cadencia exata depende de quando o bot roda os ciclos)


def run_backup(storage: Any, backups_dir: Path, now: float, retencao_dias: float = RETENCAO_DIAS_PADRAO) -> Path:
    """1 backup. Nome com timestamp UTC (nunca sobrescreve um backup anterior)."""
    dest = backups_dir / f"estado-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}.sqlite"
    storage.backup_to(dest)
    _apagar_antigos(backups_dir, now, retencao_dias)
    return dest


def _apagar_antigos(backups_dir: Path, now: float, retencao_dias: float) -> None:
    limite = now - retencao_dias * 86400.0
    for path in sorted(backups_dir.glob("estado-*.sqlite")):
        try:
            if path.stat().st_mtime < limite:
                path.unlink()
        except OSError:
            log.warning("nao consegui apagar o backup antigo %s", path)


def maybe_run_backup(storage: Any, backups_dir: Path, now: float, retencao_dias: float = RETENCAO_DIAS_PADRAO,
                     intervalo_s: float = INTERVALO_S_PADRAO) -> Optional[Path]:
    """So roda 1x por `intervalo_s` (meta `ultimo_backup_ts`, mesmo padrao do `resumo_diario`/`ultimo_resumo`)
    -- quem chama (o loop principal do worker) pode chamar isto todo ciclo sem custo extra."""
    last = float(storage.get_meta("ultimo_backup_ts", "0") or 0)
    if now - last < intervalo_s:
        return None
    dest = run_backup(storage, backups_dir, now, retencao_dias)
    storage.set_meta("ultimo_backup_ts", str(now))
    return dest
