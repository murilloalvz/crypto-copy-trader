"""Score 0-100, simples e transparente. Todos os pesos e limites vem do config.

Componentes (tetos = score.pesos): narrativa 25, fluxo 35, distribuicao 20, liquidez 20.
Penalidades subtraem. Dado ausente => 0 ponto no sub-item + aviso (nunca "chute").

AVISO CIENTIFICO: pesos e limites sao um ponto de partida NAO validado. O objetivo da v0 e
gravar o que aconteceu depois de cada token avaliado para medir se o score separa bons de
ruins. Recalibrar = calibrar num periodo, congelar, validar num periodo seguinte nunca visto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .metrics import Metrics
from .narrative import NarrativeMatch
from .util import clamp, lerp01


@dataclass
class ScoreResult:
    total: float
    narrativa: float
    fluxo: float
    distribuicao: float
    liquidez: float
    penalidades: float                      # <= 0
    parts: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    @property
    def components_text(self) -> str:
        return (
            f"narr={self.narrativa:.1f};fluxo={self.fluxo:.1f};dist={self.distribuicao:.1f};"
            f"liq={self.liquidez:.1f};pen={self.penalidades:.1f}"
        )


def _log10(value: Optional[float]) -> Optional[float]:
    return math.log10(value) if value is not None and value > 0 else None


def score_token(
    metrics: Metrics,
    narrative: NarrativeMatch,
    top10_pct: Optional[float],
    security_status: str,
    score_cfg: dict,
    top10_max_pct: float,
) -> ScoreResult:
    weights = score_cfg["pesos"]
    flags: list[str] = []
    parts: dict[str, float] = {}

    # --- narrativa -------------------------------------------------------------
    ncfg = score_cfg["narrativa"]
    narr = min(
        weights["narrativa"],
        len(narrative.name_hits) * ncfg["pontos_match_nome_ticker"] + len(narrative.desc_hits) * ncfg["pontos_match_descricao"],
    )
    if not narrative.description_known:
        flags.append("descricao s/d")

    # --- fluxo -------------------------------------------------------------------
    f = score_cfg["fluxo"]
    vol_pts = f["pontos_volume"] * lerp01(_log10(metrics.vol_m5), math.log10(f["vol_m5_zero_usd"]), math.log10(f["vol_m5_cheio_usd"])) if metrics.vol_m5 else 0.0
    if metrics.acel is None:
        accel_pts = f["pontos_aceleracao"] * f["acel_sem_base_fracao"]
        flags.append("acel s/d")
    else:
        accel_pts = f["pontos_aceleracao"] * lerp01(metrics.acel, 1.0, f["acel_cheia"])
    pressure_pts = f["pontos_pressao_compra"] * lerp01(metrics.buy_pct, 50.0, f["compras_pct_cheio"])
    participation_pts = f["pontos_participacao"] * lerp01(metrics.buyers, 0.0, f["compradores_unicos_cheio"])
    fluxo = vol_pts + accel_pts + pressure_pts + participation_pts
    parts.update(vol=vol_pts, acel=accel_pts, pressao=pressure_pts, participacao=participation_pts)

    # --- distribuicao -----------------------------------------------------------
    d = score_cfg["distribuicao"]
    if top10_pct is None:
        top10_pts = 0.0
        flags.append("top10 s/d")
    else:
        top10_pts = d["pontos_top10"] * lerp01(top10_pct, top10_max_pct, d["top10_otimo_pct"])
    dispersion = (metrics.buyers / metrics.buys) if (metrics.buyers is not None and metrics.buys) else None
    dispersion_pts = d["pontos_dispersao"] * lerp01(dispersion, d["dispersao_zero"], d["dispersao_cheia"])
    distribuicao = top10_pts + dispersion_pts
    parts.update(top10=top10_pts, dispersao=dispersion_pts)

    # --- liquidez -----------------------------------------------------------------
    q = score_cfg["liquidez"]
    if metrics.liq is None:
        level_pts = impact_pts = 0.0
        flags.append("liq desconhecida")
    else:
        level_pts = q["pontos_nivel"] * lerp01(_log10(metrics.liq), math.log10(q["liq_zero_usd"]), math.log10(q["liq_cheia_usd"]))
        impact_pts = q["pontos_impacto"] * lerp01(metrics.pos_pct_liq, q["impacto_zero_pct"], q["impacto_cheio_pct"])
    liquidez = level_pts + impact_pts
    parts.update(liq_nivel=level_pts, liq_impacto=impact_pts)

    # --- penalidades -------------------------------------------------------------
    p = score_cfg["penalidades"]
    suspect = 0.0
    if metrics.vol_m5 is not None and metrics.liq and metrics.vol_m5 / metrics.liq > p["vol_sobre_liq_max"]:
        suspect += p["pen_vol_sobre_liq"]
        flags.append("giro vol/liq alto")
    if metrics.tx_por_carteira is not None and metrics.tx_total is not None and (
        metrics.tx_total >= p["tx_por_carteira_min_tx"] and metrics.tx_por_carteira > p["tx_por_carteira_max"]
    ):
        suspect += p["pen_tx_por_carteira"]
        flags.append("poucas carteiras girando")
    if metrics.buys is not None and metrics.sells == 0 and metrics.buys >= p["sem_vendas_compras_min"]:
        suspect += p["pen_sem_vendas"]
        flags.append("sem vendas")
    if metrics.ticket_medio is not None and metrics.ticket_medio < p["ticket_medio_min_usd"]:
        suspect += p["pen_ticket_baixo"]
        flags.append("ticket minusculo")
    suspect = min(suspect, p["volume_suspeito_max"])

    low_liq = 0.0
    if metrics.liq is not None and metrics.liq < p["liq_baixa_usd"]:
        low_liq = p["pen_liq_baixa_max"] * (1.0 - clamp(metrics.liq / p["liq_baixa_usd"], 0.0, 1.0))
        flags.append("liquidez baixa")

    security_pen = 0.0
    if security_status == "sem_dado":
        security_pen = p["pen_seguranca_sem_dado"]
    elif security_status == "parcial":
        security_pen = p["pen_seguranca_parcial"]
    parts.update(pen_volume_suspeito=-suspect, pen_liquidez_baixa=-low_liq, pen_seguranca=-security_pen)
    penalties = -(suspect + low_liq + security_pen)

    total = clamp(narr + fluxo + distribuicao + liquidez + penalties, 0.0, 100.0)
    return ScoreResult(
        total=round(total, 1),
        narrativa=round(narr, 2),
        fluxo=round(fluxo, 2),
        distribuicao=round(distribuicao, 2),
        liquidez=round(liquidez, 2),
        penalidades=round(penalties, 2),
        parts={k: round(v, 3) for k, v in parts.items()},
        flags=flags,
    )
