"""Gatilhos (etiquetas) e filtros previos. Funcoes puras: foto do pool + config => decisao.

Ordem dos portoes (o primeiro que falha da o `etapa` registrado no descartados.csv):
  filtro (estrutura/MC/DEX) -> janela de idade -> liquidez_minima -> gatilho (fluxo/preco)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import PoolSnap

NOVO = "novo"
SOBREVIVENTE20 = "sobrevivente20"
LABELS = (NOVO, SOBREVIVENTE20)


@dataclass
class TriggerResult:
    label: str
    fired: bool
    etapa: str = ""                          # etapa do primeiro portao que falhou
    reasons: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons)


def structural_gate(snap: PoolSnap, cfg_filtros: dict) -> Optional[tuple[str, str]]:
    """Portao comum: (etapa, motivo) se o pool nao serve, senao None."""
    if snap.both_reference:
        return "filtro", "par de ativos de referencia (sem memecoin)"
    if snap.dex in set(cfg_filtros["dex_ignorar"]):
        return "filtro", f"dex ignorada ({snap.dex})"
    if not snap.token:
        return "filtro", "sem contrato do token"
    if snap.price_usd is None or snap.price_usd <= 0:
        return "filtro", "sem preco"
    mc = snap.mc_usd
    if mc is None:
        return "filtro", "sem MC/FDV"
    if mc < cfg_filtros["mc_min_usd"] or mc > cfg_filtros["mc_max_usd"]:
        return "filtro", f"MC fora da faixa ({mc:,.0f})"
    return None


def _liquidity_gate(snap: PoolSnap, min_liq: float) -> Optional[str]:
    if snap.liq_unreliable or snap.liq_usd is None:
        return None  # liquidez desconhecida: nao da para cortar (o score avisa)
    if snap.liq_usd < min_liq:
        return f"liquidez {snap.liq_usd:,.0f} < {min_liq:,.0f}"
    return None


def _flow_reasons(snap: PoolSnap, rules: dict) -> list[str]:
    m5 = snap.window("m5")
    vol5 = snap.vol_window("m5")
    reasons: list[str] = []
    if vol5 is None or vol5 < rules["vol_m5_min_usd"]:
        reasons.append(f"vol_m5 {0 if vol5 is None else vol5:,.0f} < {rules['vol_m5_min_usd']:,.0f}")
    if m5.buys is None or m5.buys < rules["compras_m5_min"]:
        reasons.append(f"compras_m5 {m5.buys} < {rules['compras_m5_min']}")
    if m5.buyers is None or m5.buyers < rules["compradores_unicos_m5_min"]:
        reasons.append(f"compradores_m5 {m5.buyers} < {rules['compradores_unicos_m5_min']}")
    if "transacoes_m5_min" in rules and (m5.total is None or m5.total < rules["transacoes_m5_min"]):
        reasons.append(f"tx_m5 {m5.total} < {rules['transacoes_m5_min']}")
    if "compras_pct_min" in rules:
        pct = m5.buy_pct
        if pct is None or pct < rules["compras_pct_min"]:
            reasons.append(f"compras% {'s/d' if pct is None else format(pct, '.0f')} < {rules['compras_pct_min']:g}")
    return reasons


def check_novo(snap: PoolSnap, cfg_filtros: dict, rules: dict, min_liq: float) -> TriggerResult:
    """novo: pool com menos de `idade_max_min` e fluxo (volume m5, compras/vendas) acima dos limites."""
    structural = structural_gate(snap, cfg_filtros)
    if structural:
        return TriggerResult(NOVO, False, structural[0], [structural[1]])
    age = snap.age_s()
    if age is None:
        return TriggerResult(NOVO, False, "filtro", ["sem data de criacao do pool"])
    if age > rules["idade_max_min"] * 60:
        return TriggerResult(NOVO, False, "gatilho", [f"idade {age / 60:.0f} min > {rules['idade_max_min']} min"])
    liquidity = _liquidity_gate(snap, min_liq)
    if liquidity:
        return TriggerResult(NOVO, False, "liquidez_minima", [liquidity])
    flow = _flow_reasons(snap, rules)
    if flow:
        return TriggerResult(NOVO, False, "gatilho", flow)
    return TriggerResult(NOVO, True, reasons=["fluxo acima dos limites"])


def check_sobrevivente20(
    snap: PoolSnap,
    cfg_filtros: dict,
    rules: dict,
    min_liq: float,
    first_price: Optional[float],
    first_seen_age_s: Optional[float],
) -> TriggerResult:
    """sobrevivente20: 20-25 min, preco >= 40% do inicial e compras ainda ativas."""
    structural = structural_gate(snap, cfg_filtros)
    if structural:
        return TriggerResult(SOBREVIVENTE20, False, structural[0], [structural[1]])
    age = snap.age_s()
    if age is None:
        return TriggerResult(SOBREVIVENTE20, False, "filtro", ["sem data de criacao do pool"])
    low, high = rules["idade_min_min"] * 60, rules["idade_max_min"] * 60
    if not (low <= age <= high):
        return TriggerResult(SOBREVIVENTE20, False, "gatilho", [f"idade {age / 60:.1f} min fora de {rules['idade_min_min']}-{rules['idade_max_min']} min"])
    if first_price is None or first_price <= 0 or first_seen_age_s is None or first_seen_age_s > rules["primeiro_avistamento_max_s"]:
        return TriggerResult(SOBREVIVENTE20, False, "gatilho", ["sem preco inicial confiavel (pool visto tarde demais)"])
    liquidity = _liquidity_gate(snap, min_liq)
    if liquidity:
        return TriggerResult(SOBREVIVENTE20, False, "liquidez_minima", [liquidity])
    reasons: list[str] = []
    ratio = 100.0 * snap.price_usd / first_price  # type: ignore[operator]
    if ratio < rules["preco_min_pct_do_inicial"]:
        reasons.append(f"preco {ratio:.0f}% do inicial < {rules['preco_min_pct_do_inicial']:g}%")
    reasons += _flow_reasons(snap, rules)
    if reasons:
        return TriggerResult(SOBREVIVENTE20, False, "gatilho", reasons)
    return TriggerResult(SOBREVIVENTE20, True, reasons=[f"preco {ratio:.0f}% do inicial, compras ativas"])
