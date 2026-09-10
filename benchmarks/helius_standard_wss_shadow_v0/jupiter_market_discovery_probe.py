from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib import error, parse, request

VERSION = "jupiter_market_discovery_probe_v0"
BASE_URL = "https://api.jup.ag/tokens/v2"
DEFAULT_RPS = 0.45
DEFAULT_LIMIT = 100
DISCOVERY_QUERIES = (
    ("toporganicscore_5m", "toporganicscore/5m"),
    ("toptraded_5m", "toptraded/5m"),
    ("toptrending_5m", "toptrending/5m"),
    ("recent", "recent"),
)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _get_json(url: str, *, api_key: str | None, timeout_seconds: float) -> Any:
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


def probe_jupiter_market_discovery(
    *,
    output_path: Path,
    api_key: str | None = None,
    rps: float = DEFAULT_RPS,
    limit: int = DEFAULT_LIMIT,
    timeout_seconds: float = 20.0,
    get_json: Callable[..., Any] = _get_json,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    pacer = _Pacer(rps)
    output_rows: list[dict[str, Any]] = []
    category_mints: dict[str, set[str]] = {}
    errors: list[dict[str, Any]] = []

    for query_name, path in DISCOVERY_QUERIES:
        params = "" if query_name == "recent" else "?" + parse.urlencode({"limit": limit})
        url = f"{BASE_URL}/{path}{params}"
        pacer.wait()
        requested_wall_ns = time.time_ns()
        try:
            payload = get_json(url, api_key=api_key, timeout_seconds=timeout_seconds)
        except (error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append({"query": query_name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        received_wall_ns = time.time_ns()
        if not isinstance(payload, list):
            errors.append({"query": query_name, "error": "non_list_response"})
            continue

        seen: set[str] = set()
        for rank, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            mint = item.get("id")
            if not isinstance(mint, str) or not mint or mint in seen:
                continue
            seen.add(mint)
            output_rows.append(
                {
                    "type": "jupiter_market_discovery_observation",
                    "version": VERSION,
                    "query": query_name,
                    "rank": rank,
                    "mint": mint,
                    "requested_wall_ns": requested_wall_ns,
                    "received_wall_ns": received_wall_ns,
                    "source": "jupiter_tokens_v2",
                    "market_first_external_discovery_candidate": True,
                    "economic_edge_evaluated": False,
                    "payload": item,
                }
            )
        category_mints[query_name] = seen

    all_mints = set().union(*category_mints.values()) if category_mints else set()
    frequency = Counter(mint for values in category_mints.values() for mint in values)
    multi_list = sorted(mint for mint, count in frequency.items() if count >= 2)
    all_queries_succeeded = len(category_mints) == len(DISCOVERY_QUERIES) and not errors

    return {
        "type": "jupiter_market_discovery_probe_report",
        "version": VERSION,
        "queries_requested": [name for name, _ in DISCOVERY_QUERIES],
        "queries_succeeded": sorted(category_mints),
        "query_errors": len(errors),
        "query_error_examples": errors[:10],
        "results_by_query": {name: len(category_mints.get(name, set())) for name, _ in DISCOVERY_QUERIES},
        "unique_mints": len(all_mints),
        "mints_present_in_multiple_lists": len(multi_list),
        "multi_list_mint_examples": multi_list[:20],
        "valid_probe": all_queries_succeeded,
        "jupiter_api_key_used": bool(api_key),
        "market_first_external_discovery_candidate": True,
        "chain_complete_coverage_claimed": False,
        "economic_edge_evaluated": False,
        "recommendation_or_bot_score_created": False,
        "notes": [
            "The four lists are external discovery candidates, not trading recommendations.",
            "toporganicscore is a Jupiter-derived ranking and is not ground truth.",
            "recent is ordered by first-pool creation, not mint creation time.",
            "This probe records local request/receive clocks so future prospective overlap experiments can use availability time.",
            "No Social/Event-First evidence is mixed into this Market-First probe.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture Jupiter Tokens V2 Market-First discovery lists"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()

    api_key = os.environ.get("JUPITER_API_KEY") or None
    report = probe_jupiter_market_discovery(
        output_path=args.out,
        api_key=api_key,
        rps=args.rps,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_probe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
