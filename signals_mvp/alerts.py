"""Formatacao do alerta do Telegram (curto, legivel em 5 s no celular).

Todo texto vindo da chain (nome/ticker) e nao confiavel: e escapado para HTML e limitado.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional

from .util import clean_text, fmt_age, fmt_mult, fmt_pct, fmt_usd

MINUS = "−"  # sinal de menos tipografico, como no exemplo do handoff


@dataclass
class AlertData:
    """Tudo que o alerta mostra (montado pelo engine a partir do sinal)."""

    signal_id: int
    chain_key: str
    chain_name: str
    terminal: str                    # 'axiom' | 'gmgn'
    symbol: str
    token: str
    pool: str
    etiqueta: str
    score: float
    mc: Optional[float]
    age_s: Optional[float]
    narrative_labels: str
    vol_m5: Optional[float]
    acel: Optional[float]
    buys: Optional[int]
    sells: Optional[int]
    buy_usd: Optional[float]
    sell_usd: Optional[float]
    trades_partial: bool
    liq: Optional[float]
    top10: Optional[float]
    security_status: str             # ok | parcial | sem_dado
    security_via_gt: bool
    alerts: list[str] = field(default_factory=list)
    latency_s: Optional[float] = None
    gmgn_slug: str = ""
    dexscreener_slug: str = ""


def _esc(value: object) -> str:
    return html.escape(clean_text(value, 120), quote=False)


def _security_text(data: AlertData) -> str:
    if data.security_status == "ok":
        return "ok (GT)" if data.security_via_gt else "ok"
    if data.security_status == "parcial":
        return "parcial ⚠"
    return "SEM DADO ⚠"


def format_alert_text(data: AlertData, plano: dict, verde_min: float) -> str:
    emoji = "\U0001f7e2" if data.score >= verde_min else "\U0001f7e1"
    head = (
        f"{emoji} {data.score:.0f}/100 | {_esc(data.chain_name)} | ${_esc(data.symbol)} | "
        f"MC {fmt_usd(data.mc)} | {fmt_age(data.age_s)} | {_esc(data.etiqueta)}"
    )
    narrative = f"Narrativa: {_esc(data.narrative_labels)} (match meta)" if data.narrative_labels else "Narrativa: sem match"
    accel = f" ({fmt_mult(data.acel)})" if data.acel is not None else ""
    buys = "s/d" if data.buys is None else str(data.buys)
    sells = "s/d" if data.sells is None else str(data.sells)
    value = ""
    if data.buy_usd is not None and data.sell_usd is not None:
        value = f" (${fmt_usd(data.buy_usd)}/${fmt_usd(data.sell_usd)}{'*' if data.trades_partial else ''})"
    flow = f"Vol m5: {fmt_usd(data.vol_m5)}{accel} | Compra/venda: {buys}/{sells}{value} | Liq: {fmt_usd(data.liq) if data.liq is not None else 'desconhecida'}"
    top10 = fmt_pct(data.top10, 0) if data.top10 is not None else "s/d"
    warnings = ", ".join(_esc(a) for a in data.alerts[:4]) if data.alerts else "nenhum"
    safety = f"Top10: {top10} | Segurança: {_security_text(data)} | Alertas: {warnings}"
    plan = (
        f"Plano: TP1 +{plano['tp1_pct']:g}% (vende {plano['tp1_venda_pct']:g}%) | "
        f"SL {MINUS}{plano['sl_pct']:g}% | tempo {plano['tempo_min']:g} min"
    )
    latency = f"Lat: {data.latency_s:.0f} s (evento→alerta)" if data.latency_s is not None else "Lat: s/d"
    lines = [head, narrative, flow, safety, plan, latency, f"<code>{_esc(data.token)}</code>"]
    if data.trades_partial and data.buy_usd is not None:
        lines.insert(6, "* valor de compra/venda so das ultimas ~300 trades (janela parcial)")
    return "\n".join(lines)


def build_links(data: AlertData, link_templates: dict) -> list[tuple[str, str]]:
    """[(rotulo, url)] — terminal da chain (Axiom/GMGN) e DexScreener."""
    fields = {
        "pool": data.pool,
        "token": data.token,
        "gmgn_slug": data.gmgn_slug,
        "dexscreener_slug": data.dexscreener_slug,
    }
    terminal_label = "Axiom" if data.terminal == "axiom" else "GMGN"
    return [
        (terminal_label, link_templates[data.terminal].format(**fields)),
        ("DexScreener", link_templates["dexscreener"].format(**fields)),
    ]


def build_keyboard(data: AlertData, link_templates: dict, with_buttons: bool) -> dict:
    rows: list[list[dict]] = [[{"text": label, "url": url} for label, url in build_links(data, link_templates)]]
    if with_buttons:
        rows.append(
            [
                {"text": "✅ entrei", "callback_data": f"e|{data.signal_id}"},
                {"text": "⏭ passei", "callback_data": f"p|{data.signal_id}"},
            ]
        )
    return {"inline_keyboard": rows}


def keyboard_after_choice(data_links: list[list[dict]], label: str) -> dict:
    """Depois do clique: mantem os links e troca os botoes por um carimbo inerte."""
    rows = [row for row in data_links if all("url" in b for b in row)]
    rows.append([{"text": label, "callback_data": "noop"}])
    return {"inline_keyboard": rows}


def callbacks_only(keyboard: dict) -> dict:
    """Teclado sem os botoes de URL (se o Telegram rejeitar um link, o alerta ainda sai com entrei/passei)."""
    rows = [[b for b in row if "callback_data" in b] for row in keyboard.get("inline_keyboard", [])]
    return {"inline_keyboard": [row for row in rows if row]}


def to_plain_text(html_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", html_text))


def delivery_variants(text: str, keyboard: dict) -> list[tuple[str, dict, Optional[str]]]:
    """Do mais completo ao mais simples. So se avanca para a proxima quando o Telegram responde 400 (pedido invalido)."""
    simple = callbacks_only(keyboard)
    return [(text, keyboard, "HTML"), (text, simple, "HTML"), (to_plain_text(text), simple, None)]
