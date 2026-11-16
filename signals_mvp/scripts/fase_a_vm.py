"""RODADA 22 (pedido 2026-11-16, entregavel unico antes da Fase B): executa TODAS as consultas
marcadas [VM] em `docs/pos-runner-v3/RODADA_22_FASE_A_AUDITORIA_EXECUCAO_E_VIABILIDADE.md` e imprime
um resumo compacto. PAPER/READ-ONLY.

GARANTIAS DE SO-LEITURA (fail-closed, nunca por convencao):
- o banco abre por URI `mode=ro` + `PRAGMA query_only=1`; qualquer escrita levanta erro do SQLite;
- o `Storage` usado aqui e montado SEM `__init__` (`_storage_somente_leitura`) -- nenhuma criacao de
  tabela, migracao, `_ensure_columns` ou regeneracao de CSV acontece; os metodos de CONSULTA oficiais
  (`pr3_signals`, `pr_trajetoria_get`, `pr_horizonte_fixo_all` ...) sao reusados sem copia de logica;
- o plano pre-registrado NUNCA e registrado por aqui: se `meta` nao tem o hash, a secao (c) recusa
  (diferente de `condicional.garantir_plano_registrado`, que grava na 1a chamada);
- `os.nice(19)` no inicio; zero chamada de rede, EXCETO a secao (d), que so roda com
  `--carteiras` (opt-in, ritmo de 2 chamadas/min, aborta no 1o 429).

Secoes:
 (a) stops ao vivo (V1/V2/V3): contagem com R < -1,2R e distribuicao; gap do candle de stop medido
     em `pr_bars` (open < stop) e o piso do modelo de custo offline para a mesma distancia de stop;
 (b) casos `perdido_offline` / pool fora de 'ativo': valor usado em H1 (pr_baseline), horizonte fixo
     (pr_horizonte_fixo, valor PERSISTIDO) e `simular_v3_carteira` (recalculado pela funcao oficial);
 (c) placar V1/V2 pela regra pre-registrada (`analise.condicional.rodar_h1`, sem copia);
 (d) [opt-in] transacoes bem-sucedidas por carteira "pro" antes/depois do congelamento da lista,
     SO via getSignaturesForAddress (nunca getTransaction -> conta transacoes, NAO compras);
 (e) MIN/MAX(grad_ts) de pr_pools e tokens ja vistos em qualquer tabela do banco.

Uso (na VM, a partir da raiz do repo; leve -- so (d) demora, e so se pedido):
    python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite
    python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite --exportar-vistos /tmp/mints_vistos.txt
    python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite --so-carteiras --carteiras \
        --checkpoint ~/fase_a_carteiras.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..pos_runner.candles import Bar, tf_seconds
from ..storage import Storage

VERSOES = ("v1", "v2", "v3")
TABELA_SINAIS = {"v1": "pr1_signals", "v2": "pr2_signals", "v3": "pr3_signals"}
RISCO_MIN_FRAC = 0.03                      # mesmo corte de `RISCO_IRREALISTA_MIN_PCT` (3%)
LIMIAR_R_STOP = -1.2
CUSTO_PERNA_OFFLINE = 0.0345               # CostModel() com sol_usd=None: 1,25+1,0+0,2+1,0 % por perna
# Congelamento da lista "pro": commit mais antigo com o sha256 (ac4ff4c, 2026-10-27 19:09:46 UTC) --
# ver RODADA_22 §A4a. Data de commit e declarada pelo autor; e a melhor evidencia no repositorio.
CONGELAMENTO_LISTA_TS = int(datetime(2026, 10, 27, 19, 9, 46, tzinfo=timezone.utc).timestamp())
SHA256_LISTA_ESPERADO = "71d6ee62a458290496f364496f33c20382ebc3db53530869478e121139b87aba"
RPC_PUBLICO = "https://api.mainnet-beta.solana.com"
INTERVALO_CARTEIRAS_S = 30.0               # 2 chamadas/min
PAGINA = 1000


class RateLimitAbort(RuntimeError):
    """429 (ou erro JSON-RPC de rate limit) na secao (d): aborta a coleta inteira, nunca insiste."""


# ---------------------------------------------------------------------------
# banco somente leitura
# ---------------------------------------------------------------------------


def conectar_ro(db_path: Path):
    import sqlite3
    if not db_path.exists():
        raise FileNotFoundError(f"banco nao encontrado: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    return con


def _storage_somente_leitura(con) -> Storage:
    """`Storage` sem `__init__`: so `_db`/`_lock` (o que `_one`/`_all` usam). Sem `paths`/`_dirty` de
    proposito -- qualquer caminho que tente escrever CSV/arquivo levanta AttributeError (fail-closed)."""
    st = Storage.__new__(Storage)
    st._db = con
    st._lock = threading.RLock()
    return st


def _tabelas(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _colunas(con, tabela: str) -> set[str]:
    return {r[1] for r in con.execute(f'PRAGMA table_info("{tabela}")')}


def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "s/d"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt(v: Optional[float], casas: int = 2) -> str:
    return "s/d" if v is None else f"{v:+.{casas}f}"


def _quantis(valores: list[float]) -> str:
    if not valores:
        return "(vazio)"
    v = sorted(valores)

    def q(p: float) -> float:
        k = (len(v) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(v) - 1)
        return v[lo] + (v[hi] - v[lo]) * (k - lo)
    return (f"min={v[0]:+.2f} p10={q(.10):+.2f} p25={q(.25):+.2f} mediana={q(.5):+.2f} "
            f"p75={q(.75):+.2f} max={v[-1]:+.2f}")


def r_stop_limpo_modelo(risco_frac: float, custo_perna: float = CUSTO_PERNA_OFFLINE) -> float:
    """R de um stop preenchido EXATAMENTE no nivel, sem gap, so com o custo modelado nas 2 pernas
    (mesma composicao multiplicativa de `simulate_v1._finish`)."""
    return ((1.0 - risco_frac) * (1.0 - custo_perna) ** 2 - 1.0) / risco_frac


# ---------------------------------------------------------------------------
# (a) stops ao vivo
# ---------------------------------------------------------------------------


def _bars(st: Storage, pool: str, tf: str) -> list[Bar]:
    return [Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in st.pr_bars(pool, tf)]


def _gap_do_stop(bars: list[Bar], t_entrada: Optional[float], stop: float) -> tuple[str, Optional[float]]:
    """Primeiro candle (a partir da entrada) com low <= stop. Devolve ('gap'|'sem_gap'|'sem_candles'|
    'nao_achado', open_do_candle)."""
    if not bars:
        return "sem_candles", None
    for b in bars:
        if t_entrada is not None and b.ts < t_entrada:
            continue
        if b.low <= stop:
            return ("gap" if b.open < stop else "sem_gap"), b.open
    return "nao_achado", None


def secao_a(st: Storage, con) -> list[str]:
    out = ["## (a) Stops ao vivo — R realizado (`result_net / (1 - stop/entry_price)`, risco >= 3%)", ""]
    for versao in VERSOES:
        tabela = TABELA_SINAIS[versao]
        if tabela not in _tabelas(con):
            out.append(f"- {versao.upper()}: tabela {tabela} ausente")
            continue
        rows = con.execute(
            f"SELECT id, pool, tf, mint, symbol, stop, entry_price, result_net FROM {tabela} "
            "WHERE evento='ENTRADA' AND status='fechado' AND reason='stop' AND stop IS NOT NULL "
            "AND entry_price > 0 AND result_net IS NOT NULL").fetchall()
        rs: list[float] = []
        mints: set[str] = set()
        excesso_vs_modelo: list[float] = []
        gaps = {"gap": 0, "sem_gap": 0, "sem_candles": 0, "nao_achado": 0}
        gap_r: list[float] = []
        n_risco_baixo = 0
        for r in rows:
            risco = 1.0 - r["stop"] / r["entry_price"]
            if risco < RISCO_MIN_FRAC:
                n_risco_baixo += 1
                continue
            rr = r["result_net"] / risco
            rs.append(rr)
            mints.add(r["mint"] or r["pool"])
            excesso_vs_modelo.append(rr - r_stop_limpo_modelo(risco))
            traj = st.pr_trajetoria_get(versao, r["id"])
            t_ent = traj["t_entrada"] if traj is not None else None
            tipo, aberto = _gap_do_stop(_bars(st, r["pool"], r["tf"] or "1h"), t_ent, r["stop"])
            gaps[tipo] += 1
            if tipo == "gap" and aberto is not None:
                gap_r.append((r["stop"] - aberto) / r["entry_price"] / risco)
        n = len(rs)
        piores = sum(1 for x in rs if x < LIMIAR_R_STOP)
        out.append(f"- {versao.upper()}: stops={n} sinais / {len(mints)} tokens distintos "
                   f"(fora por risco<3%: {n_risco_baixo})")
        if n:
            out.append(f"    R < -1,2R: {piores}/{n} ({100.0 * piores / n:.0f}%) | R < -1,5R: "
                       f"{sum(1 for x in rs if x < -1.5)} | R < -2R: {sum(1 for x in rs if x < -2.0)}")
            out.append(f"    distribuicao R: {_quantis(rs)}")
            out.append(f"    R real - piso do modelo offline (stop limpo, 3,45%/perna): {_quantis(excesso_vs_modelo)}"
                       "  [<0 = pior que custo modelado; ao vivo usa SOL/USD, custo tipicamente MENOR]")
            out.append(f"    candle de stop em pr_bars: gap(open<stop)={gaps['gap']} sem_gap={gaps['sem_gap']} "
                       f"sem_candles(podado?)={gaps['sem_candles']} nao_achado={gaps['nao_achado']}")
            if gap_r:
                out.append(f"    tamanho do gap em R (so os com gap): {_quantis(gap_r)}")
    out.append("")
    out.append("Referencia (modelo offline, stop limpo): 12%->-1,50R | 15%->-1,38R | 22%->-1,24R | "
               "33%->-1,14R; todo stop < 25,3% sai < -1,2R por custo (RODADA_22 §A1a).")
    return out


# ---------------------------------------------------------------------------
# (b) casos perdido_offline / pool fora de 'ativo'
# ---------------------------------------------------------------------------


def _casos(con) -> list[tuple[str, Any]]:
    """Sinais ENTRADA com status 'perdido_offline' OU (nao 'fechado' e pool atual fora de 'ativo')."""
    casos: list[tuple[str, Any]] = []
    for versao in VERSOES:
        tabela = TABELA_SINAIS[versao]
        if tabela not in _tabelas(con):
            continue
        rows = con.execute(
            f"SELECT s.*, p.status AS pool_status, p.motivo AS pool_motivo, p.checked_ts AS pool_checked_ts "
            f"FROM {tabela} s LEFT JOIN pr_pools p ON p.pool = s.pool WHERE s.evento='ENTRADA' AND "
            "(s.status='perdido_offline' OR (s.status <> 'fechado' AND COALESCE(p.status,'(sem linha)') <> 'ativo')) "
            "ORDER BY s.id").fetchall()
        casos.extend((versao, r) for r in rows)
    return casos


def _carteira_v3_por_chave(st: Storage, now: float) -> dict[tuple[str, float], Any]:
    """`simular_v3_carteira.carregar_ao_vivo` OFICIAL (sem copia) sobre o Storage so-leitura."""
    from .simular_v3_carteira import carregar_ao_vivo
    return {(t.pool, float(t.t_entrada)): t for t in carregar_ao_vivo(st, None, now)}


def secao_b(st: Storage, con, now: float, simbolos: Optional[set[str]] = None) -> list[str]:
    out = ["## (b) perdido_offline / pool fora de 'ativo' — valor usado em cada caminho", ""]
    casos = _casos(con)
    if simbolos:
        casos = [(v, r) for v, r in casos if (r["symbol"] or "").upper() in simbolos]
    if not casos:
        out.append("(nenhum caso)")
        return out
    carteira: Optional[dict[tuple[str, float], Any]] = None
    if any(v == "v3" for v, _ in casos):
        try:
            carteira = _carteira_v3_por_chave(st, now)
        except Exception as exc:   # relatorio continua; nunca inventa valor
            out.append(f"(simular_v3_carteira falhou: {type(exc).__name__}: {exc})")
    for versao, r in casos:
        traj = st.pr_trajetoria_get(versao, r["id"])
        t_ent = traj["t_entrada"] if traj is not None else None
        base = con.execute("SELECT r_sinal, dif_pareada FROM pr_baseline WHERE versao=? AND entry_id=?",
                           (versao, r["id"])).fetchone()
        if base is None:
            h1 = "excluido (sem linha em pr_baseline)"
        elif base["dif_pareada"] is None:
            h1 = "excluido (dif_pareada NULL -> fora da amostra de H1)"
        else:
            h1 = f"r_sinal={_fmt(base['r_sinal'])} dif_pareada={_fmt(base['dif_pareada'])}"
        hf = []
        for row in st.pr_horizonte_fixo_all(versao=versao, origem="ao_vivo"):
            if row["entry_key"] != str(r["id"]):
                continue
            marca = ""
            if row["candle_marca_ts"] is not None and t_ent is not None:
                marca = f" marca@{(row['candle_marca_ts'] - t_ent) / 3600.0:.0f}h"
            hf.append(f"{row['horizonte']}:{row['status']} R={_fmt(row['r_mult'])} "
                      f"dif={_fmt(row['dif_pareada'])}{marca}")
        n_bars = len(st.pr_bars(r["pool"], r["tf"] or "1h"))
        if versao != "v3":
            cart = "nao se aplica (o script so le pr3_signals)"
        elif carteira is None:
            cart = "s/d (falhou)"
        else:
            t = carteira.get((r["pool"], float(t_ent))) if t_ent is not None else None
            if t is None:
                cart = ("AUSENTE do script (sem candles/sem trajetoria/entrada invalida)"
                        f" | candles em pr_bars={n_bars}")
            else:
                cart = f"status_72h={t.status_72h} r_72h={_fmt(t.r_72h)} r_7d={_fmt(t.r_7d)}"
        out.append(f"- {versao.upper()}#{r['id']} {r['symbol'] or (r['mint'] or '')[:8]} | sinal={r['status']} "
                   f"| pool={r['pool_status'] or '(sem linha)'} ({r['pool_motivo'] or 's/motivo'}, "
                   f"{_fmt_ts(r['pool_checked_ts'])}) | entrada={_fmt_ts(t_ent)} | candles={n_bars}")
        out.append(f"    H1 legado: {h1}")
        out.append(f"    horizonte fixo (persistido): {'; '.join(hf) or 'sem linha'}")
        out.append(f"    simular_v3_carteira: {cart}")
    return out


# ---------------------------------------------------------------------------
# (c) placar V1/V2 pela regra pre-registrada
# ---------------------------------------------------------------------------


def secao_c(st: Storage) -> list[str]:
    from ..analise import condicional as cond
    out = ["## (c) Placar V1/V2 — regra pre-registrada (`analise.condicional.rodar_h1`, sem copia)", ""]
    registrado = st.get_meta(cond.META_KEY_HASH)
    atual = cond.hash_do_plano()
    if registrado is None:
        return out + [f"RECUSADO: plano nao registrado em meta (atual {atual}); este script nunca registra."]
    if registrado != atual:
        return out + [f"RECUSADO: plano em disco {atual} != registrado {registrado}."]
    out.append(f"plano {atual} (registrado = disco)")
    for versao in ("v1", "v2"):
        for horizonte, rotulo in ((None, "legado fechado-apenas (default do relatorio /analise)"),
                                  ("72h", "horizonte fixo 72h (emenda 2026-11-05; diagnostico, nao e o default)")):
            sinais, excluidos = cond.carregar_sinais_e_excluidos(st, versao, horizonte=horizonte)
            h1 = cond.rodar_h1(sinais)
            linha = (f"- {versao.upper()} [{rotulo}]: status={h1.status} n_tokens={h1.n_tokens} "
                     f"sinais={len(sinais)} excluidos={len(excluidos)}")
            if h1.media_dif_pareada is not None:
                linha += f" media_dif_pareada={h1.media_dif_pareada:+.3f}R"
            if h1.limite_inferior_dia is not None:
                linha += (f" lim_inf_dia={h1.limite_inferior_dia:+.3f} "
                          f"lim_inf_token={h1.limite_inferior_token:+.3f} "
                          f"(a)={h1.criterio_a_bootstrap} (b)={h1.criterio_b_sem_maior_ganho} "
                          f"(c)={h1.criterio_c_permutacao} p_perm={h1.p_valor_permutacao:.3f} "
                          f"(d)={h1.criterio_d_custo_conservador}")
            out.append(linha)
    out.append("Regra V1/V2: n<15 tokens -> AMOSTRA_INSUFICIENTE; 15<=n<30 com media < -0,5R -> FUTIL; "
               "n>=30 -> EDGE_PROVISORIO so com (a)-(d), senao INCONCLUSIVO.")
    return out


# ---------------------------------------------------------------------------
# (d) carteiras "pro": transacoes antes/depois do congelamento (opt-in, 2 chamadas/min)
# ---------------------------------------------------------------------------


def _rpc_signatures(url: str, endereco: str, before: Optional[str]) -> list[dict[str, Any]]:
    opts: dict[str, Any] = {"limit": PAGINA}
    if before:
        opts["before"] = before
    corpo = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                        "params": [endereco, opts]}).encode()
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            dado = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitAbort("HTTP 429") from None
        raise RuntimeError(f"HTTP {exc.code}") from None
    erro = dado.get("error")
    if erro:
        msg = str(erro.get("message", ""))
        if erro.get("code") in (-32429, 429) or "rate" in msg.lower() or "too many" in msg.lower():
            raise RateLimitAbort(f"JSON-RPC {erro.get('code')}: {msg[:80]}")
        raise RuntimeError(f"JSON-RPC {erro.get('code')}: {msg[:80]}")
    return list(dado.get("result") or [])


def contar_carteira(chamar: Callable[[Optional[str]], list[dict[str, Any]]], congelamento_ts: int,
                    inicio_pre_ts: int, max_paginas: int) -> dict[str, Any]:
    """Pagina do mais novo para o mais antigo ate passar de `inicio_pre_ts` (janela pre SIMETRICA a
    pos). Conta so assinaturas sem erro (`err is None`) com blockTime. Nunca le transacao."""
    pos = pre = paginas = 0
    before: Optional[str] = None
    completo = False
    while paginas < max_paginas:
        pagina = chamar(before)
        paginas += 1
        if not pagina:
            completo = True
            break
        for s in pagina:
            bt = s.get("blockTime")
            if s.get("err") is not None or bt is None:
                continue
            if bt >= congelamento_ts:
                pos += 1
            elif bt >= inicio_pre_ts:
                pre += 1
        mais_velho = pagina[-1].get("blockTime")
        if len(pagina) < PAGINA or (mais_velho is not None and mais_velho < inicio_pre_ts):
            completo = True
            break
        before = pagina[-1]["signature"]
    return {"pos": pos, "pre": pre, "paginas": paginas, "completo": completo}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def secao_d(rpc_url: str, checkpoint: Path, now: float, max_paginas: int, max_chamadas: int,
            intervalo_s: float = INTERVALO_CARTEIRAS_S, lista_path: Optional[Path] = None,
            chamar_rpc: Callable[[str, str, Optional[str]], list[dict[str, Any]]] = _rpc_signatures,
            dormir: Callable[[float], None] = time.sleep) -> list[str]:
    from ..pos_runner import carteiras_pro
    lista = Path(lista_path or carteiras_pro.LISTA_PATH)
    out = ["## (d) Carteiras 'pro' — transacoes bem-sucedidas antes/depois do congelamento "
           "(getSignaturesForAddress; NAO sao compras)", ""]
    if not lista.exists():
        return out + [f"lista ausente: {lista}"]
    sha = _sha256(lista)
    out.append(f"lista sha256={sha[:12]}… ({'BATE' if sha == SHA256_LISTA_ESPERADO else 'DIFERENTE do registrado'}"
               f" com 71d6ee62a458…) | congelamento={_fmt_ts(CONGELAMENTO_LISTA_TS)} | RPC={urlparse(rpc_url).hostname}")
    janela = int(now) - CONGELAMENTO_LISTA_TS
    inicio_pre = CONGELAMENTO_LISTA_TS - janela
    out.append(f"janela pos = {janela / 86400:.1f} d; janela pre SIMETRICA desde {_fmt_ts(inicio_pre)}")
    estado: dict[str, Any] = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    if estado.get("congelamento") not in (None, CONGELAMENTO_LISTA_TS) or estado.get("inicio_pre") not in (None, inicio_pre):
        # janela pos cresce com o tempo: um checkpoint de outro dia mede outra janela -- nunca mistura
        estado = {}
    estado.update({"congelamento": CONGELAMENTO_LISTA_TS, "inicio_pre": inicio_pre})
    feitos: dict[str, Any] = estado.setdefault("carteiras", {})
    chamadas = 0
    abortado = ""
    ultima = 0.0
    for endereco, nome, grupo in carteiras_pro.gerar_grupos(lista):
        if endereco in feitos:
            continue
        if chamadas >= max_chamadas:
            abortado = f"teto de {max_chamadas} chamadas nesta execucao (retome com o mesmo --checkpoint)"
            break

        def chamar(before: Optional[str]) -> list[dict[str, Any]]:
            nonlocal chamadas, ultima
            espera = intervalo_s - (time.monotonic() - ultima)
            if ultima and espera > 0:
                dormir(espera)
            ultima = time.monotonic()
            chamadas += 1
            return chamar_rpc(rpc_url, endereco, before)
        try:
            res = contar_carteira(chamar, CONGELAMENTO_LISTA_TS, inicio_pre, max_paginas)
        except RateLimitAbort as exc:
            abortado = f"429/rate limit ({exc}) -- coleta ABORTADA; retome mais tarde com o mesmo --checkpoint"
            break
        except Exception as exc:
            res = {"erro": f"{type(exc).__name__}: {exc}"}
        res.update({"nome": nome, "grupo": grupo})
        feitos[endereco] = res
        checkpoint.write_text(json.dumps(estado))   # arquivo PROPRIO, nunca o banco
    total = carteiras_pro.gerar_grupos(lista)
    out.append(f"carteiras: {len(feitos)}/{len(total)} feitas; chamadas nesta execucao={chamadas}"
               + (f"; PAROU: {abortado}" if abortado else ""))
    por_grupo: dict[str, list[int]] = {}
    for endereco, res in sorted(feitos.items(), key=lambda kv: kv[1].get("nome", "")):
        if "erro" in res:
            out.append(f"- {res['nome']} ({endereco[:4]}…): ERRO {res['erro']}")
            continue
        g = por_grupo.setdefault(res["grupo"], [0, 0, 0])
        g[0] += res["pre"]
        g[1] += res["pos"]
        g[2] += 0 if res["completo"] else 1
        out.append(f"- {res['nome']} ({endereco[:4]}…): pre={res['pre']} pos={res['pos']} "
                   f"paginas={res['paginas']}{'' if res['completo'] else ' TRUNCADO (teto de paginas)'}")
    if por_grupo:
        pre_tot = sum(g[0] for g in por_grupo.values())
        pos_tot = sum(g[1] for g in por_grupo.values())
        ativos_pos = sum(1 for g in por_grupo.values() if g[1] > 0)
        out.append(f"POR PESSOA ({len(por_grupo)} grupos): tx pre={pre_tot} pos={pos_tot}; pessoas com >=1 tx pos="
                   f"{ativos_pos}; grupos com alguma carteira truncada={sum(1 for g in por_grupo.values() if g[2])}")
    out.append("Compras por TOKEN exigem getTransaction (parse de saldos) -- fora deste script, de proposito.")
    return out


# ---------------------------------------------------------------------------
# (e) grad_ts e tokens ja vistos
# ---------------------------------------------------------------------------


def secao_e(con, exportar: Optional[Path] = None) -> list[str]:
    out = ["## (e) pr_pools.grad_ts e tokens ja vistos em qualquer tabela", ""]
    tabelas = sorted(_tabelas(con))
    if "pr_pools" in tabelas:
        for r in con.execute("SELECT COALESCE(status,'?') st, COUNT(*) n, MIN(grad_ts) lo, MAX(grad_ts) hi, "
                             "MIN(found_ts) f FROM pr_pools GROUP BY st ORDER BY st"):
            out.append(f"- pr_pools[{r['st']}]: n={r['n']} grad_ts {_fmt_ts(r['lo'])} -> {_fmt_ts(r['hi'])} "
                       f"| 1a descoberta {_fmt_ts(r['f'])}")
        r = con.execute("SELECT COUNT(*) n, MIN(grad_ts) lo, MAX(grad_ts) hi FROM pr_pools").fetchone()
        out.append(f"- pr_pools[TOTAL]: n={r['n']} MIN(grad_ts)={_fmt_ts(r['lo'])} MAX(grad_ts)={_fmt_ts(r['hi'])}")
    if "pr_retro_candidatos" in tabelas and "grad_ts" in _colunas(con, "pr_retro_candidatos"):
        r = con.execute("SELECT COUNT(*) n, MIN(grad_ts) lo, MAX(grad_ts) hi FROM pr_retro_candidatos").fetchone()
        out.append(f"- pr_retro_candidatos: n={r['n']} grad_ts {_fmt_ts(r['lo'])} -> {_fmt_ts(r['hi'])}")
    vistos: set[str] = set()
    por_tabela: list[tuple[str, int]] = []
    for t in tabelas:
        if "mint" not in _colunas(con, t):
            continue
        mints = {r[0] for r in con.execute(f'SELECT DISTINCT mint FROM "{t}" WHERE mint IS NOT NULL AND mint <> ""')}
        if mints:
            por_tabela.append((t, len(mints)))
            vistos |= mints
    out.append(f"- tokens (mint) distintos em QUALQUER tabela com coluna `mint`: {len(vistos)}")
    out.append("    " + ", ".join(f"{t}={n}" for t, n in por_tabela))
    if vistos and "pr_pools" in tabelas:
        lo = con.execute("SELECT MIN(grad_ts) FROM pr_pools WHERE mint IN (SELECT value FROM json_each(?))",
                         (json.dumps(sorted(vistos)),)).fetchone()[0]
        out.append(f"- graduacao mais antiga entre os vistos com linha em pr_pools: {_fmt_ts(lo)} "
                   "(janela limpa candidata termina ANTES disto)")
    if "pr3_filtrados" in tabelas and "pr_pools" in tabelas:
        # rendimento do B2 depende disto: o portao de qualidade do 1o candle (live.py:2151) barra o pool
        # inteiro na V3; o piloto (piloto_rendimento_b2.py) viu isso em ~80% das graduacoes.
        n_pools = con.execute("SELECT COUNT(*) FROM pr_pools WHERE added_ts IS NOT NULL").fetchone()[0]
        motivos = con.execute("SELECT motivo, COUNT(DISTINCT pool) n FROM pr3_filtrados GROUP BY motivo "
                              "ORDER BY n DESC").fetchall()
        out.append(f"- V3 pr3_filtrados (pools distintos por motivo; pools ja admitidos={n_pools}): "
                   + (", ".join(f"{r['motivo']}={r['n']}" for r in motivos) or "nenhum"))
    out.append("- fora do banco: os ~30 tokens QUEIMADOS de replay/retro estao dentro destas tabelas; "
               "a lista selada do V0 (docs/pos-runner-v0/holdout_selado.json) NAO esta no banco.")
    if exportar is not None:
        exportar.write_text("\n".join(sorted(vistos)) + "\n", encoding="utf-8")
        out.append(f"- lista exportada (arquivo proprio, nunca o banco): {exportar} ({len(vistos)} mints)")
    return out


# ---------------------------------------------------------------------------


def executar(db_path: Path, now: Optional[float] = None, simbolos: Optional[set[str]] = None,
             exportar: Optional[Path] = None) -> str:
    now = time.time() if now is None else now
    con = conectar_ro(db_path)
    try:
        st = _storage_somente_leitura(con)
        out = [f"# Fase A — consultas [VM] (somente leitura) — {_fmt_ts(now)}", f"banco: {db_path}", ""]
        for nome, fn in (("a", lambda: secao_a(st, con)), ("b", lambda: secao_b(st, con, now, simbolos)),
                         ("c", lambda: secao_c(st)), ("e", lambda: secao_e(con, exportar))):
            try:
                out += fn()
            except Exception as exc:   # uma secao quebrada nunca esconde as outras
                out.append(f"## ({nome}) FALHOU: {type(exc).__name__}: {exc}")
            out.append("")
        return "\n".join(out)
    finally:
        con.close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fase A: consultas [VM] somente leitura (RODADA_22).")
    ap.add_argument("--db", type=Path, default=Path("signals_mvp/dados/estado.sqlite"))
    ap.add_argument("--simbolos", default="", help="filtra (b) por simbolo, ex.: PEAK,WASTED")
    ap.add_argument("--exportar-vistos", type=Path, default=None)
    ap.add_argument("--so-carteiras", action="store_true", help="pula (a)/(b)/(c)/(e)")
    ap.add_argument("--carteiras", action="store_true", help="liga (d): rede, 2 chamadas/min, aborta no 1o 429")
    ap.add_argument("--rpc-url", default=os.environ.get("FASE_A_RPC_URL", RPC_PUBLICO),
                    help="endpoint proprio da secao (d); NUNCA le POS_RUNNER_RPC_URLS/CARTEIRAS_RPC_URL")
    ap.add_argument("--checkpoint", type=Path, default=Path("fase_a_carteiras_checkpoint.json"))
    ap.add_argument("--max-paginas-por-carteira", type=int, default=20)
    ap.add_argument("--max-chamadas", type=int, default=240, help="por execucao (240 = ~2h a 2/min)")
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    now = time.time()
    if not args.so_carteiras:
        simbolos = {s.strip().upper() for s in args.simbolos.split(",") if s.strip()} or None
        print(executar(args.db, now, simbolos, args.exportar_vistos))
    if args.carteiras:
        print("\n".join(secao_d(args.rpc_url, args.checkpoint, now, args.max_paginas_por_carteira,
                                args.max_chamadas)))
    elif args.so_carteiras:
        print("(d) desligada: passe --carteiras para ligar (rede).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
