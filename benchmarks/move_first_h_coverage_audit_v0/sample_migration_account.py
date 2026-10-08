"""Pendencia 3(c)/3-extra (MOVE-FIRST-H-DISC-V0): stratified, time-spread sample of the
pump.fun migration-authority account's transaction history.

Read-only. Never reads a price, a return, or any economic outcome -- only instruction names,
log messages and account roles, to characterize what this account's transactions actually do
(MigrateV2 vs other instruction names, whether InitBoost-shaped sub-instructions appear) across
calendar time. Needs SOLANA_RPC_URL (already configured in .env for this repo).

Does not open a PRE-REGISTRADA line and does not spend an attempt (registry rule 5).
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

VERSION = "move_first_h_migration_account_sample_v0"
MIGRATION_AUTHORITY = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
BONDING_CURVE_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"


def _load_rpc_url() -> str:
    match = re.search(r"^SOLANA_RPC_URL=(.*)$", open(".env").read(), re.MULTILINE)
    if not match or not match.group(1).strip():
        raise RuntimeError("SOLANA_RPC_URL not configured in .env")
    return match.group(1).strip()


def _rpc(rpc_url: str, method: str, params: list, *, retries: int = 3) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def walk_signatures(
    rpc_url: str, *, max_pages: int, page_size: int = 1000, until_block_time: int | None = None
) -> list[dict]:
    """Walk getSignaturesForAddress backward in time. Returns [{signature, blockTime}].

    Stops early once a page's oldest signature is at or before `until_block_time`, so callers
    don't have to guess max_pages for a target calendar depth.
    """
    all_sigs: list[dict] = []
    before = None
    for _ in range(max_pages):
        params: list = [MIGRATION_AUTHORITY, {"limit": page_size}]
        if before is not None:
            params[1]["before"] = before
        result = _rpc(rpc_url, "getSignaturesForAddress", params)
        page = result.get("result") or []
        if not page:
            break
        all_sigs.extend(page)
        before = page[-1]["signature"]
        oldest_block_time = page[-1].get("blockTime")
        if len(page) < page_size:
            break
        if until_block_time is not None and oldest_block_time is not None and oldest_block_time <= until_block_time:
            break
    return all_sigs


def _period_bucket(block_time: int) -> str:
    dt = datetime.fromtimestamp(block_time, tz=timezone.utc)
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{quarter}"


def stratified_sample(signatures: list[dict], *, per_bucket: int) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for item in signatures:
        bt = item.get("blockTime")
        if bt is None:
            continue
        buckets[_period_bucket(bt)].append(item["signature"])
    return {period: sigs[:per_bucket] for period, sigs in sorted(buckets.items())}


@dataclass
class TxClassification:
    signature: str
    period: str
    instruction: str  # e.g. MigrateV2, MigrateV1, unknown
    completed_create_pool: bool
    has_boost_shaped_subinstructions: bool
    pool_mint: str | None
    touches_pumpfun: bool = True


@dataclass
class SampleReport:
    classifications: list[TxClassification] = field(default_factory=list)

    def by_period_instruction_counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in self.classifications:
            out[item.period][item.instruction] += 1
        return {period: dict(counts) for period, counts in out.items()}

    def distinct_pools_by_period(self) -> dict[str, int]:
        pools_by_period: dict[str, set[str]] = defaultdict(set)
        for item in self.classifications:
            if item.pool_mint:
                pools_by_period[item.period].add(item.pool_mint)
        return {period: len(pools) for period, pools in sorted(pools_by_period.items())}


def _extract_instruction_name(log_messages: list[str] | None) -> str:
    for line in log_messages or []:
        if line.startswith("Program log: Instruction: "):
            return line[len("Program log: Instruction: ") :].strip()
    return "unknown"


def _extract_pool_mint(message: dict) -> str | None:
    for key in message.get("accountKeys", []):
        pubkey = key["pubkey"] if isinstance(key, dict) else key
        if isinstance(pubkey, str) and pubkey.endswith("pump"):
            return pubkey
    return None


def _touches_pumpfun_programs(message: dict) -> bool:
    """True if the transaction's account list includes the bonding-curve or PumpSwap program.

    Needed because the migration-authority account is also touched by unrelated third-party
    programs (confirmed live: a failed transaction from program PEPPER3dYQpY2TTqHp3XinzRu519X7GswmVNb5tqK8L
    with no connection to pump.fun) -- "any tx mentioning this account" is not a clean migration
    signal on its own.
    """
    keys = {
        (key["pubkey"] if isinstance(key, dict) else key) for key in message.get("accountKeys", [])
    }
    return BONDING_CURVE_PROGRAM in keys or PUMPSWAP_PROGRAM in keys


def classify_transaction(rpc_url: str, signature: str, period: str) -> TxClassification | None:
    result = _rpc(
        rpc_url,
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )
    tx = result.get("result")
    if tx is None:
        return None
    logs = tx.get("meta", {}).get("logMessages", [])
    instruction = _extract_instruction_name(logs)
    completed_create_pool = any("Instruction: CreatePool" in line for line in logs)
    has_boost = any("Instruction: InitBoost" in line for line in logs) or any(
        "InitBoost" in line for line in logs
    )
    pool_mint = _extract_pool_mint(tx["transaction"]["message"])
    return TxClassification(
        signature=signature,
        period=period,
        instruction=instruction,
        completed_create_pool=completed_create_pool,
        has_boost_shaped_subinstructions=has_boost,
        pool_mint=pool_mint,
    )


def fetch_day_classified(rpc_url: str, *, day: str) -> list[TxClassification]:
    """Fetch and classify every transaction for the migration authority on one UTC calendar day.

    Uses Helius's getTransactionsForAddress with a blockTime filter -- jumps directly to the
    target day instead of walking signatures back from now, and returns full parsed transactions
    (logs included) in the same call, so no second getTransaction round-trip per signature is
    needed. filters.status is NOT used: "already migrated" no-op retries have err=null (verified
    live), so a succeeded-only filter would not exclude them -- classification still has to look
    at the actual instruction/log content.
    """
    start_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = int(start_dt.timestamp())
    end = int((start_dt.replace(hour=23, minute=59, second=59)).timestamp()) + 1
    period = _period_bucket(start)

    results: list[TxClassification] = []
    pagination_token: str | None = None
    while True:
        params: dict = {
            "limit": 1000,
            "sortOrder": "asc",
            "transactionDetails": "full",
            "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1,
            "filters": {"blockTime": {"gte": start, "lt": end}},
        }
        if pagination_token is not None:
            params["paginationToken"] = pagination_token
        result = _rpc(rpc_url, "getTransactionsForAddress", [MIGRATION_AUTHORITY, params])
        payload = result.get("result") or {}
        rows = payload.get("data") or []
        for row in rows:
            logs = row.get("meta", {}).get("logMessages") or []
            instruction = _extract_instruction_name(logs)
            completed_create_pool = any("Instruction: CreatePool" in line for line in logs)
            has_boost = any("InitBoost" in line for line in logs)
            pool_mint = _extract_pool_mint(row["transaction"]["message"])
            touches_pumpfun = _touches_pumpfun_programs(row["transaction"]["message"])
            results.append(
                TxClassification(
                    signature=row["transaction"]["signatures"][0],
                    period=period,
                    instruction=instruction,
                    completed_create_pool=completed_create_pool,
                    has_boost_shaped_subinstructions=has_boost,
                    pool_mint=pool_mint,
                    touches_pumpfun=touches_pumpfun,
                )
            )
        pagination_token = payload.get("paginationToken")
        if not pagination_token or not rows:
            break
    return results


def run_sample(
    *, max_pages: int, per_bucket: int, until_block_time: int | None = None, rpc_url: str | None = None
) -> SampleReport:
    rpc_url = rpc_url or _load_rpc_url()
    signatures = walk_signatures(rpc_url, max_pages=max_pages, until_block_time=until_block_time)
    buckets = stratified_sample(signatures, per_bucket=per_bucket)
    report = SampleReport()
    for period, sigs in buckets.items():
        for sig in sigs:
            classification = classify_transaction(rpc_url, sig, period)
            if classification is not None:
                report.classifications.append(classification)
    return report


def enumerate_date_range(
    rpc_url: str, *, start_date: str, end_date: str, output_path: str
) -> None:
    """Day-by-day enumeration via getTransactionsForAddress (blockTime filter), not a signature
    walk. Writes one JSON line per day to output_path as it goes, so partial progress survives
    an interruption. Only rows that touch the bonding-curve or PumpSwap program are kept.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day = start
    with open(output_path, "a") as handle:
        while day <= end:
            day_str = day.strftime("%Y-%m-%d")
            rows = [r for r in fetch_day_classified(rpc_url, day=day_str) if r.touches_pumpfun]
            completed = [r for r in rows if r.completed_create_pool]
            distinct_pools = sorted({r.pool_mint for r in completed if r.pool_mint})
            instruction_counts: dict[str, int] = defaultdict(int)
            for r in rows:
                instruction_counts[r.instruction] += 1
            record = {
                "day": day_str,
                "total_tx_touching_pumpfun": len(rows),
                "instruction_counts": dict(instruction_counts),
                "completed_create_pool": len(completed),
                "distinct_pools": distinct_pools,
            }
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            print(day_str, "total=", len(rows), "completed=", len(completed), "pools=", len(distinct_pools), flush=True)
            day += __import__("datetime").timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=2000, help="pages of 1000 signatures to walk backward")
    parser.add_argument("--per-bucket", type=int, default=5, help="transactions sampled per calendar quarter")
    parser.add_argument(
        "--until-date",
        default="2025-03-01",
        help="stop walking back once signatures are at or before this UTC date (YYYY-MM-DD)",
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--enumerate-from",
        help="day-by-day enumeration (getTransactionsForAddress, not a signature walk) from this date",
    )
    parser.add_argument("--enumerate-to", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--enumerate-output", default="migration_enumeration.jsonl")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        print("self-check OK")
        return

    if args.enumerate_from:
        enumerate_date_range(
            _load_rpc_url(),
            start_date=args.enumerate_from,
            end_date=args.enumerate_to,
            output_path=args.enumerate_output,
        )
        return

    until_block_time = int(datetime.strptime(args.until_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    report = run_sample(max_pages=args.max_pages, per_bucket=args.per_bucket, until_block_time=until_block_time)
    print(f"total classified: {len(report.classifications)}")
    print("por período, contagem de instrução:")
    for period, counts in sorted(report.by_period_instruction_counts().items()):
        print(f"  {period}: {counts}")
    print("pools distintos por período (dedup por mint):")
    for period, n in report.distinct_pools_by_period().items():
        print(f"  {period}: {n}")


def _self_check() -> None:
    buckets = stratified_sample(
        [
            {"signature": "A", "blockTime": 1711000000},  # 2024-Q1-ish
            {"signature": "B", "blockTime": 1711000100},
            {"signature": "C", "blockTime": 1790000000},  # ~2026-Q3-ish
        ],
        per_bucket=1,
    )
    assert all(len(sigs) <= 1 for sigs in buckets.values())
    assert sum(len(sigs) for sigs in buckets.values()) == 2  # one per bucket, 2 distinct buckets

    report = SampleReport(
        classifications=[
            TxClassification("A", "2025-Q2", "MigrateV2", False, False, None),
            TxClassification("B", "2025-Q2", "MigrateV2", True, True, "MINTApump"),
            TxClassification("C", "2026-Q3", "MigrateV1", True, False, "MINTBpump"),
        ]
    )
    counts = report.by_period_instruction_counts()
    assert counts["2025-Q2"] == {"MigrateV2": 2}
    assert counts["2026-Q3"] == {"MigrateV1": 1}
    pools = report.distinct_pools_by_period()
    assert pools == {"2025-Q2": 1, "2026-Q3": 1}


if __name__ == "__main__":
    main()
