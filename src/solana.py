import json
import time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config import settings

LAMPORTS_PER_SOL = 1_000_000_000


class SolanaRPCError(RuntimeError):
    pass


class SolanaClient:
    def __init__(self, rpc_url: str | None = None, timeout: int = 30):
        self.rpc_url = rpc_url or settings.rpc_url
        self.timeout = timeout
        self._request_id = 0

    def call(self, method: str, params: list, max_attempts: int = 3):
        last_error = None
        for attempt in range(max_attempts):
            self._request_id += 1
            body = json.dumps(
                {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
            ).encode("utf-8")
            request = Request(
                self.rpc_url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "solana-copytrader-mvp/0.1"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < max_attempts:
                    time.sleep(2 ** attempt)
        else:
            raise SolanaRPCError(f"RPC indisponível após {max_attempts} tentativas: {last_error}") from last_error
        if payload.get("error"):
            raise SolanaRPCError(payload["error"].get("message", str(payload["error"])))
        return payload.get("result")

    def signatures(self, address: str, limit: int) -> list[dict]:
        return self.call("getSignaturesForAddress", [address, {"limit": limit}]) or []

    def transaction(self, signature: str) -> dict | None:
        return self.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )


def _account_keys(message: dict) -> list[str]:
    keys = []
    for item in message.get("accountKeys", []):
        keys.append(item.get("pubkey") if isinstance(item, dict) else item)
    return keys


def parse_wallet_transaction(wallet: str, signature: str, tx: dict) -> dict:
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    keys = _account_keys(message)
    wallet_index = keys.index(wallet) if wallet in keys else None
    pre_balances = meta.get("preBalances") or []
    post_balances = meta.get("postBalances") or []
    sol_change = 0.0
    if wallet_index is not None and wallet_index < len(pre_balances) and wallet_index < len(post_balances):
        sol_change = (post_balances[wallet_index] - pre_balances[wallet_index]) / LAMPORTS_PER_SOL

    before = defaultdict(float)
    after = defaultdict(float)
    for entry in meta.get("preTokenBalances") or []:
        if entry.get("owner") == wallet:
            before[entry.get("mint")] += float(entry.get("uiTokenAmount", {}).get("uiAmount") or 0)
    for entry in meta.get("postTokenBalances") or []:
        if entry.get("owner") == wallet:
            after[entry.get("mint")] += float(entry.get("uiTokenAmount", {}).get("uiAmount") or 0)

    changes = {mint: after[mint] - before[mint] for mint in before.keys() | after.keys()}
    changes = {mint: value for mint, value in changes.items() if abs(value) > 1e-12}
    token_mint, token_change = (max(changes.items(), key=lambda item: abs(item[1])) if changes else (None, None))

    if token_change is not None and abs(sol_change) > 0.000005:
        kind = "swap"
    elif token_change is not None:
        kind = "token_transfer"
    elif abs(sol_change) > 0.000005:
        kind = "sol_transfer"
    else:
        kind = "other"

    return {
        "signature": signature,
        "block_time": tx.get("blockTime"),
        "status": "failed" if meta.get("err") else "success",
        "kind": kind,
        "sol_change": sol_change,
        "fee_sol": float(meta.get("fee") or 0) / LAMPORTS_PER_SOL,
        "token_mint": token_mint,
        "token_change": token_change,
        "raw_json": json.dumps(tx, separators=(",", ":")),
    }
