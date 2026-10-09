from __future__ import annotations

import argparse
from collections import OrderedDict
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib import error, parse, request

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TRACE_VERSION = "free_historical_raw_transaction_trace_v2"


class RpcError(RuntimeError):
    pass


@dataclass
class Counters:
    signature_rpc_calls: int = 0
    transaction_rpc_calls: int = 0
    rpc_errors: int = 0
    missing_transactions: int = 0
    write_errors: int = 0
    candidate_signatures: int = 0
    duplicate_candidates: int = 0
    hydrated_records: int = 0
    pump_records: int = 0
    pumpswap_records: int = 0

    @property
    def estimated_standard_rpc_credits(self) -> int:
        return self.signature_rpc_calls + self.transaction_rpc_calls


class FixedRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._next_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_at:
            time.sleep(self._next_at - now)
            now = time.monotonic()
        self._next_at = max(now, self._next_at) + self._interval


def helius_rpc_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY cannot be blank")
    return "https://mainnet.helius-rpc.com/?api-key=" + parse.quote(key, safe="")


def _rpc_call(
    *,
    rpc_url: str,
    method: str,
    params: list[Any],
    limiter: FixedRateLimiter,
    timeout_seconds: float,
    max_attempts: int,
) -> Any:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        limiter.wait()
        req = request.Request(
            rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                body = response.read()
            decoded = json.loads(body)
            if "error" in decoded:
                raise RpcError(f"RPC {method} error: {decoded['error']}")
            return decoded.get("result")
        except error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < max_attempts:
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else float(attempt)
                except ValueError:
                    delay = float(attempt)
                time.sleep(max(0.25, delay))
                continue
            raise RpcError(f"HTTP {exc.code} during {method}") from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(float(attempt))
                continue
            raise RpcError(f"transport/decode failure during {method}: {exc}") from exc

    raise RpcError(f"RPC {method} failed: {last_error}")


def _collect_signatures(
    *,
    rpc_url: str,
    program_id: str,
    venue: str,
    desired_candidates: int,
    max_pages: int,
    limiter: FixedRateLimiter,
    counters: Counters,
    timeout_seconds: float,
    max_attempts: int,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    before: str | None = None

    for _ in range(max_pages):
        if len(collected) >= desired_candidates:
            break
        config: dict[str, Any] = {
            "limit": min(1000, max(1, desired_candidates - len(collected))),
            "commitment": "confirmed",
        }
        if before:
            config["before"] = before

        counters.signature_rpc_calls += 1
        rows = _rpc_call(
            rpc_url=rpc_url,
            method="getSignaturesForAddress",
            params=[program_id, config],
            limiter=limiter,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        if not rows:
            break

        for row in rows:
            signature = row.get("signature")
            if not signature or row.get("err") is not None:
                continue
            collected.append(
                {
                    "signature": signature,
                    "slot": row.get("slot"),
                    "block_time": row.get("blockTime"),
                    "venue": venue,
                }
            )
            if len(collected) >= desired_candidates:
                break

        before = rows[-1].get("signature")
        if not before or len(rows) < config["limit"]:
            break

    return collected


def collect(
    *,
    api_key: str,
    out_path: Path,
    per_venue: int,
    reserve_fraction: float,
    requests_per_second: float,
    max_signature_pages: int,
    timeout_seconds: float,
    max_attempts: int,
) -> dict[str, Any]:
    if per_venue <= 0:
        raise ValueError("per_venue must be positive")
    if reserve_fraction < 0:
        raise ValueError("reserve_fraction cannot be negative")
    if max_signature_pages <= 0:
        raise ValueError("max_signature_pages must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    rpc_url = helius_rpc_url(api_key)
    limiter = FixedRateLimiter(requests_per_second)
    counters = Counters()
    started_wall_ns = time.time_ns()

    desired_candidates = max(per_venue, int(per_venue * (1.0 + reserve_fraction) + 0.999))

    try:
        pump = _collect_signatures(
            rpc_url=rpc_url,
            program_id=PUMP_PROGRAM_ID,
            venue="pump",
            desired_candidates=desired_candidates,
            max_pages=max_signature_pages,
            limiter=limiter,
            counters=counters,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        pumpswap = _collect_signatures(
            rpc_url=rpc_url,
            program_id=PUMPSWAP_PROGRAM_ID,
            venue="pumpswap",
            desired_candidates=desired_candidates,
            max_pages=max_signature_pages,
            limiter=limiter,
            counters=counters,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    except RpcError:
        counters.rpc_errors += 1
        raise

    candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row in pump + pumpswap:
        sig = row["signature"]
        existing = candidates.get(sig)
        if existing is None:
            candidates[sig] = {
                "signature": sig,
                "venues": {row["venue"]},
                "slot": row["slot"],
                "block_time": row["block_time"],
            }
        else:
            counters.duplicate_candidates += 1
            existing["venues"].add(row["venue"])
    counters.candidate_signatures = len(candidates)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as handle:
        header = {
            "type": "trace_header",
            "version": TRACE_VERSION,
            "source": "helius_free_standard_rpc_historical",
            "per_venue_target": per_venue,
            "requests_per_second": requests_per_second,
            "programs": {"pump": PUMP_PROGRAM_ID, "pumpswap": PUMPSWAP_PROGRAM_ID},
            "started_wall_ns": started_wall_ns,
        }
        handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")

        for item in candidates.values():
            if counters.pump_records >= per_venue and counters.pumpswap_records >= per_venue:
                break
            venues = item["venues"]
            if all(
                (venue == "pump" and counters.pump_records >= per_venue)
                or (venue == "pumpswap" and counters.pumpswap_records >= per_venue)
                for venue in venues
            ):
                continue

            counters.transaction_rpc_calls += 1
            try:
                result = _rpc_call(
                    rpc_url=rpc_url,
                    method="getTransaction",
                    params=[
                        item["signature"],
                        {
                            "encoding": "json",
                            "commitment": "confirmed",
                            "maxSupportedTransactionVersion": 0,
                        },
                    ],
                    limiter=limiter,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_attempts,
                )
            except RpcError:
                counters.rpc_errors += 1
                raise

            if result is None:
                counters.missing_transactions += 1
                continue

            accepted_venues: list[str] = []
            if "pump" in venues and counters.pump_records < per_venue:
                counters.pump_records += 1
                accepted_venues.append("pump")
            if "pumpswap" in venues and counters.pumpswap_records < per_venue:
                counters.pumpswap_records += 1
                accepted_venues.append("pumpswap")
            if not accepted_venues:
                continue

            record = {
                "type": "raw_transaction",
                "version": TRACE_VERSION,
                "signature": item["signature"],
                "venues": accepted_venues,
                "signature_slot": item["slot"],
                "signature_block_time": item["block_time"],
                "retrieved_wall_ns": time.time_ns(),
                "result": result,
            }
            try:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            except OSError:
                counters.write_errors += 1
                raise
            counters.hydrated_records += 1

            if counters.hydrated_records % 100 == 0:
                handle.flush()

        finished_wall_ns = time.time_ns()
        footer = {
            "type": "trace_footer",
            "version": TRACE_VERSION,
            "started_wall_ns": started_wall_ns,
            "finished_wall_ns": finished_wall_ns,
            "elapsed_seconds": (finished_wall_ns - started_wall_ns) / 1_000_000_000,
            "per_venue_target": per_venue,
            "counters": {
                **asdict(counters),
                "estimated_standard_rpc_credits": counters.estimated_standard_rpc_credits,
            },
            "valid_for_decoder_parity": (
                counters.pump_records >= per_venue
                and counters.pumpswap_records >= per_venue
                and counters.rpc_errors == 0
                and counters.write_errors == 0
            ),
        }
        handle.write(json.dumps(footer, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()

    return footer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a bounded Pump/PumpSwap raw transaction corpus using Helius Free "
            "standard historical RPCs. This is offline research, not live acquisition."
        )
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--per-venue", type=int, default=250)
    parser.add_argument("--reserve-fraction", type=float, default=0.10)
    parser.add_argument("--rps", type=float, default=5.0)
    parser.add_argument("--max-signature-pages", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser


def main() -> int:
    args = _parser().parse_args()
    api_key = os.getenv("HELIUS_API_KEY", "").strip()
    if not api_key:
        print("Missing HELIUS_API_KEY. Keep the key in the environment only.", file=sys.stderr)
        return 2

    try:
        footer = collect(
            api_key=api_key,
            out_path=args.out,
            per_venue=args.per_venue,
            reserve_fraction=args.reserve_fraction,
            requests_per_second=args.rps,
            max_signature_pages=args.max_signature_pages,
            timeout_seconds=args.timeout_seconds,
            max_attempts=args.max_attempts,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(footer, indent=2, sort_keys=True))
    return 0 if footer["valid_for_decoder_parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
