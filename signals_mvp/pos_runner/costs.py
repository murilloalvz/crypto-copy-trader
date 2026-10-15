"""Modelo de custo do POS-RUNNER-V0 (por perna: entrada e saida).

Fontes:
- PumpSwap: tabela oficial por faixa de MC em SOL (pump.fun/docs/fees, pagina de 2026-05-20, lida e citada em
  `docs/sig-fast-cost-model-v0-2026-10-08.md` na branch research/rust-signal-plane-live-shadow-v0). MC em SOL =
  preco em SOL x 1 bilhao. Pool PumpSwap nao canonico: 0,300% fixo.
- Terminal: 1% por perna (handoff; cobre Photon/GMGN/BullX/Trojan sem referral; Axiom fica em 0,75-0,95%).
- Rede: 0,0003 SOL por perna (handoff), sobre a posicao de 0,15 SOL = 0,2% por perna. ATA = 0.
- Raydium CPMM (graduacao da LaunchLab) e Meteora DAMM v2 (graduacao da DBC): fee do pool NAO CONFIRMADA
  nesta versao (depende da config de cada pool). Usa os valores conservadores abaixo ate a Parte A medir a fee
  real de cada pool on-chain; quem nao tem fee conhecida paga o teto (1,25%).
- Slippage AMM para 0,15 SOL: impacto ~ tamanho / reserva da cotacao. Reserva aproximada por produto constante a
  partir da graduacao: reserva_usd(MC) ~ 0,207 x sqrt(L_bc x MC) (no pump.fun ~85 SOL + 206,9M tokens = 20,7% da
  oferta vao para o pool). Para 0,15 SOL o impacto fica tipicamente < 0,2%; liquidez concentrada/retirada pode
  diferir (limitacao documentada).
O custo 2x (sensibilidade do Gate 2) multiplica todas as parcelas.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Optional

# (limite superior da faixa de MC em SOL, fee %) — pools PumpSwap canonicos
PUMPSWAP_TIERS: tuple[tuple[float, float], ...] = (
    (420, 1.250), (1_470, 1.200), (2_460, 1.150), (3_440, 1.100), (4_420, 1.050), (9_820, 1.000),
    (14_740, 0.950), (19_650, 0.900), (24_560, 0.850), (29_470, 0.800), (34_380, 0.750), (39_300, 0.700),
    (44_210, 0.650), (49_120, 0.600), (54_030, 0.550), (58_940, 0.525), (63_860, 0.500), (68_770, 0.475),
    (73_681, 0.450), (78_590, 0.425), (83_500, 0.400), (88_400, 0.375), (93_330, 0.350), (98_240, 0.325),
    (float("inf"), 0.300),
)
_TIER_LIMITS = [t[0] for t in PUMPSWAP_TIERS]

# fee do pool (%) por familia de DEX quando nao ha medida do proprio pool
DEFAULT_POOL_FEE_PCT = {
    "pumpswap_noncanonical": 0.300,
    "raydium_cpmm": 1.000,        # NAO CONFIRMADO (tiers do CPMM: 0,25/1/2/4%): conservador ate medir
    "meteora_damm_v2": 1.000,     # NAO CONFIRMADO (config da DBC): conservador ate medir
}
MAX_POOL_FEE_PCT = 1.250
LP_SHARE_OF_SUPPLY = 0.207


def pumpswap_fee_pct(mc_sol: float) -> float:
    return PUMPSWAP_TIERS[bisect.bisect_left(_TIER_LIMITS, mc_sol)][1]


@dataclass(frozen=True)
class CostModel:
    position_sol: float = 0.15
    terminal_pct: float = 1.0
    network_sol: float = 0.0003
    multiplier: float = 1.0        # 2.0 = sensibilidade "custo 2x" (Gate 2)

    def pool_fee_pct(self, dex: str, mc_usd: float, sol_usd: Optional[float], pool_fee_pct: Optional[float] = None) -> float:
        if pool_fee_pct is not None:
            return pool_fee_pct
        if dex == "pumpswap":
            if not sol_usd:
                return MAX_POOL_FEE_PCT
            return pumpswap_fee_pct(mc_usd / sol_usd)
        return DEFAULT_POOL_FEE_PCT.get(dex, MAX_POOL_FEE_PCT)

    def slippage_pct(self, mc_usd: float, l_bc: Optional[float], sol_usd: Optional[float]) -> float:
        if not l_bc or not sol_usd or mc_usd <= 0:
            return 1.0   # sem como estimar a reserva: 1% conservador
        reserve_usd = LP_SHARE_OF_SUPPLY * (l_bc * mc_usd) ** 0.5
        return 100.0 * (self.position_sol * sol_usd) / reserve_usd

    def leg_pct(self, dex: str, mc_usd: float, l_bc: Optional[float], sol_usd: Optional[float], pool_fee_pct: Optional[float] = None) -> float:
        """Custo total de UMA perna em % do valor negociado."""
        network_pct = 100.0 * self.network_sol / self.position_sol
        base = self.pool_fee_pct(dex, mc_usd, sol_usd, pool_fee_pct) + self.terminal_pct + network_pct + self.slippage_pct(mc_usd, l_bc, sol_usd)
        return base * self.multiplier
