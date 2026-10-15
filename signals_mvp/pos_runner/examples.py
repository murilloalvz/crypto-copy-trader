"""Os 5 exemplos do professor (Passo 0 — CALIBRACAO, nunca avaliacao).

Linhagem conferida on-chain em 2026-10-15 (RPC publico, `lineage.account_origin`): a 1a transacao de cada mint
mostra o launchpad e a 1a transacao do pool de graduacao mostra a instrucao de migracao. Estes 5 tokens ficam
FORA de todas as metricas de resultado (sao vencedores escolhidos depois; inclui-los seria vies).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..util import parse_iso
from .quotes import SOL_MINT

DKNG_MINT = "DKNGQFNGQmoBdXSRGKJ8tTu7uPDasw5JDcfMmWniNfow"
ZEC_MINT = "A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS"
EMBER_MINT = "5dvXTZ5qwgafnHtwu3Ls3QrWx1U4LQsFeCuJgkk4QEC6"

# referencia USD de cada cotacao (pool, lado do token da cotacao no pool, desde quando cobrir)
QUOTE_REFERENCES = {
    SOL_MINT: ("Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE", "base"),      # Orca SOL/USDC
    ZEC_MINT: ("GTHKH8s82ZR8GTSFZ1dUu6wfdxhy59wpMShxzG5zjiPm", "base"),      # Orca ZEC/USDC
    DKNG_MINT: ("f2qSBho9ZzGxAxMbbXwc74PbfTH5F3ZYHJTXC5LuyZ7", "base"),      # Raydium CLMM DKNG/USDC (criado antes do ALLINU)
    EMBER_MINT: ("5e1UHN6pZdaWyEMyacjKp6VyF6bbPK3EFsebKE5sSvfS", "base"),    # Meteora EMBER/USDC
}


@dataclass(frozen=True)
class Example:
    key: str
    name: str
    mint: str
    pool: str                    # pool de GRADUACAO (a serie usada no detector)
    handoff_pool: str            # pool citado no handoff (secao 1.5)
    launchpad: str               # pumpfun | raydium_launchlab | meteora_dbc
    dex: str                     # familia do pool de graduacao (custos)
    quote_mint: str
    quote_symbol: str
    created_iso: str             # 1a transacao do mint (criacao do token na curva)
    grad_iso: str                # migracao (1a transacao do pool de graduacao)
    grad_sig: str
    migration_ix: str
    supply: float                # getTokenSupply em 2026-10-15
    tf_prof: Optional[str]       # timeframe indicado pelo professor (None = nao informado)
    note: str = ""

    @property
    def grad_ts(self) -> int:
        return int(parse_iso(self.grad_iso) or 0)

    @property
    def created_ts(self) -> int:
        return int(parse_iso(self.created_iso) or 0)


EXAMPLES: tuple[Example, ...] = (
    Example(
        key="BIKE", name="BIKE TYSON (biketyson)", mint="CbyTNf7UPzvewHh4Zp6umogM2RWahhmGRJWLJnPwpump",
        pool="41rzTMB7JHPTyMXzrYwdqnBecJRhkb8KHYAjrQ9cYxJx", handoff_pool="41rzTMB7JHPTyMXzrYwdqnBecJRhkb8KHYAjrQ9cYxJx",
        launchpad="pumpfun", dex="pumpswap", quote_mint=SOL_MINT, quote_symbol="SOL",
        created_iso="2026-09-03T11:08:06Z", grad_iso="2026-09-03T16:16:10Z",
        grad_sig="9gNCiLkoqiAWc3WBxQWpzauWtYusjnGY6bZudcL2XJ7xQHHQKZjbuU67BQVHTPFHj1yrCimV2XEJgNPkX2aAUhE",
        migration_ix="pump.fun MigrateV2 -> PumpSwap CreatePool", supply=961_853_706.93, tf_prof="4h",
        note="1a assinatura do mint (11:08) e uma transacao que falhou; a criacao na curva e logo depois.",
    ),
    Example(
        key="SOLCAT", name="SOLCAT (Solana Cat)", mint="9U1f18idDeySFnYrurxqT1f5n5nE4g4Uk5LLzP69bh1",
        pool="9Hr6NXw5WSffxNQnqxwZyhRw81uz3PpB7RF9J3i9nMt1", handoff_pool="9Hr6NXw5WSffxNQnqxwZyhRw81uz3PpB7RF9J3i9nMt1",
        launchpad="pumpfun", dex="pumpswap", quote_mint=SOL_MINT, quote_symbol="SOL",
        created_iso="2026-09-17T19:11:50Z", grad_iso="2026-09-17T19:15:41Z",
        grad_sig="22Xjz5uR84EDcPLLDqgjtGtUgKnqXp3JAAjordEKfHawFpvdK9LGePcT2guhHJpVWEkKRcgWX4mhLAAFxEV3hMxd",
        migration_ix="pump.fun MigrateV2 -> PumpSwap CreatePool (curva Gkxp9pv7... completou 19:15:41)",
        supply=975_188_456.39, tf_prof="1h",
        note="mint criado com pump.fun CreateV2 (sem sufixo 'pump'). Handoff dizia MC ~575k em 15/10; o GT mostra ~30k.",
    ),
    Example(
        key="ALLINU", name="ALLINU", mint="4MMQY9bwkxxTtsK3W227Q5ABT6yFY8Pmn9Ze7wmAXKY8",
        pool="5752ia7jC3ZU1c8ycytaSyi5D4nVhApSKvreGbs7pwWL", handoff_pool="4iVHkn5WhmGwrKb2fYFNPnTkqhwYTEEezvsju9YEBY76",
        launchpad="raydium_launchlab", dex="raydium_cpmm", quote_mint=DKNG_MINT, quote_symbol="DKNG",
        created_iso="2026-09-11T20:01:54Z", grad_iso="2026-09-11T20:02:17Z",
        grad_sig="6rBM9CZELoqbxWKEpzZwkuQwWxd8FqFXD7U939k2XebJXNoK1L44nGNhyFAboEE4dW7Be8Unkx3YxzfTkiVVhNh",
        migration_ix="LaunchLab MigrateToCpswap -> Raydium CPMM InitializeWithPermission (LP travada)",
        supply=991_589_149.33, tf_prof=None,
        note="NAO e Meteora: e Raydium LaunchLab cotado em DKNG. O pool do handoff (4iVH, Meteora DLMM) foi criado "
             "54 min depois da graduacao por outra carteira. A curva completou em 23 s.",
    ),
    Example(
        key="ZILL", name="ZILLIONS", mint="8gMWXHfSwBRSLc2wKtLv24JYboCAsKaEqfC5cXLeZJXL",
        pool="82BhSZXxSXBKsAmyHJ5NxkCd6JrSUBrmPsxYgu7Byvns", handoff_pool="82BhSZXxSXBKsAmyHJ5NxkCd6JrSUBrmPsxYgu7Byvns",
        launchpad="raydium_launchlab", dex="raydium_cpmm", quote_mint=ZEC_MINT, quote_symbol="ZEC",
        created_iso="2026-09-17T19:41:30Z", grad_iso="2026-09-17T20:16:33Z",
        grad_sig="4sGwpDs28CAN5EAXuLpJP1L1VJxLvjsu8uK3k4GFBpHrhKJRsqjq1q7R9yxpi5UJviL9Af5hbVm3Enn1YmnzCfu2",
        migration_ix="LaunchLab MigrateToCpswap -> Raydium CPMM InitializeWithPermission (LP travada)",
        supply=999_964_568.89, tf_prof=None,
        note="cotado em ZEC (Zcash na Solana). O USD do GeckoTerminal deste pool fica travado em ~1,0M entre 18/09 12h "
             "e 19/09 12h; a serie usada aqui e a taxa em ZEC x ZEC/USDC.",
    ),
    Example(
        key="FLAME", name="FLAME", mint="9oXA1VWKNiYDYa6VKHBFFBBvZdvuhw1b2eD5Aka7YrVt",
        pool="23B6d3FvDu2eiZxyBLgWdm2W2vn1bdRwJTR6NCfQpxGE", handoff_pool="23B6d3FvDu2eiZxyBLgWdm2W2vn1bdRwJTR6NCfQpxGE",
        launchpad="meteora_dbc", dex="meteora_damm_v2", quote_mint=EMBER_MINT, quote_symbol="EMBER",
        created_iso="2026-09-11T09:48:50Z", grad_iso="2026-09-11T10:32:54Z",
        grad_sig="37vCKiDuPihGTQ62hbqqt5zUZsqFZM8h1KFo1MdZFN5J9u3CLDDpEhiMuJwKjF6sb6NyLAFnqgmotVMEFuY5rKUN",
        migration_ix="Meteora DBC MigrationDammV2 -> DAMM v2 InitializePoolWithDynamicConfig (posicao travada)",
        supply=999_921_622.77, tf_prof="5m",
        note="cotado em EMBER. O pool FLAME/SOL mais antigo (BdEx, 10:06) foi criado por terceiro durante a curva.",
    ),
)

EXAMPLES_BY_KEY = {e.key: e for e in EXAMPLES}
