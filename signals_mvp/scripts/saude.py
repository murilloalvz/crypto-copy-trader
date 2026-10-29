"""PEDIDO 2026-10-29, item 4: auditoria geral do bot, SOMENTE LEITURA -- nunca escreve no banco, nunca
chama rede, nunca manda Telegram. Imprime um relatorio compacto (texto puro, sem markdown) pra colar
direto numa conversa. Cobre: erros/avisos do log (48h), uptime vs versao/hashes, fila/fases/pools sem
atualizacao, coleta de carteiras "pro", trajetoria/baseline, DexPaprika, 429/h, alertas, backups/disco/
RAM, healthchecks, trades contaminados/risco_irrealista e consistencia geral (ENTRADA sem trajetoria/
baseline, fechado sem R, R com risco <3%, timestamps no futuro/duplicados).

Varias metricas (creditos DexPaprika restantes no plano, contadores do heartbeat em memoria, ultimo
ping bem-sucedido do Healthchecks.io) so existem no PROCESSO ao vivo ou no painel de um servico externo
-- nunca sao persistidas no SQLite. Essas linhas aparecem como "s/d (so no processo ao vivo)" ou
equivalente -- nunca um numero inventado.

Uso (na VM, dentro do diretorio do bot):
    python -m signals_mvp.scripts.saude --db dados/estado.sqlite
    python -m signals_mvp.scripts.saude --db dados/estado.sqlite --logs logs --janela-h 48
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..config import make_paths
from ..storage import Storage

LOG_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})Z (?P<level>\w+)\s+(?P<logger>\S+): (?P<msg>.*)$")
TAGS_EXCLUSAO_R = ("contaminado_candle", "risco_irrealista")


def _abrir_storage_no_arquivo(db_path: Path) -> Storage:
    paths = dataclasses.replace(make_paths(), db=db_path, dados=db_path.parent)
    return Storage(paths)


def _fmt_h(segundos: float) -> str:
    return f"{segundos / 3600.0:.1f}h"


def _ts_de_linha(linha: str) -> Optional[float]:
    m = LOG_LINE_RE.match(linha)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m["ts"], "%Y-%m-%d %H:%M:%S")) - time.timezone
    except ValueError:
        return None


def _linhas_log(logs_dir: Path, janela_s: float, now: float) -> list[str]:
    """Junta `signals_mvp.log` + rotacionados (`.log.1`..`.log.5`) dentro da janela -- mais antigo
    que a janela para de ler esse arquivo (os rotacionados so ficam MAIS antigos)."""
    out: list[str] = []
    candidatos = [logs_dir / "signals_mvp.log"] + [logs_dir / f"signals_mvp.log.{i}" for i in range(1, 6)]
    corte = now - janela_s
    for path in candidatos:
        if not path.exists():
            continue
        try:
            texto = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for linha in texto.splitlines():
            ts = _ts_de_linha(linha)
            if ts is not None and ts < corte:
                continue
            out.append(linha)
    return out


def _secao_log(logs_dir: Path, janela_h: float, now: float) -> list[str]:
    linhas = _linhas_log(logs_dir, janela_h * 3600.0, now)
    if not linhas:
        return [f"LOG ({janela_h:.0f}h): arquivo nao encontrado em {logs_dir} -- nada pra ler"]
    erros = Counter()
    avisos = Counter()
    n_429 = 0
    for linha in linhas:
        m = LOG_LINE_RE.match(linha)
        if not m:
            continue
        nivel, msg = m["level"], m["msg"]
        if nivel in ("ERROR", "CRITICAL"):
            chave = msg.split(":")[0][:60]
            erros[chave] += 1
        elif nivel == "WARNING":
            chave = msg.split(":")[0][:60]
            avisos[chave] += 1
        if "429" in msg or "rate_limited" in msg.lower():
            n_429 += 1
    out = [f"LOG ({janela_h:.0f}h, {len(linhas)} linhas): {sum(erros.values())} erro(s), "
          f"{sum(avisos.values())} aviso(s), {n_429} mencao(oes) a 429"]
    for chave, n in erros.most_common(5):
        out.append(f"  ERRO x{n}: {chave}")
    for chave, n in avisos.most_common(3):
        out.append(f"  AVISO x{n}: {chave}")
    return out


def _secao_uptime_versoes(storage: Storage, now: float) -> list[str]:
    out = []
    sessoes = storage._all("SELECT inicio_ts, fim_ts FROM pr1_uptime ORDER BY inicio_ts DESC LIMIT 5")  # noqa: SLF001
    if sessoes:
        ultima = sessoes[0]
        aberta = ultima["fim_ts"] is None
        desde = _fmt_h(now - ultima["inicio_ts"])
        out.append(f"UPTIME: sessao atual {'ABERTA' if aberta else 'FECHADA (bug? deveria estar aberta)'} "
                  f"ha {desde} | {len(sessoes)} sessao(oes) recentes no banco")
    else:
        out.append("UPTIME: sem nenhuma sessao pr1_uptime no banco")
    try:
        from ..pos_runner.params_v1 import ParamsV1
        from ..pos_runner.params_v2 import load_params_v2
        out.append(f"HASHES: V1={ParamsV1().version} | V2={load_params_v2().version}")
    except Exception as exc:  # noqa: BLE001 - relatorio nunca quebra por isto
        out.append(f"HASHES: nao consegui calcular V1/V2 aqui ({type(exc).__name__})")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        out[-1] += f" | commit={commit or 's/d'}"
    except Exception:  # noqa: BLE001
        out[-1] += " | commit=s/d"
    return out


def _secao_fila(storage: Storage, now: float) -> list[str]:
    pools = storage.pr_pools("ativo")
    sem_tentativa = 0
    atrasados_2h = 0
    for row in pools:
        bars_1h = storage.pr_bars(row["pool"], "1h")
        if not bars_1h:
            sem_tentativa += 1
            continue
        if now - bars_1h[-1][0] > 2 * 3600.0:
            atrasados_2h += 1
    abertos_v1 = storage.pr1_signals(status="aberto")
    abertos_v2 = storage.pr2_signals(status="aberto")
    out = [f"FILA: {len(pools)} pool(s) ativo(s) | sem nenhum candle 1h ainda: {sem_tentativa} | "
          f"sem candle 1h novo ha >2h: {atrasados_2h}"]
    out.append(f"POSICOES ABERTAS: V1={len(abertos_v1)} V2={len(abertos_v2)}")
    for s in (abertos_v1 + abertos_v2)[:5]:
        bars = storage.pr_bars(s["pool"], s["tf"])
        ultimo = f"{(now - bars[-1][0]) / 60.0:.0f}min atras" if bars else "sem candle"
        out.append(f"  {s['symbol']} ({s['pool'][:8]}...): ultimo candle {ultimo}")
    return out


def _secao_carteiras(storage: Storage, now: float) -> list[str]:
    from ..pos_runner import carteiras_pro as cp
    sha = storage.get_meta(cp.META_KEY_SHA256)
    n_carteiras = storage.get_meta(cp.META_KEY_N_CARTEIRAS)
    n_pessoas = storage.get_meta(cp.META_KEY_N_PESSOAS)
    por_hora = Counter()
    erros = 0
    for row in storage.pr_carteiras_snapshot_all():
        if now - row["ts"] <= 86400.0:
            por_hora[int(row["ts"] // 3600)] += 1
    total_24h = sum(por_hora.values())
    out = [f"CARTEIRAS: lista carregada={'sim' if sha else 'NAO'} (sha256={sha[:12] + '...' if sha else 's/d'}) "
          f"| n_carteiras_pro={n_carteiras or 's/d'} n_pessoas_pro={n_pessoas or 's/d'}",
          f"  snapshots nas ultimas 24h: {total_24h} horaria(s) em {len(por_hora)} hora(s) distinta(s)"]
    return out


def _secao_trajetoria_baseline(storage: Storage, now: float) -> list[str]:
    out = []
    for versao in ("v1", "v2"):
        abertas = storage.pr_trajetoria_abertas(versao)
        pendentes = storage.pr_baseline_pendentes(versao)
        poucos_controles = 0
        for row in storage.pr_baseline_all(versao):
            n = len(json.loads(row["controles_json"] or "[]"))
            if n < 10:
                poucos_controles += 1
        out.append(f"TRAJETORIA/BASELINE {versao.upper()}: trajetoria aberta={len(abertas)} | "
                  f"baseline pendente={len(pendentes)} | com n_controles<10={poucos_controles}")
    return out


def _secao_dexpaprika(storage: Storage, now: float) -> list[str]:
    div_24h = storage.pr1_dexpaprika_divergencia_count_since(now - 86400.0)
    candle_divergente = sum(1 for s in storage.pr1_signals()
                            if "candle_divergente" in json.loads(s["tags"] or "[]"))
    return [f"DEXPAPRIKA: divergencias (24h)={div_24h} | sinais ja marcados candle_divergente={candle_divergente} | "
           "creditos usados/restantes: s/d (so no processo ao vivo -- ver resumo diario/heartbeat)"]


def _secao_429(storage: Storage, now: float, logs_dir: Path) -> list[str]:
    linhas = _linhas_log(logs_dir, 86400.0, now)
    por_hora = Counter()
    for linha in linhas:
        if "429" not in linha:
            continue
        m = LOG_LINE_RE.match(linha)
        if m:
            por_hora[m["ts"][:13]] += 1
    if not por_hora:
        return ["GT 429 (24h, pelo log): 0 mencao -- ou o log nao cobre a janela"]
    pior = por_hora.most_common(1)[0]
    return [f"GT 429 (24h, pelo log): {sum(por_hora.values())} mencao(oes) em {len(por_hora)} hora(s); pior hora {pior[0]}h: {pior[1]}"]


def _secao_alertas(storage: Storage) -> list[str]:
    # V1 e V2 sao detectores INDEPENDENTES -- o mesmo (pool,tf,ts_fechamento) pode legitimamente
    # alertar nos 2, por desenho (nunca mistura versao no desempate de duplicado).
    vistos: Counter = Counter()
    for versao, sinais in (("v1", storage.pr1_signals()), ("v2", storage.pr2_signals())):
        for s in sinais:
            if s["tg_message_id"]:
                vistos[(versao, s["pool"], s["tf"], s["ts_fechamento"])] += 1
    duplicados = sum(1 for n in vistos.values() if n > 1)
    return [f"ALERTAS: {duplicados} (versao,pool,tf,ts_fechamento) com mais de 1 sinal alertado "
           "(heartbeat V2: ver correcao nesta entrega -- antes so mandava V1)"]


def _secao_backups_disco(storage: Storage, backups_dir: Path, db_path: Path, now: float) -> list[str]:
    ultimo_ts = storage.get_meta("ultimo_backup_ts")
    desde = f"{_fmt_h(now - float(ultimo_ts))} atras" if ultimo_ts else "nunca (meta ultimo_backup_ts ausente)"
    arquivos = sorted(backups_dir.glob("estado-*.sqlite")) if backups_dir.exists() else []
    tamanho_db = db_path.stat().st_size / 1e6 if db_path.exists() else 0.0
    wal = db_path.with_suffix(db_path.suffix + "-wal")
    tamanho_wal = wal.stat().st_size / 1e6 if wal.exists() else 0.0
    out = [f"BACKUPS: ultimo backup {desde} | {len(arquivos)} arquivo(s) em {backups_dir.name}/ | "
          f"estado.sqlite={tamanho_db:.1f}MB | WAL={tamanho_wal:.1f}MB"]
    try:
        disco = shutil.disk_usage(db_path.parent if db_path.exists() else Path("."))
        out.append(f"DISCO: {disco.free / 1e9:.1f}GB livres de {disco.total / 1e9:.1f}GB")
    except OSError:
        out.append("DISCO: s/d")
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        campos = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in meminfo.splitlines() if ":" in l)}
        mem_total = int(campos.get("MemTotal", "0 kB").split()[0]) / 1e6
        mem_disp = int(campos.get("MemAvailable", "0 kB").split()[0]) / 1e6
        swap_total = int(campos.get("SwapTotal", "0 kB").split()[0]) / 1e6
        swap_livre = int(campos.get("SwapFree", "0 kB").split()[0]) / 1e6
        out.append(f"RAM: {mem_disp:.2f}/{mem_total:.2f}GB disponivel | SWAP: {swap_livre:.2f}/{swap_total:.2f}GB livre")
    except (OSError, ValueError):
        out.append("RAM/SWAP: s/d (nao e Linux ou /proc indisponivel)")
    return out


def _secao_healthchecks_contaminados(storage: Storage) -> list[str]:
    todos = storage.pr1_signals() + storage.pr2_signals()
    contados = Counter()
    for s in todos:
        for tag in json.loads(s["tags"] or "[]"):
            if tag in TAGS_EXCLUSAO_R:
                contados[tag] += 1
    return [
        "HEALTHCHECKS.IO: ultimo ping bem-sucedido: s/d (so no painel do servico -- o bot nunca "
        "persiste isso localmente, so loga quando um ping FALHA)",
        f"TAGS: contaminado_candle={contados.get('contaminado_candle', 0)} | "
        f"risco_irrealista={contados.get('risco_irrealista', 0)} | resumo diario/relatorio ja excluem (ver §17/§18)",
    ]


def _secao_consistencia(storage: Storage, now: float) -> list[str]:
    problemas: Counter = Counter()
    vistos_ts: Counter = Counter()
    for versao, sinais, traj_get, base_get in (
        ("v1", storage.pr1_signals(), lambda eid: storage.pr_trajetoria_get("v1", eid),
         lambda eid: storage.pr_baseline_get("v1", eid)),
        ("v2", storage.pr2_signals(), lambda eid: storage.pr_trajetoria_get("v2", eid),
         lambda eid: storage.pr_baseline_get("v2", eid)),
    ):
        for s in sinais:
            if s["ts_fechamento"] and s["ts_fechamento"] > now + 3600.0:
                problemas["timestamp_no_futuro"] += 1
            vistos_ts[(versao, s["pool"], s["tf"], s["ts_fechamento"])] += 1
            if s["status"] == "fechado":
                entry, stop = s["entry_price"], s["stop"]
                risco_pct = 100.0 * (1.0 - stop / entry) if entry and stop is not None else None
                if s["result_net"] is None:
                    problemas["fechado_sem_result_net"] += 1
                elif risco_pct is not None and risco_pct < 3.0 and "risco_irrealista" not in (s["tags"] or ""):
                    problemas["risco_lt_3pct_sem_tag"] += 1
            # trajetoria/baseline sao preenchidas por um refresh HORARIO separado (`_refresh_baselines`)
            # -- um sinal com menos de 2h ainda nao teve chance de ganhar essas linhas, isso NAO e bug.
            if now - s["ts_fechamento"] > 2 * 3600.0:
                if traj_get(s["id"]) is None:
                    problemas["entrada_sem_trajetoria_apos_2h"] += 1
                if base_get(s["id"]) is None:
                    problemas["entrada_sem_baseline_apos_2h"] += 1
    problemas["ts_fechamento_duplicado"] = sum(1 for n in vistos_ts.values() if n > 1)
    if not any(problemas.values()):
        return ["CONSISTENCIA: nenhum problema encontrado (timestamps, trajetoria/baseline, R, duplicados)"]
    return ["CONSISTENCIA:"] + [f"  {chave}: {n}" for chave, n in problemas.items() if n]


def executar(db_path: Path, logs_dir: Optional[Path], janela_h: float) -> str:
    storage = _abrir_storage_no_arquivo(db_path)
    try:
        now = time.time()
        root = db_path.parent.parent
        logs_dir = logs_dir or (root / "logs")
        backups_dir = root / "backups"
        linhas: list[str] = [f"=== POS-RUNNER saude ({time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(now))}) ==="]
        for secao in (
            lambda: _secao_log(logs_dir, janela_h, now),
            lambda: _secao_uptime_versoes(storage, now),
            lambda: _secao_fila(storage, now),
            lambda: _secao_carteiras(storage, now),
            lambda: _secao_trajetoria_baseline(storage, now),
            lambda: _secao_dexpaprika(storage, now),
            lambda: _secao_429(storage, now, logs_dir),
            lambda: _secao_alertas(storage),
            lambda: _secao_backups_disco(storage, backups_dir, db_path, now),
            lambda: _secao_healthchecks_contaminados(storage),
            lambda: _secao_consistencia(storage, now),
        ):
            try:
                linhas.extend(secao())
            except Exception as exc:  # noqa: BLE001 - 1 secao quebrada nunca derruba o relatorio inteiro
                linhas.append(f"[secao falhou: {type(exc).__name__}: {exc}]")
        return "\n".join(linhas)
    finally:
        storage.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Auditoria geral do bot, somente leitura.")
    parser.add_argument("--db", required=True, help="caminho do estado.sqlite (produção ou cópia)")
    parser.add_argument("--logs", default=None, help="diretorio de logs (padrao: <raiz>/logs, irmao de dados/)")
    parser.add_argument("--janela-h", type=float, default=48.0, help="janela em horas pro log/erros (padrao 48)")
    args = parser.parse_args(argv)
    print(executar(Path(args.db), Path(args.logs) if args.logs else None, args.janela_h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
