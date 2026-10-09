from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib import error, parse, request

VERSION = "jupiter_token_intelligence_probe_v0"
JUPITER_SEARCH_URL = "https://api.jup.ag/tokens/v2/search"
BATCH_SIZE = 100
DEFAULT_RPS = 0.45


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def exact_mints_from_adapter(adapter_path: Path) -> tuple[str, ...]:
    mints: set[str] = set()
    for row in _jsonl(adapter_path):
        if (
            row.get("type") != "helius_standard_wss_shadow_adapter_result"
            or row.get("stage") != "matched_unit_flow"
            or row.get("status") != "ADAPTED"
        ):
            continue
        observation = row.get("observation")
        if not isinstance(observation, dict):
            continue
        mint = observation.get("token_mint")
        if isinstance(mint, str) and mint:
            mints.add(mint)
    return tuple(sorted(mints))


def _chunks(values: tuple[str, ...], size: int = BATCH_SIZE) -> Iterable[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _get_json(
    url: str,
    *,
    api_key: str | None,
    timeout_seconds: float,
) -> Any:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    req = request.Request(url, headers=headers, method="GET")
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


def probe_jupiter_token_intelligence(
    *,
    adapter_path: Path,
    output_path: Path,
    api_key: str | None = None,
    rps: float = DEFAULT_RPS,
    timeout_seconds: float = 20.0,
    get_json: Callable[..., Any] = _get_json,
) -> dict[str, Any]:
    mints = exact_mints_from_adapter(adapter_path)
    pacer = _Pacer(rps)
    output_rows: list[dict[str, Any]] = []
    returned: dict[str, dict[str, Any]] = {}
    duplicate_mints: set[str] = set()
    errors: list[dict[str, Any]] = []

    for batch_number, batch in enumerate(_chunks(mints), start=1):
        pacer.wait()
        query = parse.urlencode({"query": ",".join(batch)})
        url = f"{JUPITER_SEARCH_URL}?{query}"
        requested_wall_ns = time.time_ns()
        try:
            payload = get_json(
                url,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
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

        requested = set(batch)
        for item in payload:
            if not isinstance(item, dict):
                continue
            mint = item.get("id")
            if not isinstance(mint, str) or mint not in requested:
                continue
            if mint in returned:
                duplicate_mints.add(mint)
                continue
            returned[mint] = item
            output_rows.append(
                {
                    "type": "jupiter_token_intelligence_observation",
                    "version": VERSION,
                    "mint": mint,
                    "requested_wall_ns": requested_wall_ns,
                    "received_wall_ns": received_wall_ns,
                    "causal_for_source_shadow": False,
                    "source": "jupiter_tokens_v2_search",
                    "payload": item,
                }
            )

    _write_jsonl(output_path, output_rows)
    missing = sorted(set(mints) - set(returned))
    field_counts = {
        name: sum(1 for item in returned.values() if item.get(name) is not None)
        for name in (
            "holderCount",
            "liquidity",
            "organicScore",
            "organicScoreLabel",
            "audit",
            "firstPool",
            "stats5m",
            "stats1h",
            "stats6h",
            "stats24h",
            "dev",
            "launchpad",
            "graduatedPool",
            "usdPrice",
            "mcap",
            "fdv",
        )
    }
    valid = len(mints) > 0 and not errors and not duplicate_mints
    return {
        "type": "jupiter_token_intelligence_probe_report",
        "version": VERSION,
        "mints_requested": len(mints),
        "mints_returned_exact": len(returned),
        "missing_mints": len(missing),
        "missing_mint_examples": missing[:20],
        "duplicate_return_mints": len(duplicate_mints),
        "request_batches": (len(mints) + BATCH_SIZE - 1) // BATCH_SIZE if mints else 0,
        "request_errors": len(errors),
        "request_error_examples": errors[:10],
        "exact_mint_coverage_pct": (
            0.0 if not mints else 100.0 * len(returned) / len(mints)
        ),
        "field_coverage_counts": field_counts,
        "valid_probe": valid,
        "jupiter_api_key_used": bool(api_key),
        "causal_for_source_shadow": False,
        "chain_complete_coverage_claimed": False,
        "economic_edge_evaluated": False,
        "external_score_is_ground_truth": False,
        "notes": [
            "This is post-shadow external evidence and MUST NOT be backfilled into the source T0.",
            "Jupiter organicScore is retained as provider-native evidence, not adopted as bot truth or a trading recommendation.",
            "Exact mint identity is required; search results for names/symbols outside the requested mint set are ignored.",
            "Provider missing fields remain missing and are never imputed from native bot metrics.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Jupiter Tokens V2 as independent external token-intelligence evidence"
    )
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()

    api_key = os.environ.get("JUPITER_API_KEY") or None
    report = probe_jupiter_token_intelligence(
        adapter_path=args.adapter_output,
        output_path=args.out,
        api_key=api_key,
        rps=args.rps,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_probe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
