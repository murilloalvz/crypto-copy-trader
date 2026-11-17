from src.solana import SolanaClient, SolanaRPCError


def fetch_token_decimals(client: SolanaClient, token_mint: str) -> int:
    token_mint = token_mint.strip()
    if not token_mint:
        raise ValueError("token_mint cannot be empty")
    result = client.call("getTokenSupply", [token_mint, {"commitment": "confirmed"}])
    try:
        decimals = int(result["value"]["decimals"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SolanaRPCError(
            f"getTokenSupply returned invalid decimals for {token_mint}"
        ) from exc
    if decimals < 0 or decimals > 18:
        raise SolanaRPCError(
            f"getTokenSupply returned unsupported decimals={decimals} for {token_mint}"
        )
    return decimals


class TokenDecimalsCache:
    def __init__(self, client: SolanaClient):
        self.client = client
        self._cache: dict[str, int] = {}

    def get(self, token_mint: str) -> int:
        token_mint = token_mint.strip()
        if not token_mint:
            raise ValueError("token_mint cannot be empty")
        if token_mint not in self._cache:
            self._cache[token_mint] = fetch_token_decimals(self.client, token_mint)
        return self._cache[token_mint]
