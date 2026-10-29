"""Templates do Telegram da POS-RUNNER-V1 (item 4 do PROMPT DEFINITIVO V1): ENTRADA, TP1, EXIT FULL,
INVALIDADO, WATCHLIST, RESUMO DIARIO, RELATORIO SEMANAL (FASE 3). HTML-escape de ticker/nome
(`chain_adapter.html_escape_ticker`); fila de envio com retry e botoes sao responsabilidade de quem chama
(mesmo padrao do V0: `telegram.TelegramClient` + `alerts.delivery_variants`) -- aqui so o TEXTO e o teclado.

FASE 3 (feedback no Telegram): botoes 👍 Bom / 👎 Ruim / 📝 Nota em todo alerta de ENTRADA/TP1/EXIT FULL
(`feedback_row`/`with_feedback`); o callback do botao e processado por `telegram.OperatorHandler` (reaproveita
o poller/offset ja existente do V0 -- nunca um 2o long-poll no mesmo token). O botao 📝 pede a nota EM
RESPOSTA (`note_prompt_text`): o id do sinal fica embutido no proprio texto do prompt ("(sinal #<id>)"),
resolvido de volta por `NOTE_PROMPT_RE` quando a resposta chega -- sem precisar de nenhum estado novo no
servidor (o historico do Telegram e o unico "estado").
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..util import fmt_usd
from .brt import hora_brt
from .chain_adapter import ChainAdapter, html_escape_ticker

# tags que entram no relatorio semanal "bons vs ruins" (complemento FASE 3, item 3) -- as mesmas que ja
# aparecem no alerta de ENTRADA (TAG_LABELS abaixo), exceto `holders_indisponivel`/`nao_validado` (nunca
# avaliam qualidade do sinal em si).
RELATORIO_TAGS = ("l_bc_suspeito", "HOLDER_CONCENTRADO", "VAMP_RISK", "risco_fora_da_faixa", "base_ge_2d")

# o id do sinal fica embutido no texto do prompt da nota ("...(sinal #123)."): quando a resposta chega,
# `OperatorHandler` relê o texto da mensagem RESPONDIDA (nao um estado novo) para saber a qual sinal associar.
NOTE_PROMPT_RE = re.compile(r"\(sinal #(\d+)\)")

TAG_LABELS = {
    "na_janela_idade": None,                 # nunca aparece (e so o filtro de idade, nao uma tag visivel)
    "risco_fora_da_faixa": "⚠️ risco fora da faixa (15–22%)",
    "HOLDER_CONCENTRADO": "⚠️ HOLDER_CONCENTRADO",
    "holders_indisponivel": "holders: s/d",
    "VAMP_RISK": "⚠️ VAMP_RISK",
    "nao_validado": "⚠️ nao_validado (parametros calibrados na Solana)",
    "l_bc_suspeito": "⚠️ l_bc_suspeito (confira a mao no GeckoTerminal)",
    "base_ge_2d": "base ≥ 2 dias (≥48 candles de 1h)",
}


def _esc(value: Any, limit: int = 40) -> str:
    return html_escape_ticker(str(value) if value is not None else "", limit)


def _tag_lines(tags: list[str]) -> list[str]:
    out = [TAG_LABELS[t] for t in tags if TAG_LABELS.get(t)]
    return out


def _head(emoji: str, title: str, chain_name: str, symbol: str) -> str:
    return f"{emoji} [POS_RUNNER] {title}\nChain: {_esc(chain_name)} | Coin: ${_esc(symbol, 20)}"


def entrada_text(chain_name: str, symbol: str, mc_usd: Optional[float], idade_h: Optional[float], janela_ouro: str,
                 gatilho: list[str], tags: list[str], entry_price: float, stop: float, tp1_price: float,
                 tamanho_usd: float, mint: str, liquidez_usd: Optional[float] = None,
                 mint_authority: Optional[str] = None, freeze_authority: Optional[str] = None) -> str:
    stop_pct = 100.0 * (stop / entry_price - 1.0) if entry_price else None
    risco_pct = abs(stop_pct) if stop_pct is not None else None
    # "mao sugerida por risco": sizing informativo so (NUNCA o campo que o paper usa, esse continua sendo
    # `tamanho_usd`/gestao hibrida acima) -- US$2 de risco fixo dividido pela distancia entrada->stop em %,
    # limitado a US$10 (o mesmo teto da mao fixa hibrida); risco_pct ausente/zero => s/d, nunca um numero
    # inventado.
    mao_risco_usd = min(10.0, 2.0 / (risco_pct / 100.0)) if risco_pct else None
    lines = [
        _head("🚨", "SINAL DE ENTRADA DETECTADO", chain_name, symbol),
        f"Pico (MC): {fmt_usd(mc_usd)}",
        f"MC na entrada: {fmt_usd(entry_price)}",
        f"Idade: {idade_h:.1f}h | Janela: {'dentro da janela de ouro' if janela_ouro == 'janela_ouro' else 'fora da janela de ouro'}",
        f"Setup 1 (Range/Bear Trap) | Gatilho: {', '.join(gatilho) if gatilho else 's/d'}",
    ]
    for line in _tag_lines(tags):
        lines.append(line)
    lines.append(
        f"Parâmetros do trade: entrada ~{fmt_usd(entry_price)} | stop {fmt_usd(stop)}"
        + (f" ({stop_pct:+.1f}%)" if stop_pct is not None else "") + f" | TP1 {fmt_usd(tp1_price)}"
    )
    lines.append(f"Recomendação de tamanho (gestão híbrida): {fmt_usd(tamanho_usd)}")
    lines.append(
        "Mão sugerida por risco (informativo, não é o tamanho usado no paper): "
        + (f"{fmt_usd(mao_risco_usd)} (mín(US$10, US$2÷risco%); risco {risco_pct:.1f}%)"
           if mao_risco_usd is not None else "s/d")
    )
    if liquidez_usd is not None:
        lines.append(f"Liquidez do pool: {fmt_usd(liquidez_usd)}")
    if mint_authority is not None or freeze_authority is not None:
        lines.append(f"Authority: mint {mint_authority or 'indisponivel'} | freeze {freeze_authority or 'indisponivel'}")
    lines.append(f"<code>{_esc(mint, 60)}</code>")
    return "\n".join(lines)


def entrada_confirmada_text(chain_name: str, symbol: str, fill_price: float, stop: float, risco_real_pct: float,
                            risco_irrealista: bool = False) -> str:
    """PATCH 2026-10-27 (diagnostico McRib: fill real ~441k colado no stop 440k, risco ~0,2% distorce
    R -- o alerta ENTRADA so tinha o preco PROVISORIO). Retifica o alerta original uma vez, quando o
    fill real (`entry_price_alerta` vs `entry_price`) e conhecido."""
    linha = f"Fill: {fmt_usd(fill_price)} | Stop: {fmt_usd(stop)} | Risco real: {risco_real_pct:.1f}%"
    if risco_irrealista:
        linha += " ⚠️ risco_irrealista (<3% -- ver /relatorio)"
    return f"{_head('✅', 'ENTRADA CONFIRMADA (fill real)', chain_name, symbol)}\n{linha}"


def tp1_text(chain_name: str, symbol: str, price: float, entry_price: float) -> str:
    pct = 100.0 * (price / entry_price - 1.0) if entry_price else None
    return (f"{_head('🟡', 'TP1 — REALIZAÇÃO PARCIAL (30%)', chain_name, symbol)}\n"
           f"Saída parcial em {fmt_usd(price)}" + (f" ({pct:+.1f}% desde a entrada)" if pct is not None else ""))


def exit_full_text(chain_name: str, symbol: str, price: float, entry_price: float, motivo: str) -> str:
    pct = 100.0 * (price / entry_price - 1.0) if entry_price else None
    rotulo = {"stop": "STOP atingido", "exit_full": "fechou abaixo do suporte (S)"}.get(motivo, motivo)
    return (f"{_head('🔴', 'EXIT FULL — SAÍDA TOTAL', chain_name, symbol)}\n"
           f"{rotulo}: {fmt_usd(price)}" + (f" ({pct:+.1f}% desde a entrada)" if pct is not None else ""))


def invalidado_text(chain_name: str, symbol: str, motivo: str) -> str:
    return f"{_head('⚪', 'INVALIDADO', chain_name, symbol)}\nCandle absurdo ou fora do plano: {_esc(motivo, 80)}"


def watchlist_text(chain_name: str, symbol: str, s_suporte: float, r_resistencia: float, n_testes: int) -> str:
    return (f"{_head('👀', 'WATCHLIST', chain_name, symbol)}\n"
           f"Setup 1 maduro: S {fmt_usd(s_suporte)} – R {fmt_usd(r_resistencia)} | {n_testes} wick(s) de rejeição")


def dado_invalido_text(chain_name: str, symbol: str, motivo: str) -> str:
    rotulo = {"wick": "candle do 1º fechamento com pavio absurdo", "l_bc_floor": "L_bc abaixo do piso de precisão",
             "l_bc_ceiling": "L_bc acima do teto de sanidade (defeito de candle do GT)"}.get(motivo, motivo)
    return f"ℹ️ POS-RUNNER-V1: {_esc(symbol, 20)} ficou `dado_invalido` ({rotulo}) — nunca vira alerta."


def resumo_diario_text(sinais: int, invalidados: int, dado_invalido: int, filtrado_mc_baixo: int, filtrado_idade: int,
                       pnl_pct: Optional[float], uptime_h: float, filtrado_queda_90_96: int = 0,
                       base_ge_2d: int = 0, dexpaprika_impacto: Optional[dict[str, Any]] = None,
                       dexpaprika_divergencias_24h: int = 0) -> str:
    pnl = "s/d" if pnl_pct is None else f"{pnl_pct:+.1f}%"
    linhas = [
        "📋 RESUMO DIÁRIO — POS-RUNNER-V1",
        f"Sinais: {sinais} | Invalidados: {invalidados} | dado_invalido: {dado_invalido} | "
        f"filtrado_mc_baixo: {filtrado_mc_baixo} | filtrado_idade: {filtrado_idade} | "
        f"filtrado_queda_90_96: {filtrado_queda_90_96}",
        f"base ≥ 2 dias (base_ge_2d): {base_ge_2d}",
        f"PnL paper (líquido): {pnl} | Uptime: {uptime_h:.1f}h",
    ]
    # PEDIDO CONSOLIDADO FASE 1 (DexPaprika), item 5: impacto no orcamento de chamadas/creditos -- so
    # aparece quando o recurso esta ligado (dexpaprika_impacto vem None quando desligado).
    if dexpaprika_impacto is not None:
        d = dexpaprika_impacto
        creditos = ("s/d" if d.get("creditos_restantes") is None or d.get("creditos_limite") is None
                   else f"{d['creditos_restantes']}/{d['creditos_limite']}")
        linhas.append(
            f"DexPaprika: fallback {d.get('chamadas_fallback', 0)} chamada(s) | conferência "
            f"{d.get('chamadas_conferencia', 0)} chamada(s) | créditos restantes {creditos} | "
            f"divergências (24h): {dexpaprika_divergencias_24h}"
            + (" | ⚠ circuit breaker ABERTO" if d.get("breaker_aberto") else "")
        )
    return "\n".join(linhas)


def heartbeat_text(uptime_h: float, pools_ativos: int, chamadas_por_min: float, rate_limited_429: int,
                   fases: dict[str, int], fila_atualizacao: int, dado_invalido: int, l_bc_suspeito: int,
                   filtrado_mc_baixo: int, filtrado_idade: int, versao_config_v1: str,
                   uptime_sessao_h: Optional[float] = None) -> str:
    """FASE 1.1 (revisao 2026-10-22): sai ja no startup (nao espera a 1a janela) e a cada 6h; alem de
    chamadas/min, agora traz 429 na janela, pools por FASE do detector (runner/pullback/sem_fase), a fila de
    atualizacao pendente, os 4 contadores de filtro e `versao_config_v1` (para saber qual congelamento gerou
    os numeros). `uptime_h` e o ACUMULADO (todas as sessoes desta versao congelada, pode abranger varios
    restarts); `uptime_sessao_h` (PEDIDO 2026-10-29, item 2) e so desde o ultimo restart -- os 2 juntos
    deixam claro quando o processo reiniciou sem o operador ter trocado a config."""
    fases_txt = f"runner {fases.get('runner', 0)} | pullback {fases.get('pullback', 0)} | sem_fase {fases.get('sem_fase', 0)}"
    sessao = "s/d" if uptime_sessao_h is None else f"{uptime_sessao_h:.1f}h"
    return (
        f"💓 POS-RUNNER-V1 ativo | uptime sessão {sessao} (acumulado {uptime_h:.1f}h) | versao {versao_config_v1}\n"
        f"pools acompanhados: {pools_ativos} ({fases_txt}) | fila de atualização: {fila_atualizacao}\n"
        f"GT: {chamadas_por_min:.1f} chamadas/min | 429 na janela: {rate_limited_429}\n"
        f"dado_invalido: {dado_invalido} | l_bc_suspeito: {l_bc_suspeito} | "
        f"filtrado_mc_baixo: {filtrado_mc_baixo} | filtrado_idade: {filtrado_idade}"
    )


def heartbeat_text_v2(fases: dict[str, int], dado_invalido: int, l_bc_suspeito: int,
                      filtrado_mc_baixo: int, filtrado_idade: int, versao_config_v2: str) -> str:
    """PEDIDO 2026-10-29: o heartbeat so mandava o bloco da V1 -- V2 ficava invisivel no "vivo" periodico
    (so aparecia no resumo diario). Mesmo gatilho/janela do heartbeat V1 (chamado logo depois, MESMA
    mensagem "viva" a cada `heartbeat_interval_s`), mensagem PROPRIA -- nunca mistura com a V1. Uptime/
    chamadas-por-min/429/fila de atualizacao/pools ativos sao do PROCESSO inteiro (1 so GT compartilhado,
    1 so lista de pools pra V0/V1/V2) e ja saem no heartbeat V1 -- aqui so o que e GENUINAMENTE
    especifico da V2 (fase do detector PROPRIO da V2, filtros PROPRIOS da V2), que pode divergir do V1
    pro MESMO pool (parametros diferentes)."""
    fases_txt = f"runner {fases.get('runner', 0)} | pullback {fases.get('pullback', 0)} | sem_fase {fases.get('sem_fase', 0)}"
    return (
        f"💓 POS-RUNNER-V2 ativo | versao {versao_config_v2}\n"
        f"fase do detector V2: {fases_txt}\n"
        f"dado_invalido: {dado_invalido} | l_bc_suspeito: {l_bc_suspeito} | "
        f"filtrado_mc_baixo: {filtrado_mc_baixo} | filtrado_idade: {filtrado_idade}"
    )


def keyboard(adapter: ChainAdapter, mint: str, pool: str, gmgn_slug: str, dexscreener_slug: str) -> dict:
    """Botões inline por rede (item 4): interface da rede (Axiom/GMGN) + DexScreener. `link_for` ja garante
    (assert) que a URL e https://."""
    terminal_label = "Axiom/GMGN" if adapter.name == "solana" else "GMGN"
    rows = [[
        {"text": terminal_label, "url": adapter.link_for("terminal", mint, pool, gmgn_slug, dexscreener_slug)},
        {"text": "DexScreener", "url": adapter.link_for("dexscreener", mint, pool, gmgn_slug, dexscreener_slug)},
    ]]
    return {"inline_keyboard": rows}


# ---------------------------------------------------------------------------
# FASE 3 -- feedback no Telegram (botoes 👍/👎/📝 + relatorio semanal)
# ---------------------------------------------------------------------------


def feedback_row(signal_id: int) -> list[dict[str, str]]:
    """Linha de botoes de feedback (item 1 da FASE 3): `callback_data` no formato `v1fb:<acao>:<signal_id>`,
    resolvido por `telegram.OperatorHandler._handle_v1_feedback_callback`. `up`/`down` gravam o voto (idempotente:
    clicar de novo so atualiza); `note` manda o prompt em resposta (`note_prompt_text`), nunca grava nada so com
    o clique."""
    return [
        {"text": "👍 Bom", "callback_data": f"v1fb:up:{signal_id}"},
        {"text": "👎 Ruim", "callback_data": f"v1fb:down:{signal_id}"},
        {"text": "📝 Nota", "callback_data": f"v1fb:note:{signal_id}"},
    ]


def feedback_keyboard(signal_id: int) -> dict:
    """Teclado SO com a linha de feedback (usado em TP1/EXIT FULL, que respondem ao alerta de ENTRADA e por
    isso nao precisam repetir os botoes de terminal/DexScreener -- aquele teclado ja esta na mensagem
    original)."""
    return {"inline_keyboard": [feedback_row(signal_id)]}


def with_feedback(base_keyboard: dict, signal_id: int) -> dict:
    """Acrescenta a linha de feedback a um teclado JA existente (terminal/DexScreener do ENTRADA, `keyboard()`
    acima) -- nunca substitui as linhas que ja estavam la."""
    rows = list(base_keyboard.get("inline_keyboard") or [])
    rows.append(feedback_row(signal_id))
    return {"inline_keyboard": rows}


def note_prompt_text(symbol: str, signal_id: int) -> str:
    """Pede a nota EM RESPOSTA (item 1 da FASE 3): o id do sinal fica no proprio texto ("(sinal #<id>)"),
    reconhecido por `NOTE_PROMPT_RE` quando a resposta chega -- nao precisa de nenhum estado novo no servidor."""
    return f"📝 Responda esta mensagem com a nota para ${_esc(symbol, 20)} (sinal #{signal_id})."


def _tags_from_json(raw: Optional[str]) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _risco_pct_do_sinal(entry_price: Optional[float], stop: Optional[float]) -> Optional[float]:
    """Mesma formula de `entrada_text` (distancia entrada->stop em %) -- reaproveitada aqui so pra
    relatorio, nunca recalculada com outro criterio."""
    if not entry_price or stop is None:
        return None
    return 100.0 * (1.0 - stop / entry_price)


def _risco_fora_da_faixa_por_gatilho(sinais: list[Any]) -> dict[str, int]:
    """Item 4 do pedido de ajustes de alerta/medicao: entre os sinais marcados `risco_fora_da_faixa`,
    quantos vieram de cada gatilho (um sinal pode ter mais de um gatilho; cada um soma)."""
    out: dict[str, int] = {}
    for s in sinais:
        if "risco_fora_da_faixa" not in _tags_from_json(s["tags"]):
            continue
        for g in _tags_from_json(s["gatilho"]):
            out[g] = out.get(g, 0) + 1
    return out


def _histograma_stop_pct(sinais: list[Any]) -> dict[str, int]:
    """Item 4: histograma do % de stop (distancia entrada->stop) em faixas de 10 pontos percentuais."""
    out: dict[str, int] = {}
    for s in sinais:
        risco = _risco_pct_do_sinal(s["entry_price"], s["stop"])
        label = "s/d" if risco is None else f"{int(risco // 10) * 10}-{int(risco // 10) * 10 + 10}%"
        out[label] = out.get(label, 0) + 1
    return out


def _contagem_lines(title: str, counts: dict[str, int]) -> list[str]:
    if not counts:
        return [f"{title}: sem dados"]

    def _ordem(chave: str) -> tuple[int, int]:
        if chave == "s/d":
            return (1, 0)
        try:
            return (0, int(chave.split("-")[0]))
        except ValueError:
            return (0, 0)

    out = [f"{title}:"]
    for key in sorted(counts, key=_ordem):
        out.append(f"  {key}: {counts[key]}")
    return out


def relatorio_semanal_text(rows: list[Any], pnl_pct: Optional[float], versao_config_v1: str,
                           sinais_semana: Optional[list[Any]] = None, scam_count: int = 0,
                           excluidos: Optional[dict[str, int]] = None) -> str:
    """"Bons vs ruins" da semana (complemento FASE 3, item 3): contagem de votos 👍/👎 por gatilho, por
    janela_ouro/fora_da_janela, por tag (`RELATORIO_TAGS`) e por token, mais o PnL paper do periodo --
    `rows` ja vem filtrada por `versao_config_v1` (nunca mistura versoes de config, mesma regra de
    `daily_summary_v1`). `sinais_semana` (opcional, pedido de ajustes de alerta/medicao item 4) e TODOS os
    ENTRADA da semana -- universo maior que `rows` (que so tem os com feedback do operador) -- usado so
    para a quebra de risco_fora_da_faixa por gatilho e o histograma do % de stop."""
    bons = sum(1 for r in rows if r["voto"] == "bom")
    ruins = sum(1 for r in rows if r["voto"] == "ruim")

    def _group(key_fn: Any) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            for key in key_fn(r):
                slot = out.setdefault(key, {"bom": 0, "ruim": 0})
                if r["voto"] in slot:
                    slot[r["voto"]] += 1
        return out

    por_gatilho = _group(lambda r: _tags_from_json(r["sig_gatilho"]))
    por_janela = _group(lambda r: [r["sig_janela_ouro"] or "s/d"])
    por_tag = _group(lambda r: [t for t in _tags_from_json(r["sig_tags"]) if t in RELATORIO_TAGS])
    # item 3 da FASE 2 de medicao/UX: quebra por authority ativa vs revogada.
    por_mint_authority = _group(lambda r: [f"mint {r['sig_mint_authority'] or 'indisponivel'}"])
    por_freeze_authority = _group(lambda r: [f"freeze {r['sig_freeze_authority'] or 'indisponivel'}"])
    # item 2 do pedido de ajustes de alerta/medicao: agrupamento por token (bons/ruins dos votos).
    por_token = _group(lambda r: [r["symbol"] or "s/d"])

    def _lines(title: str, counts: dict[str, dict[str, int]]) -> list[str]:
        if not counts:
            return [f"{title}: sem dados"]
        out = [f"{title}:"]
        for key, c in sorted(counts.items()):
            out.append(f"  {key}: 👍{c['bom']} 👎{c['ruim']}")
        return out

    sinais_semana = sinais_semana or []
    pnl = "s/d" if pnl_pct is None else f"{pnl_pct:+.1f}%"
    lines = [
        "📊 RELATÓRIO SEMANAL — POS-RUNNER-V1 (bons vs ruins)",
        f"Votos: 👍 {bons} | 👎 {ruins} (de {len(rows)} sinais com feedback)",
        f"PnL paper (líquido, período): {pnl} | versão: {versao_config_v1}",
        _linha_excluidos(excluidos),
        *_lines("Por gatilho", por_gatilho),
        *_lines("Por janela de ouro", por_janela),
        *_lines("Por tag", por_tag),
        *_lines("Por authority", {**por_mint_authority, **por_freeze_authority}),
        *_lines("Por token", por_token),
        *_contagem_lines("Risco fora da faixa por gatilho", _risco_fora_da_faixa_por_gatilho(sinais_semana)),
        *_contagem_lines("Histograma do % de stop", _histograma_stop_pct(sinais_semana)),
    ]
    if scam_count:
        # PEDIDO ADICIONAL FASE 5, item 5: /scam marca manual (nunca bloqueia nem remove o sinal) --
        # so uma contagem informativa aqui.
        lines.append(f"Marcados como scam: {scam_count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PEDIDO ADICIONAL FASE 5: /abertos, /fechados [n], resumo diario com R acumulado
# ---------------------------------------------------------------------------


def _fmt_r(value: Optional[float]) -> str:
    return "s/d" if value is None else f"{value:+.2f}R"


def abertos_text(blocos: list[tuple[str, list[dict[str, Any]]]]) -> str:
    """`blocos`: [(titulo_da_versao, [{"symbol","entry_price","stop","tp1_price","ultimo_preco",
    "r_nao_realizado","tempo_h"}, ...]), ...] -- ja ORDENADO por quem chama. So leitura (o ultimo
    preco vem do ultimo candle JA buscado, nunca uma chamada nova)."""
    lines = ["📂 POSIÇÕES ABERTAS"]
    for titulo, abertos in blocos:
        if not abertos:
            lines.append(f"{titulo}: nenhuma posição aberta")
            continue
        lines.append(f"{titulo}:")
        for d in abertos:
            lines.append(
                f"  ${html_escape_ticker(str(d.get('symbol') or '?'), 20)} | entrada {fmt_usd(d.get('entry_price'))} | "
                f"stop {fmt_usd(d.get('stop'))} | TP1 {fmt_usd(d.get('tp1_price'))} | "
                f"último {fmt_usd(d.get('ultimo_preco'))} | R não realizado: {_fmt_r(d.get('r_nao_realizado'))} | "
                f"{d.get('tempo_h', 0.0):.1f}h desde a entrada"
            )
    return "\n".join(lines)


def fechados_text(blocos: list[tuple[str, list[dict[str, Any]]]], n: int) -> str:
    """`blocos`: [(titulo_da_versao, [{"symbol","r_realizado","motivo_saida","data_fechamento"}, ...]
    -- ja limitado a `n` e ordenado do mais recente pro mais antigo por quem chama."""
    lines = [f"📁 ÚLTIMOS {n} FECHADOS"]
    for titulo, fechados in blocos:
        if not fechados:
            lines.append(f"{titulo}: nenhum trade fechado ainda")
            continue
        lines.append(f"{titulo}:")
        for d in fechados:
            lines.append(
                f"  ${html_escape_ticker(str(d.get('symbol') or '?'), 20)} | R realizado: "
                f"{_fmt_r(d.get('r_realizado'))} | motivo: {d.get('motivo_saida') or 's/d'} | "
                f"{d.get('data_fechamento') or 's/d'}"
            )
    return "\n".join(lines)


def _linha_excluidos(excluidos: Optional[dict[str, int]]) -> str:
    """PEDIDO 2026-10-28 (McRib R acumulado -564,74R/-561,43R contaminado): linha fixa, sempre
    presente (mesmo com 0), provando que o filtro de contaminado_candle/risco_irrealista esta ativo
    -- nunca silencioso."""
    excluidos = excluidos or {}
    total = sum(excluidos.values())
    if not total:
        return "excluídos: 0"
    motivos = ", ".join(f"{k}: {v}" for k, v in sorted(excluidos.items()))
    return f"excluídos: {total} ({motivos})"


def stats_r_text(titulo: str, n_tokens: int, alvo_tokens: int, r_acumulado: Optional[float],
                 taxa_r_positivo: Optional[float], r_medio: Optional[float], r_mediana: Optional[float],
                 excluidos: Optional[dict[str, int]] = None) -> str:
    """PEDIDO ADICIONAL FASE 5, item 3: n de tokens DISTINTOS com trade fechado sobre o alvo (padrão
    30, configurável), R acumulado, taxa de trades com R>0, R médio e mediana -- bloco por versão,
    nunca misturado com a outra. `excluidos` (PEDIDO 2026-10-28): trades contaminado_candle/
    risco_irrealista nunca entram nessas contas -- a linha mostra quantos e por qual motivo."""
    linha_excl = _linha_excluidos(excluidos)
    if n_tokens == 0:
        return f"{titulo}: ainda sem trade fechado (0/{alvo_tokens} tokens distintos) | {linha_excl}"
    taxa = "s/d" if taxa_r_positivo is None else f"{taxa_r_positivo:.0f}%"
    return (
        f"{titulo}: {n_tokens}/{alvo_tokens} tokens distintos com trade fechado | "
        f"R acumulado: {_fmt_r(r_acumulado)} | taxa R>0: {taxa} | "
        f"R médio: {_fmt_r(r_medio)} | R mediana: {_fmt_r(r_mediana)} | {linha_excl}"
    )
