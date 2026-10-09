from dataclasses import dataclass

from src.assets import USDC_MINT


DEMO_WALLET_ADDRESS = "Au3TXDEAkixrxmzRtDVm49tcrLrdkNaLXrH3CkQL37nj"
DEMO_WALLET_LABEL = "Demonstração offline"
DEMO_RPC_HOST = "offline-local"

JUPITER_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
DEMO_DEX_PROGRAMS = (JUPITER_V6, RAYDIUM_CPMM, PUMP_SWAP)


@dataclass(frozen=True)
class DemoAsset:
    mint: str
    buy_price: float
    sell_price: float
    buy_time: int
    sell_time: int


_BASE_TIME = 1_750_000_000
DEMO_ASSETS = (
    DemoAsset(
        "HNGwef6yFPZMm7WNVT9vgM1P44eLLve6YB8b6CVCmB83",
        1.00,
        1.30,
        _BASE_TIME,
        _BASE_TIME + 1_800,
    ),
    DemoAsset(
        "9kZsusa94PptiPCsAs3fw5jBwGL9nXV7sKM1jko3BeTa",
        2.00,
        1.70,
        _BASE_TIME + 3_600,
        _BASE_TIME + 5_400,
    ),
    DemoAsset(
        "6waifDxQSRXSKibDJVetnwp4FpZRuGeJYzM5nXLwvSh8",
        0.50,
        0.80,
        _BASE_TIME + 7_200,
        _BASE_TIME + 9_000,
    ),
    DemoAsset(
        "4CXnzqNg9HK9Lr5kykqQRf3eWZsCAeqQKJvtnUeJuAsE",
        4.00,
        4.20,
        _BASE_TIME + 10_800,
        _BASE_TIME + 12_600,
    ),
    DemoAsset(
        "oWRvYhR7fCnhzYih2zKJGNdayPZpYdaog27yfSPXp7M",
        0.20,
        0.15,
        _BASE_TIME + 14_400,
        _BASE_TIME + 16_200,
    ),
)


def _token_balance(mint: str, amount: float) -> dict:
    return {
        "owner": DEMO_WALLET_ADDRESS,
        "mint": mint,
        "uiTokenAmount": {"uiAmountString": f"{amount:.8f}"},
    }


def _transaction(asset: DemoAsset, side: str, program_id: str) -> dict:
    token_quantity = 25 / asset.buy_price
    if side == "buy":
        block_time = asset.buy_time
        pre_tokens = [
            _token_balance(USDC_MINT, 1_000),
            _token_balance(asset.mint, 0),
        ]
        post_tokens = [
            _token_balance(USDC_MINT, 975),
            _token_balance(asset.mint, token_quantity),
        ]
    else:
        block_time = asset.sell_time
        pre_tokens = [
            _token_balance(USDC_MINT, 975),
            _token_balance(asset.mint, token_quantity),
        ]
        post_tokens = [
            _token_balance(USDC_MINT, 1_000),
            _token_balance(asset.mint, 0),
        ]

    return {
        "blockTime": block_time,
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": DEMO_WALLET_ADDRESS}],
                "instructions": [{"programId": program_id}],
            }
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_999_995_000],
            "preTokenBalances": pre_tokens,
            "postTokenBalances": post_tokens,
            "logMessages": [f"Program {program_id} invoke [1]"],
        },
    }


def _demo_transactions() -> dict[str, dict]:
    transactions = {}
    for index, asset in enumerate(DEMO_ASSETS, start=1):
        program_id = DEMO_DEX_PROGRAMS[(index - 1) % len(DEMO_DEX_PROGRAMS)]
        for side in ("buy", "sell"):
            signature = f"offline-demo-{index:02d}-{side}"
            transactions[signature] = _transaction(asset, side, program_id)
    return transactions


DEMO_TRANSACTIONS = _demo_transactions()


class DemoSolanaClient:
    """Drop-in RPC client backed only by deterministic local fixtures."""

    rpc_host = DEMO_RPC_HOST

    def signatures(
        self, address: str, limit: int, before: str | None = None
    ) -> list[dict]:
        if address != DEMO_WALLET_ADDRESS:
            return []
        items = [
            {
                "signature": signature,
                "blockTime": transaction["blockTime"],
                "err": None,
                "confirmationStatus": "finalized",
            }
            for signature, transaction in DEMO_TRANSACTIONS.items()
        ]
        items.sort(key=lambda item: item["blockTime"], reverse=True)
        if before:
            positions = {
                item["signature"]: index for index, item in enumerate(items)
            }
            start = positions.get(before, len(items) - 1) + 1
            items = items[start:]
        return items[:limit]

    def transaction(self, signature: str) -> dict | None:
        return DEMO_TRANSACTIONS.get(signature)


class DemoPriceProvider:
    """Deterministic prices for demo assets; it never performs HTTP requests."""

    def price_at(self, token_mint: str, timestamp: int) -> float:
        for asset in DEMO_ASSETS:
            if asset.mint == token_mint:
                return asset.buy_price if timestamp < asset.sell_time else asset.sell_price
        raise ValueError(f"Token fora da demonstração offline: {token_mint}")
