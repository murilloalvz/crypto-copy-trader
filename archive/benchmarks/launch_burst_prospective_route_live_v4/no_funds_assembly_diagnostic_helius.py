from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v4 import no_funds_assembly_diagnostic as diag


HELIUS_MAINNET_RPC_PREFIX = "https://mainnet.helius-rpc.com/?api-key="
MAX_DISCOVERY_ROWS = 25


def _helius_rpc_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY is required")
    return HELIUS_MAINNET_RPC_PREFIX + key


def _helius_call(
    rpc_url: str,
    method: str,
    params: Any,
    *,
    attempts: int = 4,
) -> Any:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(attempts):
        request = Request(
            rpc_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "crypto-copy-trader/0.3",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt + 1 < attempts:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = max(float(retry_after), 0.25) if retry_after else 0.5 * (2**attempt)
                except ValueError:
                    delay = 0.5 * (2**attempt)
                time.sleep(delay)
                continue
            raise
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
                continue
            raise

        if not isinstance(payload, dict):
            raise RuntimeError(f"Helius {method} returned a non-object payload")
        if payload.get("error") is not None:
            raise RuntimeError(f"Helius {method} error: {payload['error']}")
        return payload.get("result")

    raise RuntimeError(f"Helius {method} unavailable: {last_exc}")


def _make_discovery_rpc_adapter(rpc_url: str):
    """Adapt Helius getTokenAccounts into the narrow interface used by the diagnostic.

    Helius recommends getTokenAccounts filtered by mint for very large fungible tokens.
    We expose only a small, amount-sorted candidate set to the generic diagnostic and
    synthesize the token-account owner lookup from the same Helius response. No private
    material is read and no transaction is signed or submitted.
    """

    owner_by_token_account: dict[str, str] = {}

    def rpc_call(_ignored_url: str, method: str, params: list[Any]) -> Any:
        if method == "getTokenLargestAccounts":
            if not params:
                raise RuntimeError("mint is required for Helius token-account discovery")
            mint = str(params[0])
            result = _helius_call(
                rpc_url,
                "getTokenAccounts",
                {
                    "page": 1,
                    "limit": 1000,
                    "displayOptions": {},
                    "mint": mint,
                },
            )
            rows = result.get("token_accounts") if isinstance(result, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("Helius getTokenAccounts returned an invalid payload")

            normalized: list[dict[str, str]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                address = str(row.get("address") or "").strip()
                owner = str(row.get("owner") or "").strip()
                try:
                    amount_raw = int(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                if not address or not owner or amount_raw <= 0:
                    continue
                owner_by_token_account[address] = owner
                normalized.append({"address": address, "amount": str(amount_raw)})

            normalized.sort(key=lambda item: int(item["amount"]), reverse=True)
            return {"value": normalized[:MAX_DISCOVERY_ROWS]}

        if method == "getAccountInfo":
            if not params:
                raise RuntimeError("token account is required")
            token_account = str(params[0])
            owner = owner_by_token_account.get(token_account)
            if owner is None:
                raise RuntimeError("token account owner was not cached from getTokenAccounts")
            return {
                "value": {
                    "data": {
                        "parsed": {
                            "info": {"owner": owner}
                        }
                    }
                }
            }

        return _helius_call(rpc_url, method, params)

    return rpc_call


def main() -> int:
    parser = argparse.ArgumentParser(
        description="No-funds Launch Burst V4 assembly diagnostic using Helius token-account discovery"
    )
    parser.add_argument("--fixture", type=Path, default=diag.DEFAULT_FIXTURE)
    parser.add_argument("--contract", type=Path, default=diag.DEFAULT_CONTRACT)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file
    if env_file is None:
        candidate = Path.cwd() / ".env"
        env_file = candidate if candidate.exists() else None
    if env_file is not None and env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    helius_api_key = os.environ.get("HELIUS_API_KEY", "")
    jupiter_api_key = os.environ.get("JUPITER_API_KEY", "")
    frozen_taker = os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "")

    try:
        rpc_url = _helius_rpc_url(helius_api_key)
        report = diag.run_diagnostic(
            fixture_path=args.fixture,
            contract_path=args.contract,
            rpc_url=rpc_url,
            jupiter_api_key=jupiter_api_key,
            frozen_taker_public_key=frozen_taker,
            rpc_call=_make_discovery_rpc_adapter(rpc_url),
        )
        report["diagnostic_rpc_source"] = "helius_getTokenAccounts_mint_filtered"
    except Exception as exc:
        report = {
            "type": "launch_burst_v4_no_funds_assembly_diagnostic",
            "classification": diag.NOT_CONFIRMED,
            "diagnostic_only": True,
            "official_funded_taker_gate_passed": False,
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
            "diagnostic_rpc_source": "helius_getTokenAccounts_mint_filtered",
            "error": diag.ft._redact_error(
                exc,
                helius_api_key,
                jupiter_api_key,
            ),
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
