"""Templates do Telegram da POS-RUNNER-V1 (item 4 do PROMPT DEFINITIVO V1): ENTRADA, TP1, EXIT FULL,
INVALIDADO, WATCHLIST, RESUMO DIARIO. HTML-escape de ticker/nome (`chain_adapter.html_escape_ticker`); fila de
envio com retry e botoes sao responsabilidade de quem chama (mesmo padrao do V0: `telegram.TelegramClient` +
`alerts.delivery_variants`) -- aqui so o TEXTO e o teclado.
"""

from __future__ import annotations

from typing import Any, Optional

from ..util import fmt_usd
from .brt import hora_brt
from .chain_adapter import ChainAdapter, html_escape_ticker

TAG_LABELS = {
    "na_janela_idade": None,                 # nunca aparece (e so o filtro de idade, nao uma tag visivel)
    "risco_fora_da_faixa": "⚠️ risco fora da faixa (15–22%)",
    "HOLDER_CONCENTRADO": "⚠️ HOLDER_CONCENTRADO",
    "holders_indisponivel": "holders: s/d",
    "VAMP_RISK": "⚠️ VAMP_RISK",
    "nao_validado": "⚠️ nao_validado (parametros calibrados na Solana)",
    "l_bc_suspeito": "⚠️ l_bc_suspeito (confira a mao no GeckoTerminal)",
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
                 tamanho_usd: float, mint: str, liquidez_usd: Optional[float] = None) -> str:
    stop_pct = 100.0 * (stop / entry_price - 1.0) if entry_price else None
    lines = [
        _head("🚨", "SINAL DE ENTRADA DETECTADO", chain_name, symbol),
        f"Market Cap: {fmt_usd(mc_usd)}",
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
    if liquidez_usd is not None:
        lines.append(f"Liquidez do pool: {fmt_usd(liquidez_usd)}")
    lines.append(f"<code>{_esc(mint, 60)}</code>")
    return "\n".join(lines)


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
                       pnl_pct: Optional[float], uptime_h: float) -> str:
    pnl = "s/d" if pnl_pct is None else f"{pnl_pct:+.1f}%"
    return (
        "📋 RESUMO DIÁRIO — POS-RUNNER-V1\n"
        f"Sinais: {sinais} | Invalidados: {invalidados} | dado_invalido: {dado_invalido} | "
        f"filtrado_mc_baixo: {filtrado_mc_baixo} | filtrado_idade: {filtrado_idade}\n"
        f"PnL paper (líquido): {pnl} | Uptime: {uptime_h:.1f}h"
    )


def heartbeat_text(uptime_h: float, pools_ativos: int, chamadas_por_min: float, rate_limited_429: int,
                   fases: dict[str, int], fila_atualizacao: int, dado_invalido: int, l_bc_suspeito: int,
                   filtrado_mc_baixo: int, filtrado_idade: int, versao_config_v1: str) -> str:
    """FASE 1.1 (revisao 2026-10-22): sai ja no startup (nao espera a 1a janela) e a cada 6h; alem de
    chamadas/min, agora traz 429 na janela, pools por FASE do detector (runner/pullback/sem_fase), a fila de
    atualizacao pendente, os 4 contadores de filtro e `versao_config_v1` (para saber qual congelamento gerou
    os numeros)."""
    fases_txt = f"runner {fases.get('runner', 0)} | pullback {fases.get('pullback', 0)} | sem_fase {fases.get('sem_fase', 0)}"
    return (
        f"💓 POS-RUNNER-V1 ativo | uptime {uptime_h:.1f}h | versao {versao_config_v1}\n"
        f"pools acompanhados: {pools_ativos} ({fases_txt}) | fila de atualização: {fila_atualizacao}\n"
        f"GT: {chamadas_por_min:.1f} chamadas/min | 429 na janela: {rate_limited_429}\n"
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
