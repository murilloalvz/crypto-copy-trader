from dataclasses import dataclass


WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# V1 is intentionally narrow. Unknown pair orientations remain explicit missing coverage rather
# than being guessed into an opportunity token.
REFERENCE_ASSET_MINTS_V1 = frozenset({WSOL_MINT, USDC_MINT})


@dataclass(frozen=True)
class PumpSwapOpportunityAssetRole:
    opportunity_mint: str
    reference_mint: str
    opportunity_is_base: bool

    def normalize_event_side(self, event_side: str) -> str:
        side = str(event_side).strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("PumpSwap event side must be buy or sell")
        if self.opportunity_is_base:
            return side
        return "sell" if side == "buy" else "buy"


def classify_pumpswap_opportunity_asset(
    *,
    base_mint: str,
    quote_mint: str,
) -> PumpSwapOpportunityAssetRole | None:
    """Resolve the non-reference asset of a PumpSwap pair without guessing.

    PumpSwap Buy/Sell events are expressed relative to the pool base asset. For the market-first
    opportunity store we want the memecoin/non-reference asset. If that asset is the quote side,
    callers must invert buy/sell via ``normalize_event_side``.

    Exactly one side must be a v1 reference asset (WSOL or USDC). Pools with two reference assets
    or two unknown assets remain outside the opportunity radar until a broader asset-role policy is
    explicitly designed and tested.
    """

    base = str(base_mint).strip()
    quote = str(quote_mint).strip()
    if not base or not quote:
        raise ValueError("PumpSwap base_mint and quote_mint are required")
    if base == quote:
        return None

    base_reference = base in REFERENCE_ASSET_MINTS_V1
    quote_reference = quote in REFERENCE_ASSET_MINTS_V1
    if base_reference == quote_reference:
        return None

    if quote_reference:
        return PumpSwapOpportunityAssetRole(
            opportunity_mint=base,
            reference_mint=quote,
            opportunity_is_base=True,
        )
    return PumpSwapOpportunityAssetRole(
        opportunity_mint=quote,
        reference_mint=base,
        opportunity_is_base=False,
    )
