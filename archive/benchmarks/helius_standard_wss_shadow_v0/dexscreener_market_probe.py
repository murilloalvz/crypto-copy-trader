from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib import error, parse, request

from benchmarks.helius_standard_wss_shadow_v0.jupiter_token_intelligence_probe import (
    exact_mints_from_adapter,
)

VERSION = "dexscreener_market_evidence_probe_v0"
BASE_URL = "https://api.dexscreener.com/tokens/v1/solana"
BATCH_SIZE = 30
DEFAULT_RPS = 2.0


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _chunks(values: tuple[str, ...], size: int = BATCH_SIZE) -> Iterable[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _get_json(url: str, *, timeout_seconds: float) -> Any:
    req = request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


class _Pacer:
    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be positive")
        self.interval = 1.0 / rps
        self.last_started: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self.last_started is not None:
            remaining = self.interval - (now - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()


def _token_address(token: Any) -> str | None:
    if not isinstance(token, dict):
        return None
    address = token.get("address")
    return address if isinstance(address, str) and address else None


def probe_dexscreener_market_evidence(
    *,
    adapter_path: Path,
    output_path: Path,
    rps: float = DEFAULT_RPS,
    timeout_seconds: float = 20.0,
    get_json: Callable[..., Any] = _get_json,
) -> dict[str, Any]:
    mints = exact_mints_from_adapter(adapter_path)
    pacer = _Pacer(rps)
    output_rows: list[dict[str, Any]] = []
    tokens_with_pairs: set[str] = set()
    pair_keys: set[tuple[str, str]] = set()
    duplicate_pairs = 0
    off_request_pairs = 0
    errors: list[dict[str, Any]] = []

    for batch_number, batch in enumerate(_chunks(mints), start=1):
        requested = set(batch)
        path = ",".join(parse.quote(mint, safe="") for mint in batch)
        url = f"{BASE_URL}/{path}"
        pacer.wait()
        requested_wall_ns = time.time_ns()
        try:
            payload = get_json(url, timeout_seconds=timeout_seconds)
        except (error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append(
                {
                    "batch_number": batch_number,
                    "mint_count": len(batch),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        received_wall_ns = time.time_ns()
        if not isinstance(payload, list):
            errors.append(
                {
                    "batch_number": batch_number,
                    "mint_count": len(batch),
                    "error": "non_list_response",
                }
            )
            continue

        for pair in payload:
            if not isinstance(pair, dict):
                continue
            chain_id = pair.get("chainId")
            pair_address = pair.get("pairAddress")
            base_mint = _token_address(pair.get("baseToken"))
            quote_mint = _token_address(pair.get("quoteToken"))
            matched = sorted(
                mint for mint in (base_mint, quote_mint) if mint is not None and mint in requested
            )
            if chain_id != "solana" or not matched:
                off_request_pairs += 1
                continue
            if not isinstance(pair_address, str) or not pair_address:
                off_request_pairs += 1
                continue

            key = (str(chain_id), pair_address)
            if key in pair_keys:
                duplicate_pairs += 1
                continue
            pair_keys.add(key)
            tokens_with_pairs.update(matched)
            output_rows.append(
                {
                    "type": "dexscreener_market_evidence_observation",
                    "version": VERSION,
                    "pair_address": pair_address,
                    "matched_requested_mints": matched,
                    "requested_wall_ns": requested_wall_ns,
                    "received_wall_ns": received_wall_ns,
                    "causal_for_source_shadow": False,
                    "source": "dexscreener_tokens_v1_solana",
                    "payload": pair,
                }
            )

    _write_jsonl(output_path, output_rows)
    missing = sorted(set(mints) - tokens_with_pairs)

    def covered(predicate: Callable[[dict[str, Any]], bool]) -> int:
        return sum(1 for row in output_rows if predicate(row["payload"]))

    field_coverage = {
        "liquidity_usd": covered(
            lambda p: isinstance(p.get("liquidity"), dict)
            and p["liquidity"].get("usd") is not None
        ),
        "pair_created_at": covered(lambda p: p.get("pairCreatedAt") is not None),
        "price_usd": covered(lambda p: p.get("priceUsd") is not None),
        "txns": covered(lambda p: isinstance(p.get("txns"), dict)),
        "volume": covered(lambda p: isinstance(p.get("volume"), dict)),
        "price_change": covered(lambda p: isinstance(p.get("priceChange"), dict)),
        "boosts": covered(lambda p: isinstance(p.get("boosts"), dict)),
    }

    valid = len(mints) > 0 and not errors
    return {
        "type": "dexscreener_market_evidence_probe_report",
        "version": VERSION,
        "mints_requested": len(mints),
        "mints_with_exact_pair_match": len(tokens_with_pairs),
        "missing_mints": len(missing),
        "missing_mint_examples": missing[:20],
        "pair_rows_saved": len(output_rows),
        "duplicate_pair_rows_rejected": duplicate_pairs,
        "off_request_or_invalid_pairs_rejected": off_request_pairs,
        "request_batches": (len(mints) + BATCH_SIZE - 1) // BATCH_SIZE if mints else 0,
        "request_errors": len(errors),
        "request_error_examples": errors[:10],
        "exact_mint_pair_coverage_pct": (
            0.0 if not mints else 100.0 * len(tokens_with_pairs) / len(mints)
        ),
        "pair_field_coverage_counts": field_coverage,
        "valid_probe": valid,
        "causal_for_source_shadow": False,
        "chain_complete_coverage_claimed": False,
        "economic_edge_evaluated": False,
        "provider_market_metrics_are_ground_truth": False,
        "notes": [
            "Only exact requested mint matches on Solana pairs are retained.",
            "This is post-shadow external evidence and MUST NOT be backfilled into the source T0.",
            "DEX Screener liquidity, volume, txn, price, boost and pair-age fields remain provider-native evidence.",
            "Pair-level market data is not silently merged with native matched-unit reserves or flow metrics.",
            "Paid boosts/ads are attention metadata, not evidence of organic demand or economic edge.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe DexScreener as independent exact-mint pair/market evidence"
    )
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()

    report = probe_dexscreener_market_evidence(
        adapter_path=args.adapter_output,
        output_path=args.out,
        rps=args.rps,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_probe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
