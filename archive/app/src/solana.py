import json
import ssl
import time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from src.assets import QUOTE_ASSET_MINTS, STABLECOIN_MINTS, WRAPPED_SOL_MINT
from src.config import settings

LAMPORTS_PER_SOL = 1_000_000_000
SOL_CHANGE_EPSILON = 0.000005
CURRENT_MAINNET_RPC_URL = "https://api.mainnet.solana.com"
LEGACY_MAINNET_RPC_URLS = {
    "https://api.mainnet-beta.solana.com",
}

# Program IDs are treated as evidence that a DEX/aggregator was actually invoked.
# Balance deltas alone are not enough: exchange and custody wallets commonly move
# several assets in one transaction without executing a swap.
DEX_PROGRAM_LABELS = {
    # Jupiter v4, v5, v5.1 and v6.
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": "Jupiter v4",
    "JUP5pEAZeHdHrLxh5UCwAbpjGwYKKoquCpda2hfP4u8": "Jupiter v5",
    "JUP5cHjnnCx2DppVsufsLrXs8EBZeEZzGtEK9Gdz6ow": "Jupiter v5.1",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter v6",
    # Pump bonding curve and PumpSwap AMM.
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "Pump.fun",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "PumpSwap",
    # Raydium mainnet AMMs.
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM v4",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "Raydium CPMM",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h": "Raydium Stable AMM",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "Raydium LaunchLab",
    "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS": "Raydium Router",
    # Orca concentrated-liquidity pools.
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    # Meteora current and legacy swap surfaces.
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB": "Meteora DAMM v1",
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG": "Meteora DAMM v2",
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN": "Meteora DBC",
}

INFRASTRUCTURE_PROGRAM_IDS = {
    "11111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "AddressLookupTab1e1111111111111111111111111",
    "BPFLoaderUpgradeab1e11111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
    "Ed25519SigVerify111111111111111111111111111",
    "KeccakSecp256k11111111111111111111111111111",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "noopb9bkMVfRPU8AsbpTUg8AQkHtKwMYZiFUjNRtMmV",
}

DEX_LABEL_PRIORITY = (
    "Jupiter v6",
    "Jupiter v5.1",
    "Jupiter v5",
    "Jupiter v4",
    "PumpSwap",
    "Pump.fun",
    "Raydium CPMM",
    "Raydium CLMM",
    "Raydium AMM v4",
    "Raydium Stable AMM",
    "Raydium LaunchLab",
    "Raydium Router",
    "Orca Whirlpool",
    "Meteora DLMM",
    "Meteora DAMM v2",
    "Meteora DAMM v1",
    "Meteora DBC",
)


class SolanaRPCError(RuntimeError):
    pass


def normalize_rpc_url(rpc_url: str) -> str:
    """Map retired public endpoints while preserving custom/private RPC URLs."""
    normalized = rpc_url.strip().rstrip("/")
    if normalized in LEGACY_MAINNET_RPC_URLS:
        return CURRENT_MAINNET_RPC_URL
    return normalized


def _tls12_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


def _is_ssl_error(error: BaseException) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(error, ssl.SSLError) or isinstance(reason, ssl.SSLError)


class SolanaClient:
    def __init__(
        self,
        rpc_url: str | None = None,
        timeout: int = 30,
        fallback_urls: tuple[str, ...] | list[str] | None = None,
    ):
        configured_urls = [rpc_url or settings.rpc_url]
        configured_urls.extend(
            settings.rpc_fallback_urls if fallback_urls is None else fallback_urls
        )
        self.rpc_urls = []
        for item in configured_urls:
            normalized = normalize_rpc_url(item)
            if normalized and normalized not in self.rpc_urls:
                self.rpc_urls.append(normalized)
        self.rpc_url = self.rpc_urls[0]
        self.timeout = timeout
        self._request_id = 0

    @property
    def rpc_host(self) -> str:
        return urlsplit(self.rpc_url).hostname or self.rpc_url

    def _read_payload(
        self, request: Request, context: ssl.SSLContext | None = None
    ) -> dict:
        options = {"timeout": self.timeout}
        if context is not None:
            options["context"] = context
        with urlopen(request, **options) as response:
            return json.loads(response.read().decode("utf-8"))

    def call(self, method: str, params: list, max_attempts: int = 2):
        errors = []
        candidates = [self.rpc_url] + [
            item for item in self.rpc_urls if item != self.rpc_url
        ]
        for rpc_url in candidates:
            last_error = None
            for attempt in range(max_attempts):
                self._request_id += 1
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": self._request_id,
                        "method": method,
                        "params": params,
                    }
                ).encode("utf-8")
                request = Request(
                    rpc_url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "solana-copytrader-mvp/0.1",
                    },
                    method="POST",
                )
                try:
                    payload = self._read_payload(request)
                except (HTTPError, URLError, TimeoutError, ssl.SSLError) as exc:
                    last_error = exc
                    if _is_ssl_error(exc):
                        try:
                            payload = self._read_payload(request, _tls12_context())
                        except (HTTPError, URLError, TimeoutError, ssl.SSLError) as tls_exc:
                            last_error = tls_exc
                        else:
                            self.rpc_url = rpc_url
                            if payload.get("error"):
                                raise SolanaRPCError(
                                    payload["error"].get("message", str(payload["error"]))
                                )
                            return payload.get("result")
                    if attempt + 1 < max_attempts:
                        time.sleep(2 ** attempt)
                    continue

                self.rpc_url = rpc_url
                if payload.get("error"):
                    raise SolanaRPCError(
                        payload["error"].get("message", str(payload["error"]))
                    )
                return payload.get("result")

            host = urlsplit(rpc_url).hostname or rpc_url
            errors.append(f"{host}: {last_error}")

        raise SolanaRPCError("Todos os RPCs falharam: " + " | ".join(errors))

    def signatures(self, address: str, limit: int, before: str | None = None) -> list[dict]:
        options = {"limit": limit}
        if before:
            options["before"] = before
        return self.call("getSignaturesForAddress", [address, options]) or []

    def transaction(self, signature: str) -> dict | None:
        return self.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )


def _account_keys(message: dict, meta: dict | None = None) -> list[str]:
    keys = []
    for item in message.get("accountKeys", []):
        key = item.get("pubkey") if isinstance(item, dict) else item
        if key:
            keys.append(key)

    # Compiled v0 instructions can index addresses loaded from lookup tables.
    loaded = (meta or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or loaded.get("readOnly") or [])
    return keys


def _instruction_program_id(instruction: dict, account_keys: list[str]) -> str | None:
    program_id = instruction.get("programId")
    if isinstance(program_id, dict):
        program_id = program_id.get("pubkey")
    if isinstance(program_id, str):
        return program_id

    index = instruction.get("programIdIndex")
    if isinstance(index, int) and 0 <= index < len(account_keys):
        return account_keys[index]
    return None


def _invoked_program_ids(tx: dict, account_keys: list[str]) -> set[str]:
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    instructions = list(message.get("instructions") or [])
    for group in meta.get("innerInstructions") or []:
        instructions.extend(group.get("instructions") or [])

    program_ids = {
        program_id
        for instruction in instructions
        if isinstance(instruction, dict)
        for program_id in [_instruction_program_id(instruction, account_keys)]
        if program_id
    }

    # Logs provide a useful fallback when an RPC omits parsed inner instructions.
    for log in meta.get("logMessages") or []:
        if not isinstance(log, str) or not log.startswith("Program "):
            continue
        parts = log.split()
        if len(parts) >= 3 and parts[2] == "invoke":
            program_ids.add(parts[1])
    return program_ids


def _detected_dex(program_ids: set[str]) -> str | None:
    labels = {DEX_PROGRAM_LABELS[item] for item in program_ids if item in DEX_PROGRAM_LABELS}
    return next((label for label in DEX_LABEL_PRIORITY if label in labels), None)


def transaction_program_ids(tx: dict) -> set[str]:
    """Return every program invoked by a parsed RPC transaction."""
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    return _invoked_program_ids(tx, _account_keys(message, meta))


def _ui_token_amount(entry: dict) -> float:
    amount = entry.get("uiTokenAmount") or {}
    value = amount.get("uiAmountString")
    if value is None:
        value = amount.get("uiAmount")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _wallet_token_changes(meta: dict, wallet: str) -> dict[str, float]:
    before = defaultdict(float)
    after = defaultdict(float)
    for entry in meta.get("preTokenBalances") or []:
        if entry.get("owner") == wallet and entry.get("mint"):
            before[entry["mint"]] += _ui_token_amount(entry)
    for entry in meta.get("postTokenBalances") or []:
        if entry.get("owner") == wallet and entry.get("mint"):
            after[entry["mint"]] += _ui_token_amount(entry)

    changes = {mint: after[mint] - before[mint] for mint in before.keys() | after.keys()}
    return {mint: value for mint, value in changes.items() if abs(value) > 1e-12}


def _wallet_token_balance_details(meta: dict, wallet: str) -> dict[str, dict[str, int | None]]:
    """Aggregate exact raw token balances across all wallet token accounts."""
    before: dict[str, int] = defaultdict(int)
    after: dict[str, int] = defaultdict(int)
    decimals: dict[str, int] = {}
    for collection, target in ((meta.get("preTokenBalances") or [], before), (meta.get("postTokenBalances") or [], after)):
        for entry in collection:
            if entry.get("owner") != wallet or not entry.get("mint"):
                continue
            amount = (entry.get("uiTokenAmount") or {}).get("amount")
            if amount is None:
                continue
            target[str(entry["mint"])] += int(amount)
            raw_decimals = (entry.get("uiTokenAmount") or {}).get("decimals")
            if raw_decimals is not None:
                decimals[str(entry["mint"])] = int(raw_decimals)
    return {
        mint: {
            "before_raw": before.get(mint, 0),
            "after_raw": after.get(mint, 0),
            "delta_raw": after.get(mint, 0) - before.get(mint, 0),
            "decimals": decimals.get(mint),
        }
        for mint in before.keys() | after.keys()
    }


def describe_source_quantity(side: str, before_raw: int | None, after_raw: int | None, delta_raw: int | None, *, forward_buy_raw: int = 0) -> tuple[float | None, tuple[str, ...]]:
    """Return descriptive source reduction metadata; never infers a copy fill."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if None in (before_raw, after_raw, delta_raw):
        return None, ("SOURCE_QUANTITY_UNKNOWN",)
    mismatch = (side == "buy" and delta_raw <= 0) or (side == "sell" and delta_raw >= 0)
    if mismatch:
        return None, ("SIDE_DELTA_MISMATCH",)
    if side != "sell" or before_raw <= 0 or delta_raw >= 0:
        return None, ()
    fraction = abs(delta_raw) / before_raw
    flags = ("PREEXISTING_INVENTORY_OBSERVED",) if before_raw > forward_buy_raw else ()
    if fraction >= 1:
        return fraction, flags + ("SOURCE_COMPLETE_LIKE_REDUCTION",)
    return fraction, flags + ("SOURCE_PARTIAL_REDUCTION",)


def _opposite_directions(first: float, second: float) -> bool:
    return (first > 0 > second) or (first < 0 < second)


def _swap_asset(
    changes: dict[str, float], economic_sol_change: float
) -> tuple[str, float] | None:
    """Return the asset copied by paper trading only for a trade-shaped balance flow."""
    non_quote = [(mint, value) for mint, value in changes.items() if mint not in QUOTE_ASSET_MINTS]
    quote_values = [value for mint, value in changes.items() if mint in QUOTE_ASSET_MINTS]
    if abs(economic_sol_change) > SOL_CHANGE_EPSILON:
        quote_values.append(economic_sol_change)

    # Most swaps are one non-quote token against SOL, WSOL, USDC or USDT.
    if len(non_quote) == 1:
        mint, value = non_quote[0]
        if any(_opposite_directions(value, quote) for quote in quote_values):
            return mint, value

    # Routers can leave more than one non-quote balance delta. Accept the flow
    # only when exactly one asset moves against the net quote direction.
    if quote_values and len(non_quote) > 1:
        directional = [
            item
            for item in non_quote
            if any(_opposite_directions(item[1], quote) for quote in quote_values)
        ]
        if len(directional) == 1:
            return directional[0]

    # For a token-to-token route without a quote asset, copy the received token.
    if len(non_quote) >= 2 and not quote_values:
        received = [item for item in non_quote if item[1] > 0]
        spent = [item for item in non_quote if item[1] < 0]
        if len(received) == 1 and spent:
            return received[0]

    # SOL/USDC and SOL/USDT swaps have no non-quote SPL token. Represent native
    # SOL using the canonical wrapped-SOL mint and preserve the true direction.
    stable_values = [
        value for mint, value in changes.items() if mint in STABLECOIN_MINTS
    ]
    wrapped_sol_change = changes.get(WRAPPED_SOL_MINT)
    if wrapped_sol_change is not None and any(
        _opposite_directions(wrapped_sol_change, value) for value in stable_values
    ):
        return WRAPPED_SOL_MINT, wrapped_sol_change
    if abs(economic_sol_change) > SOL_CHANGE_EPSILON and any(
        _opposite_directions(economic_sol_change, value) for value in stable_values
    ):
        return WRAPPED_SOL_MINT, economic_sol_change
    return None


def _display_token(changes: dict[str, float]) -> tuple[str | None, float | None]:
    non_quote = {
        mint: value for mint, value in changes.items() if mint not in QUOTE_ASSET_MINTS
    }
    selected = non_quote or changes
    return max(selected.items(), key=lambda item: abs(item[1])) if selected else (None, None)


def parse_wallet_transaction(wallet: str, signature: str, tx: dict) -> dict:
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    keys = _account_keys(message, meta)
    wallet_index = keys.index(wallet) if wallet in keys else None
    pre_balances = meta.get("preBalances") or []
    post_balances = meta.get("postBalances") or []
    sol_change = 0.0
    if (
        wallet_index is not None
        and wallet_index < len(pre_balances)
        and wallet_index < len(post_balances)
    ):
        sol_change = (post_balances[wallet_index] - pre_balances[wallet_index]) / LAMPORTS_PER_SOL

    fee_sol = float(meta.get("fee") or 0) / LAMPORTS_PER_SOL
    wallet_is_fee_payer = wallet_index == 0
    economic_sol_change = sol_change + fee_sol if wallet_is_fee_payer else sol_change
    changes = _wallet_token_changes(meta, wallet)
    balance_details = _wallet_token_balance_details(meta, wallet)
    token_mint, token_change = _display_token(changes)
    quantity_fraction, quantity_flags = (
        describe_source_quantity(
            "sell" if (token_change or 0) < 0 else "buy",
            int(balance_details[token_mint]["before_raw"]) if token_mint in balance_details else None,
            int(balance_details[token_mint]["after_raw"]) if token_mint in balance_details else None,
            int(balance_details[token_mint]["delta_raw"]) if token_mint in balance_details else None,
        ) if token_mint is not None else (None, ("SOURCE_QUANTITY_UNKNOWN",))
    )

    program_ids = transaction_program_ids(tx)
    dex = _detected_dex(program_ids)
    swap_asset = _swap_asset(changes, economic_sol_change) if dex else None
    if swap_asset:
        kind = "swap"
        token_mint, token_change = swap_asset
    elif dex:
        kind = "dex_activity"
    elif token_change is not None:
        kind = "token_transfer"
    elif abs(economic_sol_change) > SOL_CHANGE_EPSILON:
        kind = "sol_transfer"
    else:
        kind = "other"

    return {
        "signature": signature,
        "block_time": tx.get("blockTime"),
        "status": "failed" if meta.get("err") else "success",
        "kind": kind,
        "dex": dex,
        "sol_change": sol_change,
        "fee_sol": fee_sol,
        "token_mint": token_mint,
        "token_change": token_change,
        "token_delta_raw": (
            str(balance_details[token_mint]["delta_raw"])
            if token_mint in balance_details else None
        ),
        "token_decimals": (
            balance_details[token_mint]["decimals"] if token_mint in balance_details else None
        ),
        "token_balance_before_raw": (
            str(balance_details[token_mint]["before_raw"])
            if token_mint in balance_details else None
        ),
        "token_balance_after_raw": (
            str(balance_details[token_mint]["after_raw"])
            if token_mint in balance_details else None
        ),
        "source_reduction_fraction": quantity_fraction,
        "token_quantity_flags": ",".join(quantity_flags),
        "raw_json": json.dumps(tx, separators=(",", ":")),
    }
