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
TAGS_EXCLUSAO_R = ("contaminado_candle", "risco_irrealista", "entrada_atrasada")


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


def _agrupar_mensagens(linhas: list[str], niveis: tuple[str, ...]) -> list[tuple[str, int, str, str]]:
    """PEDIDO 2026-10-29 (item 1): agrupa pela mensagem EXATA (nunca so o nome do modulo) -- devolve
    (mensagem, contagem, primeira_ocorrencia, ultima_ocorrencia), ordenado por contagem desc."""
    grupos: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        m = LOG_LINE_RE.match(linha)
        if not m or m["level"] not in niveis:
            continue
        msg = m["msg"]
        g = grupos.setdefault(msg, {"n": 0, "primeira": m["ts"], "ultima": m["ts"]})
        g["n"] += 1
        g["ultima"] = m["ts"]   # linhas vem em ordem cronologica (arquivo atual + rotacionados, mais antigo primeiro)
    ordenado = sorted(grupos.items(), key=lambda kv: kv[1]["n"], reverse=True)
    return [(msg, g["n"], g["primeira"], g["ultima"]) for msg, g in ordenado]


def _secao_log(logs_dir: Path, janela_h: float, now: float) -> list[str]:
    linhas = _linhas_log(logs_dir, janela_h * 3600.0, now)
    if not linhas:
        return [f"LOG ({janela_h:.0f}h): arquivo nao encontrado em {logs_dir} -- nada pra ler"]
    n_erros = sum(1 for l in linhas if (m := LOG_LINE_RE.match(l)) and m["level"] in ("ERROR", "CRITICAL"))
    n_avisos = sum(1 for l in linhas if (m := LOG_LINE_RE.match(l)) and m["level"] == "WARNING")
    n_429 = sum(1 for l in linhas if "429" in l or "rate_limited" in l.lower())
    out = [f"LOG ({janela_h:.0f}h, {len(linhas)} linhas): {n_erros} erro(s), {n_avisos} aviso(s), "
          f"{n_429} mencao(oes) a 429"]
    out.append("  top 5 ERRO (texto | contagem | 1a..ultima ocorrencia):")
    for msg, n, primeira, ultima in _agrupar_mensagens(linhas, ("ERROR", "CRITICAL"))[:5]:
        out.append(f"    x{n} [{primeira}..{ultima}] {msg[:90]}")
    out.append("  top 5 AVISO (texto | contagem | 1a..ultima ocorrencia):")
    for msg, n, primeira, ultima in _agrupar_mensagens(linhas, ("WARNING",))[:5]:
        out.append(f"    x{n} [{primeira}..{ultima}] {msg[:90]}")
    return out


def _secao_uptime_versoes(storage: Storage, now: float) -> list[str]:
    # PEDIDO 2026-10-29, item 2: sessao ATUAL (desde o ultimo restart) separada do ACUMULADO (soma de
    # TODAS as sessoes ja registradas, `since_ts=0`) -- antes so a sessao atual aparecia.
    out = []
    sessoes = storage._all("SELECT inicio_ts, fim_ts FROM pr1_uptime ORDER BY inicio_ts DESC LIMIT 5")  # noqa: SLF001
    acumulado_h = storage.pr1_uptime_hours(0.0, now)
    if sessoes:
        ultima = sessoes[0]
        aberta = ultima["fim_ts"] is None
        desde = _fmt_h(now - ultima["inicio_ts"])
        out.append(f"UPTIME: sessao atual {'ABERTA' if aberta else 'FECHADA (bug? deveria estar aberta)'} "
                  f"ha {desde} | acumulado total {acumulado_h:.1f}h | {len(sessoes)} sessao(oes) recentes no banco")
    else:
        out.append(f"UPTIME: sem nenhuma sessao pr1_uptime no banco | acumulado total {acumulado_h:.1f}h")
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
    atrasados: list[tuple[str, str]] = []
    for row in pools:
        bars_1h = storage.pr_bars(row["pool"], "1h")
        if not bars_1h:
            sem_tentativa += 1
            continue
        if now - bars_1h[-1][0] > 2 * 3600.0:
            atrasados.append((row["symbol"] or row["pool"], row["pool"]))
    abertos_v1 = storage.pr1_signals(status="aberto")
    abertos_v2 = storage.pr2_signals(status="aberto")
    out = [f"FILA: {len(pools)} pool(s) ativo(s) | sem nenhum candle 1h ainda: {sem_tentativa} | "
          f"sem candle 1h novo ha >2h: {len(atrasados)}"]
    if atrasados:
        # PEDIDO 2026-10-29, item 1: nome dos pools, nunca so a contagem.
        out.append("  pools atrasados (>2h): " + ", ".join(f"{sym} ({pool[:8]}...)" for sym, pool in atrasados))
    # PEDIDO 2026-10-30 (item 5b): quantos pools DISTINTOS ficaram sem vaga (max_pools) nas ultimas
    # 48h -- `_promote`/`_retire_estagnado` (live.py) liberam vaga de pool morto automaticamente;
    # isto so mede se ainda sobra demanda sem atender.
    vaga_negada_48h = storage.pr_vaga_descarte_count(now - 48 * 3600.0)
    out.append(f"  candidatos novos sem vaga (max_pools, 48h): {vaga_negada_48h} pool(s) distinto(s)")
    # PEDIDO 2026-10-30 (FASE 1a/1b): ENTRADA descartada por staleness (_late) nunca abre posicao/
    # alerta; evento pre-admissao mede setup que aconteceu no mercado real enquanto o pool esperava
    # vaga -- os dois so existem a partir desta entrega (0 em bancos sem o patch, nunca inventado).
    entradas_atrasadas_24h = storage.pr_entrada_atrasada_count(now - 24 * 3600.0)
    eventos_pre_admissao_24h = storage.pr_evento_pre_admissao_count_por_tipo(now - 24 * 3600.0)
    out.append(f"  entradas_atrasadas (24h, nunca abriram posicao): {entradas_atrasadas_24h}")
    out.append("  eventos_pre_admissao (24h, setup real enquanto esperava vaga): " +
              (", ".join(f"{k}={v}" for k, v in sorted(eventos_pre_admissao_24h.items())) or "0"))
    # PEDIDO 2026-10-30 (FASE 2, item 5): rotacao por incapacidade estrutural -- aposentados (vao pra
    # 'dormente', nunca 'encerrado') e readmitidos nas ultimas 24h, dormentes atuais, candidatos
    # esperando vaga agora (mesmo universo de `_promote`/`_rotacionar_vagas`: 'verificado' com
    # criado_ts conhecido).
    aposentados_rotacao_24h = storage.pr_dormentes_rotacionados_count_desde(now - 24 * 3600.0)
    readmitidos_24h = storage.pr_dormentes_readmitidos_count_desde(now - 24 * 3600.0)
    dormentes_agora = len(storage.pr_dormentes("dormente"))
    candidatos_esperando = sum(1 for r in storage.pr_pools("verificado") if "criado_ts" in json.loads(r["info"] or "{}"))
    out.append(f"  rotacao: aposentados (24h)={aposentados_rotacao_24h} | readmitidos (24h)={readmitidos_24h} | "
              f"dormentes agora={dormentes_agora} | candidatos esperando vaga={candidatos_esperando}")
    out.append(f"POSICOES ABERTAS: V1={len(abertos_v1)} V2={len(abertos_v2)}")
    for s in (abertos_v1 + abertos_v2)[:5]:
        bars = storage.pr_bars(s["pool"], s["tf"])
        ultimo = f"{(now - bars[-1][0]) / 60.0:.0f}min atras" if bars else "sem candle"
        out.append(f"  {s['symbol']} ({s['pool'][:8]}...): ultimo candle {ultimo}")
    return out


_RE_CICLO_CARTEIRAS = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})Z .*POS-RUNNER-V1: ciclo .*"
    r"carteiras_tentativas=(?P<tent>\d+) carteiras_gravados=(?P<grav>\d+) "
    r"carteiras_erros=(?P<err>\d+) carteiras_orcamento_esgotado=(?P<orc>\d+)"
)
_RE_ERRO_CARTEIRAS = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})Z .*POS-RUNNER carteiras: snapshot horario falhou em (?P<msg>.*)$"
)


def _secao_carteiras(storage: Storage, now: float, logs_dir: Path) -> list[str]:
    """PEDIDO 2026-10-29, item 1/2: diagnostico completo da coleta "ao lado" de carteiras "pro" --
    elegiveis AGORA (posicao aberta OU fase runner/pullback, V1 ou V2 -- PEDIDO 2026-10-29), RPC
    configurado (gravado pelo PROPRIO processo ao vivo em `meta` -- nunca um env var lido por ESTE
    script, que pode rodar num shell diferente), orcamento usado/limite, ultima tentativa/resultado e
    ultimo erro (do log, `_atualizar_carteiras_horaria`), e a distribuicao de fases AGORA (lida de
    `pr_pools.fase_v1`/`fase_v2`, persistida a cada ciclo que processa candle novo -- NUNCA mais do
    ultimo heartbeat em memoria)."""
    from ..pos_runner import carteiras_pro as cp
    sha = storage.get_meta(cp.META_KEY_SHA256)
    n_carteiras = storage.get_meta(cp.META_KEY_N_CARTEIRAS)
    n_pessoas = storage.get_meta(cp.META_KEY_N_PESSOAS)
    por_hora = Counter()
    for row in storage.pr_carteiras_snapshot_all():
        if now - row["ts"] <= 86400.0:
            por_hora[int(row["ts"] // 3600)] += 1
    total_24h = sum(por_hora.values())
    out = [f"CARTEIRAS: lista carregada={'sim' if sha else 'NAO'} (sha256={sha[:12] + '...' if sha else 's/d'}) "
          f"| n_carteiras_pro={n_carteiras or 's/d'} n_pessoas_pro={n_pessoas or 's/d'}",
          f"  snapshots nas ultimas 24h: {total_24h} horaria(s) em {len(por_hora)} hora(s) distinta(s)"]
    pools_ativos = storage.pr_pools("ativo")
    abertos = {s["pool"] for s in storage.pr1_signals(status="aberto")} | \
              {s["pool"] for s in storage.pr2_signals(status="aberto")}
    fases_v1: Counter = Counter()
    fases_v2: Counter = Counter()
    elegiveis = set(abertos)
    for row in pools_ativos:
        f1 = row["fase_v1"] or "sem_fase"
        f2 = row["fase_v2"] or "sem_fase"
        fases_v1[f1] += 1
        fases_v2[f2] += 1
        if f1 in ("runner", "pullback") or f2 in ("runner", "pullback"):
            elegiveis.add(row["pool"])
    out.append(f"  elegiveis AGORA (posicao aberta OU fase runner/pullback, V1 ou V2): {len(elegiveis)} pool(s)")
    for versao, fases in (("V1", fases_v1), ("V2", fases_v2)):
        out.append(f"  fases {versao} AGORA ({len(pools_ativos)} pool(s) ativo(s), de pr_pools -- nao e "
                  "'caixa', so sem_fase/runner/pullback existem no detector): " +
                  " ".join(f"{k}={fases.get(k, 0)}" for k in ("sem_fase", "runner", "pullback")))
    runtime_raw = storage.get_meta("pr_carteiras_runtime")
    if runtime_raw:
        rt = json.loads(runtime_raw)
        inicio_do_dia = now - (now % 86400.0)
        usado_hoje = storage.pr_carteiras_snapshot_count_since(inicio_do_dia, "horaria")
        out.append(f"  RPC configurado={'sim' if rt['rpc_configurado'] else 'NAO'} | "
                  f"SEM_CARTEIRAS={'sim (desligado)' if rt['sem_carteiras'] else 'nao'} | "
                  f"orcamento hoje: {usado_hoje}/{rt['carteiras_max_chamadas_dia']} chamada(s) | "
                  f"(config lida ha {_fmt_h(now - rt['ts'])}, no proprio processo ao vivo)")
    else:
        out.append("  RPC configurado/orcamento: s/d (nenhum _startup rodou ainda nesta copia do banco)")
    linhas = _linhas_log(logs_dir, 86400.0, now)
    ultimo_ciclo = None
    for linha in linhas:
        m = _RE_CICLO_CARTEIRAS.match(linha)
        if m:
            ultimo_ciclo = m
    if ultimo_ciclo:
        out.append(f"  ultima tentativa da coleta (log, [{ultimo_ciclo['ts']}]): "
                  f"tentativas={ultimo_ciclo['tent']} gravados={ultimo_ciclo['grav']} "
                  f"erros={ultimo_ciclo['err']} orcamento_esgotado={ultimo_ciclo['orc']}")
    else:
        out.append("  ultima tentativa da coleta: nenhuma linha de ciclo no log (bot nunca rodou 1 tick "
                  "nesta janela, ou --logs nao aponta pro diretorio certo)")
    ultimo_erro = None
    for linha in linhas:
        m = _RE_ERRO_CARTEIRAS.match(linha)
        if m:
            ultimo_erro = m
    out.append(f"  ultimo erro da coleta: [{ultimo_erro['ts']}] {ultimo_erro['msg']}" if ultimo_erro
              else "  ultimo erro da coleta: nenhum no log (24h)")
    return out


_RE_ERRO_SOMBRA = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})Z .*POS-RUNNER sombra \((?P<motivo>[^)]+)\): erro inesperado"
)


def _secao_sombra(storage: Storage, now: float, logs_dir: Path) -> list[str]:
    """PEDIDO 2026-10-29, item 3: pools sombra ativos (ultima leitura conhecida, persistida a cada
    heartbeat -- so existe na memoria do processo ao vivo), descartados por teto
    (SOMBRA_MAX_POOLS), sinais por motivo/status (`pr_sombra`) e erros da sombra (log, `_sombra_safe`
    -- ver incidente de producao 2026-10-29, candles sobrepostos)."""
    out = ["SOMBRA:"]
    ativos_raw = storage.get_meta("pr_sombra_ativos")
    if ativos_raw:
        ativos = json.loads(ativos_raw)
        out.append(f"  pools ativos: {ativos['n_pools']} (ha {_fmt_h(now - ativos['ts'])}, no ultimo heartbeat)")
    else:
        out.append("  pools ativos: s/d (so existe na memoria do processo ao vivo -- aparece apos o 1o heartbeat)")
    descartados = storage.pr_sombra_descarte_count(now - 86400.0)
    out.append(f"  descartados por teto (SOMBRA_MAX_POOLS, 24h): {descartados}")
    por_motivo: Counter = Counter()
    por_status: Counter = Counter()
    for s in storage.pr_sombra_signals():
        por_motivo[s["versao"]] += 1
        por_status[s["status"]] += 1
    if por_motivo:
        out.append("  sinais por motivo: " + " | ".join(f"{k}={v}" for k, v in sorted(por_motivo.items())))
        out.append("  sinais por status: " + " | ".join(f"{k}={v}" for k, v in sorted(por_status.items())))
    else:
        out.append("  sinais: 0 (nenhum candidato sombra ainda)")
    linhas = _linhas_log(logs_dir, 86400.0, now)
    ultimo_erro, erros_24h = None, 0
    for linha in linhas:
        m = _RE_ERRO_SOMBRA.match(linha)
        if m:
            erros_24h += 1
            ultimo_erro = m
    out.append(f"  erros da sombra (24h, log): {erros_24h}" +
              (f" | ultimo: [{ultimo_erro['ts']}] {ultimo_erro['motivo']}" if ultimo_erro else ""))
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
    out = [f"DEXPAPRIKA: divergencias (24h)={div_24h} (linhas = campo x candle; ver candles distintos "
          f"abaixo) | sinais ja marcados candle_divergente={candle_divergente} | "
          "creditos usados/restantes: s/d (so no processo ao vivo -- ver resumo diario/heartbeat)"]
    # PEDIDO 2026-10-29, item 4: cada linha ja registrada JA passou da tolerancia (so loga quando
    # diverge) -- a regra que decide `candle_divergente` (condicional.py: _candle_divergente_confirmado)
    # e: qualquer linha aqui cujo `candle_ts` seja EXATAMENTE o candle do GATILHO (`ts_fechamento`) do
    # sinal confirma a tag -- nunca um limiar novo, so presenca. diff% > 50% em QUALQUER campo do MESMO
    # candle = `candle_corrompido_provavel` (qualidade_candle.py) -- MESMO veto do `dexpaprika_divergente`
    # generico (nenhum gatilho/TP1/saida decide nesse candle ate confirmar pelo seguinte ou pelas fontes
    # concordarem), so um rotulo mais forte pra severidade.
    out.append("  regra candle_divergente: campo (open/high/low/close/volume) com diff% > tolerancia "
              "(padrao 1.0%) ENTRE GT e DexPaprika no MESMO candle -- só uma linha aqui já passou desse "
              "teto; confirma a tag quando o candle_ts bate com o candle do GATILHO do sinal (presença, "
              "sem limiar novo). diff% > 50% em qualquer campo = candle_corrompido_provavel -- nenhum "
              "gatilho/TP1/saída decide nesse candle até o seguinte ou as fontes concordarem.")
    recentes = [r for r in storage.pr1_dexpaprika_divergencias() if now - r["ts"] <= 86400.0]
    # PEDIDO 2026-10-29, item 4: dedupe -- 1 linha por (pool,candle_ts), nunca 1 por (pool,candle_ts,
    # campo); um candle com 2+ campos divergentes aparecia 2x+ no relatorio antes desta correcao.
    agrupado: dict[tuple[Optional[str], Optional[int]], dict[str, Any]] = {}
    for r in recentes:
        chave = (r["pool"], r["candle_ts"])
        g = agrupado.setdefault(chave, {"symbol": r["symbol"], "campos": [], "diff_max": 0.0, "ts": r["ts"]})
        g["campos"].append(f"{r['campo']} {r['diff_pct']:.2f}%")
        g["diff_max"] = max(g["diff_max"], r["diff_pct"])
        g["ts"] = max(g["ts"], r["ts"])
    linhas = sorted(agrupado.items(), key=lambda kv: kv[1]["ts"], reverse=True)
    if linhas:
        out.append(f"  ultimos {min(15, len(linhas))} de {len(linhas)} candle(s) divergente(s) (24h, "
                  "dedupe por pool+candle_ts) [token hora campos]:")
        for (_pool, candle_ts), g in linhas[:15]:
            hora = time.strftime("%H:%M", time.gmtime(candle_ts)) if candle_ts is not None else "s/d"
            marca = " [CORROMPIDO_PROVAVEL]" if g["diff_max"] > 50.0 else ""
            out.append(f"    {g['symbol'] or 's/d'} {hora} {', '.join(g['campos'])}{marca}")
    return out


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
        f"risco_irrealista={contados.get('risco_irrealista', 0)} | "
        f"entrada_atrasada={contados.get('entrada_atrasada', 0)} | resumo diario/relatorio ja excluem (ver §17/§18)",
    ]


def _confirmado_com_fill_real(storage: Storage, versao: str, versao_config: Optional[str], signal_id: int) -> bool:
    """PEDIDO 2026-10-30 (diagnostico risco_lt_3pct_sem_tag): a tag `risco_irrealista` NUNCA e
    calculada a partir de `entry_price`/`stop` (congelados no PLANO do alerta, nunca reescritos) --
    so e gravada por `live.py: _confirmar_entrada`, e so quando o operador usa `/entrei` com um fill
    REAL (`risco_real_pct = 100*res.risk_frac`, uma grandeza DIFERENTE do risco do plano). Mesma
    chave de idempotencia gravada la (`PosRunnerLive._key_v1`/`_key_v2`, formato
    "<versao>:confirma:<versao_config>:<signal_id>") -- nunca recalculada aqui, so leitura de
    `pr_alerts`."""
    if not versao_config:
        return False
    return storage.pr_alert_seen(f"{versao}:confirma:{versao_config}:{signal_id}")


def _secao_consistencia(storage: Storage, now: float) -> list[str]:
    problemas: Counter = Counter()
    vistos_ts: Counter = Counter()
    # PEDIDO 2026-10-29, item 5: nao so contar -- NOMEAR qual entrada esta sem trajetoria/baseline.
    sem_evidencia: list[str] = []
    for versao, sinais, traj_get, base_get, versao_col in (
        ("v1", storage.pr1_signals(), lambda eid: storage.pr_trajetoria_get("v1", eid),
         lambda eid: storage.pr_baseline_get("v1", eid), "versao_config_v1"),
        ("v2", storage.pr2_signals(), lambda eid: storage.pr_trajetoria_get("v2", eid),
         lambda eid: storage.pr_baseline_get("v2", eid), "versao_config_v2"),
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
                    # PEDIDO 2026-10-30: so e uma inconsistencia de verdade se o operador CONFIRMOU
                    # um fill real (unica fonte da tag) e ela ainda assim ficou faltando -- sem
                    # confirmacao, o risco <3% e so do PLANO (nunca comparavel a tag), nunca um bug.
                    if _confirmado_com_fill_real(storage, versao, s[versao_col], s["id"]):
                        problemas["risco_lt_3pct_sem_tag"] += 1
                    else:
                        problemas["risco_planejado_lt_3pct_sem_confirmacao_real"] += 1
            # trajetoria/baseline sao preenchidas por um refresh HORARIO separado (`_refresh_baselines`)
            # -- um sinal com menos de 2h ainda nao teve chance de ganhar essas linhas, isso NAO e bug.
            if now - s["ts_fechamento"] > 2 * 3600.0:
                traj, base = traj_get(s["id"]), base_get(s["id"])
                falta_traj = traj is None
                falta_base = base is None
                if falta_traj:
                    problemas["entrada_sem_trajetoria_apos_2h"] += 1
                if falta_base:
                    problemas["entrada_sem_baseline_apos_2h"] += 1
                if falta_traj or falta_base:
                    motivo = "trajetoria" if falta_traj and not falta_base else (
                        "baseline" if falta_base and not falta_traj else "trajetoria+baseline")
                    sem_evidencia.append(f"{versao}:{s['id']} {s['symbol']} (pool {s['pool'][:8]}...): sem {motivo}")
    problemas["ts_fechamento_duplicado"] = sum(1 for n in vistos_ts.values() if n > 1)
    if not any(problemas.values()):
        return ["CONSISTENCIA: nenhum problema encontrado (timestamps, trajetoria/baseline, R, duplicados)"]
    out = ["CONSISTENCIA:"] + [f"  {chave}: {n}" for chave, n in problemas.items() if n]
    if sem_evidencia:
        out.append(f"  entradas sem trajetoria/baseline ({len(sem_evidencia)}, primeiras 10):")
        out.extend(f"    {linha}" for linha in sem_evidencia[:10])
        out.append("  corrige com: python -m signals_mvp.scripts.backfill_evidencia --db dados/estado.sqlite "
                  "(reusa candles ja em pr_bars, zero chamada nova; marca pre_instrumentacao quando o "
                  "candle nao esta mais em cache)")
    return out


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
            lambda: _secao_carteiras(storage, now, logs_dir),
            lambda: _secao_sombra(storage, now, logs_dir),
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
