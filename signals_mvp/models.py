"""Estruturas de dados centrais.

Principio: dado ausente e None (nunca zero). A falta de dado fica explicita
ate o CSV (celula vazia) e o score trata None como "sem pontos + aviso".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

WINDOWS = ("m5", "m15", "m30", "h1", "h6", "h24")


def norm_addr(platform: str, address: str | None) -> str:
    """EVM nao diferencia maiuscula/minuscula; Solana (base58) diferencia."""
    if not address:
        return ""
    return address.lower() if platform == "evm" else address


@dataclass(frozen=True)
class WindowTx:
    """Transacoes de uma janela, JA orientadas ao token alvo (buys = compras do alvo)."""

    buys: Optional[int] = None
    sells: Optional[int] = None
    buyers: Optional[int] = None
    sellers: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        if self.buys is None or self.sells is None:
            return None
        return self.buys + self.sells

    @property
    def buy_pct(self) -> Optional[float]:
        total = self.total
        if not total:
            return None
        return 100.0 * self.buys / total  # type: ignore[operator]


@dataclass
class PoolSnap:
    """Foto de um pool num instante (`observed_ts` = relogio de decisao dessa foto)."""

    chain: str
    pool: str
    dex: str
    name: str
    created_ts: Optional[float]
    observed_ts: float
    token: str                      # contrato do token ALVO (a memecoin)
    symbol: str
    token_name: str
    target_side: str                # 'base' | 'quote'
    other_token: str
    other_symbol: str
    other_is_reference: bool
    both_reference: bool
    price_usd: Optional[float]
    fdv_usd: Optional[float]
    mcap_usd: Optional[float]
    liq_usd: Optional[float]
    liq_unreliable: bool = False    # DEX de curva que reporta liquidez 0/virtual
    vol: dict[str, Optional[float]] = field(default_factory=dict)
    tx: dict[str, WindowTx] = field(default_factory=dict)
    price_change: dict[str, Optional[float]] = field(default_factory=dict)
    locked_liq_pct: Optional[float] = None
    launchpad: Optional[dict[str, Any]] = None
    fee_pct: Optional[float] = None

    @property
    def mc_usd(self) -> Optional[float]:
        """MC = market_cap_usd; se o GeckoTerminal nao tem (comum em pool novo), usa o FDV.

        Aproximacao documentada: em token novo de oferta fixa e toda circulante, FDV = MC.
        """
        return self.mcap_usd if self.mcap_usd else self.fdv_usd

    def age_s(self, now: Optional[float] = None) -> Optional[float]:
        if self.created_ts is None:
            return None
        return (self.observed_ts if now is None else now) - self.created_ts

    def window(self, name: str) -> WindowTx:
        return self.tx.get(name, WindowTx())

    def vol_window(self, name: str) -> Optional[float]:
        return self.vol.get(name)


@dataclass(frozen=True)
class Candle:
    ts: float          # inicio do candle (epoch s)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class TokenInfo:
    address: str
    name: str = ""
    symbol: str = ""
    description: str = ""
    mint_authority: Optional[str] = None     # 'no' | 'yes' | None (desconhecido)
    freeze_authority: Optional[str] = None
    is_honeypot: Optional[str] = None        # 'unknown' etc.
    holders_count: Optional[int] = None
    top10_pct_gt: Optional[float] = None     # informativo: inclui pool/curva, NAO e o top10 "limpo"
    dev_holding_pct: Optional[float] = None
    websites: list[str] = field(default_factory=list)
    twitter: str = ""
    telegram: str = ""
    gt_score: Optional[float] = None


@dataclass
class TradesSummary:
    """Valor (USD) de compras/vendas a partir das ultimas ~300 trades do pool."""

    window_s: float                 # janela pedida (m5 = 300 s)
    n_trades: int
    buy_usd: float
    sell_usd: float
    unique_buy_wallets: int
    unique_sell_wallets: int
    complete: bool                  # False = o corte de 300 trades encurtou a janela
    covered_s: float                # quanto da janela as trades cobrem de fato


@dataclass(frozen=True)
class ChainCtx:
    """O que os parsers precisam saber de uma chain (derivado do config)."""

    name: str
    platform: str                         # 'solana' | 'evm'
    gt_network: str
    reference: frozenset                  # ativos-base que nao sao memecoin (enderecos normalizados)
    liq_unreliable_dex: frozenset = frozenset()
