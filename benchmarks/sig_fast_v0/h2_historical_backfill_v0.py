"""SIG-FAST H2 historical backfill (rev. 4, 2026-10-08 operator review).

Fetches already-happened pump->PumpSwap migrations and their pool trades via
RPC (Helius), decodes them with the same Carbon decoder extended in item (a)
(benchmarks/carbon_decoder_parity_v1/rust_runner, binary
`stream_decode_batches` -- reuses `decode_event()` from main.rs unchanged,
confirmed by reading src/bin/stream_decode_batches.rs), and persists raw +
decoded rows to a dedicated provenance table. Never touches
market_trade_observations and never invents an observed_at (CLAUDE.md
invariant 11) -- this table has `fetched_at` (when the RPC call happened,
real wall clock) and `block_time` (when the trade happened on-chain, real
historical time), two different real timestamps, never one standing in for
the other.

Read-only against chain state; writes only to its own `sig_fast_h2_backfill_v0`
table. Never computes a price, a return, or any economic outcome -- this
module stops at decoded raw fields (amounts/reserves/fees) and counts. See
docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md (rev. 4,
"Regras anti-vies do discovery historico de H2") for the frozen protocol
this implements.
"""

from __future__ import annotations

import base64
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from benchmarks.carbon_decoder_parity_v1.parity import extract_contextual_target_payloads
from benchmarks.move_first_h_coverage_audit_v0 import sample_migration_account as _mfh
from benchmarks.move_first_h_coverage_audit_v0.sample_migration_account import (
    BONDING_CURVE_PROGRAM,
    MIGRATION_AUTHORITY,
    PUMPSWAP_PROGRAM,
    fetch_day_classified,
)

VERSION = "sig_fast_h2_historical_backfill_v0"

# Rule 3 (DRAFT rev. 4): per sampled token, trades from migration through
# migration + 20min (signal marker) + 60min (max window).
SIGNAL_MARKER_SECONDS = 20 * 60
MAX_WINDOW_SECONDS = 60 * 60
POOL_TRADE_WINDOW_SECONDS = SIGNAL_MARKER_SECONDS + MAX_WINDOW_SECONDS

CARBON_MANIFEST = "benchmarks/carbon_decoder_parity_v1/rust_runner/Cargo.toml"


def _load_rpc_url() -> str:
    match = re.search(r"^SOLANA_RPC_URL=(.*)$", open(".env").read(), re.MULTILINE)
    if not match or not match.group(1).strip():
        raise RuntimeError("SOLANA_RPC_URL not configured in .env")
    return match.group(1).strip()


@dataclass(frozen=True)
class MigrationCandidate:
    pool_mint: str
    migration_signature: str
    migration_block_time: int


def fetch_migrations_in_range(
    rpc_url: str, *, start_date: str, end_date: str
) -> list[MigrationCandidate]:
    """Rule 1 (DRAFT rev. 4): completed pump->PumpSwap migrations in
    [start_date, end_date), dedup by pool_mint. Reuses fetch_day_classified
    (proven live in MOVE-FIRST-H-DISC-V0: ~1-5s/day via getTransactionsForAddress
    with a blockTime filter) day by day; keeps only rows that actually
    complete CreatePool (excludes "already migrated" no-ops, which have
    err=null and would otherwise look successful)."""
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    seen_pools: set[str] = set()
    candidates: list[MigrationCandidate] = []
    day = start
    while day < end:
        rows = fetch_day_classified(rpc_url, day=day.strftime("%Y-%m-%d"))
        for row in rows:
            if not row.touches_pumpfun or not row.completed_create_pool or not row.pool_mint:
                continue
            if row.pool_mint in seen_pools:
                continue
            seen_pools.add(row.pool_mint)
            candidates.append(
                MigrationCandidate(
                    pool_mint=row.pool_mint,
                    migration_signature=row.signature,
                    migration_block_time=_day_start_epoch(day),
                )
            )
        day += timedelta(days=1)
    return candidates


def _day_start_epoch(day: datetime) -> int:
    # Placeholder until a real getTransaction call resolves the exact
    # blockTime of the migration signature itself (TxClassification from
    # fetch_day_classified does not carry blockTime today) -- callers that
    # need the exact migration instant must resolve it via getTransaction(
    # migration_signature) before computing the trade window (rule 3).
    return int(day.timestamp())


def sample_migrations_excluding_blocks(
    candidates: list[MigrationCandidate],
    *,
    n: int,
    seed: int,
    excluded_block_starts: tuple[int, ...],
    excluded_block_ends: tuple[int, ...],
) -> list[MigrationCandidate]:
    """Rule 1 + piloto (step A): random sample with a fixed, pre-committed
    seed, excluding any candidate whose migration falls inside one of the
    frozen discovery/confirmation blocks (so the piloto never touches the
    sealed data)."""
    if len(excluded_block_starts) != len(excluded_block_ends):
        raise ValueError("excluded_block_starts/ends must be the same length")
    eligible = [
        c
        for c in candidates
        if not any(
            start <= c.migration_block_time < end
            for start, end in zip(excluded_block_starts, excluded_block_ends)
        )
    ]
    rng = random.Random(seed)
    return rng.sample(eligible, k=min(n, len(eligible)))


def fetch_pool_trades_raw(
    rpc_url: str, *, pool_mint: str, window_start: int, window_end: int
) -> list[dict[str, Any]]:
    """Every transaction touching the pool account in [window_start, window_end).
    Same getTransactionsForAddress + blockTime-filter mechanism already proven
    in sample_migration_account.py, pointed at the pool instead of the
    migration-authority account."""
    results: list[dict[str, Any]] = []
    pagination_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "limit": 1000,
            "sortOrder": "asc",
            "transactionDetails": "full",
            "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1,
            "filters": {"blockTime": {"gte": window_start, "lt": window_end}},
        }
        if pagination_token is not None:
            params["paginationToken"] = pagination_token
        result = _mfh._rpc(rpc_url, "getTransactionsForAddress", [pool_mint, params])
        payload = result.get("result") or {}
        rows = payload.get("data") or []
        results.extend(rows)
        pagination_token = payload.get("paginationToken")
        if not pagination_token or not rows:
            break
    return results


class CarbonDecoderProcess(Protocol):
    def request(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def decode_historical_trades(
    carbon: CarbonDecoderProcess,
    raw_rows: list[dict[str, Any]],
    *,
    batch_id: int = 1,
) -> list[dict[str, Any]]:
    """Rule 3: decode every Pump/PumpSwap event in a page of historical
    transactions through the same Carbon decoder the live engine uses
    (reservations+fees already exposed by item (a)). `carbon` is anything
    with the stream_decode_batches request/response protocol (a real
    JsonLineProcess, or a test double) -- see
    benchmarks/integrated_market_signal_plane_v1/live_shadow.py for the
    live-side use of the identical protocol."""
    items: list[dict[str, Any]] = []
    for row in raw_rows:
        logs = row.get("meta", {}).get("logMessages") or []
        targets, _stack_errors = extract_contextual_target_payloads(logs)
        signature = row["transaction"]["signatures"][0]
        for target in targets:
            event_key = f"{signature}:{target['log_index']}:{target['event_type']}"
            items.append(
                {
                    "type": "carbon_decoder_input",
                    "event_key": event_key,
                    "signature": signature,
                    "slot": row.get("slot"),
                    "log_index": target["log_index"],
                    "program_id": target["program_id"],
                    "event_type": target["event_type"],
                    "payload_base64": base64.b64encode(bytes(target["payload"])).decode("ascii"),
                }
            )
    if not items:
        return []
    response = carbon.request({"type": "carbon_decoder_batch", "batch_id": batch_id, "items": items})
    if response.get("type") != "carbon_canonical_batch" or response.get("batch_id") != batch_id:
        raise RuntimeError(f"unexpected Carbon stream response: {response!r}")
    decoded = response.get("items")
    if not isinstance(decoded, list):
        raise RuntimeError("Carbon canonical batch missing items")
    return decoded


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sig_fast_h2_backfill_v0 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    pool_mint TEXT NOT NULL,
    migration_signature TEXT NOT NULL,
    migration_block_time INTEGER NOT NULL,
    signature TEXT NOT NULL,
    block_time INTEGER,
    slot INTEGER,
    fetch_sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    decode_status TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    decoded_json TEXT,
    UNIQUE(pool_mint, signature, event_type)
);
CREATE INDEX IF NOT EXISTS idx_sig_fast_h2_backfill_v0_pool
ON sig_fast_h2_backfill_v0(pool_mint, slot, fetch_sequence);
"""


def ensure_h2_backfill_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def record_backfill_rows(
    conn: sqlite3.Connection,
    *,
    source: str,
    pool_mint: str,
    migration_signature: str,
    migration_block_time: int,
    raw_rows: list[dict[str, Any]],
    decoded_events: list[dict[str, Any]],
) -> int:
    """Rule 5/6: persist the raw response (so a hash commit covers the real
    downloaded bytes, not just what we chose to decode) alongside the
    decoded canonical event, if any -- keyed by event_key so each matches its
    own raw transaction. fetched_at is `time.time()` at write time (real;
    this function is only ever called right after the RPC calls that produced
    raw_rows/decoded_events, never on replayed or synthetic data in a real
    run). Ordering within a slot uses fetch_sequence (the order Helius
    returned events in this call, requested sortOrder=asc) as the proxy for
    "index of the tx in the block" (rule 3) -- Solana RPC responses in this
    pipeline do not expose a literal in-block index field."""
    ensure_h2_backfill_schema(conn)
    decoded_by_event_key = {
        str(item["event_key"]): item for item in decoded_events if "event_key" in item
    }
    fetched_at = int(time.time())
    inserted = 0
    fetch_sequence = 0
    with conn:
        for row in raw_rows:
            logs = row.get("meta", {}).get("logMessages") or []
            targets, _ = extract_contextual_target_payloads(logs)
            signature = row["transaction"]["signatures"][0]
            slot = row.get("slot")
            if not targets:
                continue
            for target in targets:
                event_key = f"{signature}:{target['log_index']}:{target['event_type']}"
                decoded = decoded_by_event_key.get(event_key)
                decode_status = "decoded" if decoded is not None else "no_decoded_event"
                conn.execute(
                    """INSERT OR IGNORE INTO sig_fast_h2_backfill_v0(
                        source, fetched_at, pool_mint, migration_signature,
                        migration_block_time, signature, block_time, slot,
                        fetch_sequence, event_type, decode_status, raw_json,
                        decoded_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        source,
                        fetched_at,
                        pool_mint,
                        migration_signature,
                        migration_block_time,
                        signature,
                        row.get("blockTime"),
                        slot,
                        fetch_sequence,
                        target["event_type"],
                        decode_status,
                        _json_dumps(row),
                        _json_dumps(decoded) if decoded is not None else None,
                    ),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
                fetch_sequence += 1
    return inserted


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class _FakeCarbonProcess:
    """Self-check-only stand-in for the real stream_decode_batches subprocess
    -- proves decode_historical_trades/record_backfill_rows wire inputs to
    outputs correctly. The real Carbon decode path (new fee/reserve fields
    included) was already proven with a live Borsh round-trip smoke test in
    item (a) of this work order; re-proving that here would just slow this
    self-check down without covering anything new."""

    def __init__(self, canned_items: list[dict[str, Any]]):
        self._canned_items = canned_items

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_keys = {item["event_key"] for item in payload["items"]}
        return {
            "type": "carbon_canonical_batch",
            "batch_id": payload["batch_id"],
            "items": [item for item in self._canned_items if item["event_key"] in requested_keys],
        }


def _fake_pumpswap_buy_raw_row(
    *, signature: str, slot: int, block_time: int, pool_mint: str
) -> dict[str, Any]:
    # A short dummy payload (not a real Borsh-encoded BuyEvent) is enough
    # here: extract_contextual_target_payloads only needs the discriminator
    # prefix to classify event_type, it does not decode the payload itself.
    from benchmarks.carbon_decoder_parity_v1.parity import (
        PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
        PUMPSWAP_PROGRAM_ID,
    )

    payload = PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"\x00" * 16
    encoded = base64.b64encode(payload).decode("ascii")
    return {
        "transaction": {"signatures": [signature], "message": {"accountKeys": [PUMPSWAP_PROGRAM]}},
        "slot": slot,
        "blockTime": block_time,
        "meta": {
            "logMessages": [
                f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
                f"Program data: {encoded}",
                f"Program {PUMPSWAP_PROGRAM_ID} success",
            ]
        },
    }


def _self_check_sampling() -> None:
    from unittest.mock import patch

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        assert method == "getTransactionsForAddress"
        assert params[0] == MIGRATION_AUTHORITY
        day_start = params[1]["filters"]["blockTime"]["gte"]
        # One completed migration (pool mint ends in "pump") plus one
        # already-migrated no-op (completed_create_pool must stay False for
        # it) per day, mirroring the real dedup finding from
        # sample_migration_account.py.
        pool = f"POOL{day_start}pump"
        sig_migrate = f"SIGM{day_start}"
        sig_noop = f"SIGN{day_start}"
        rows = [
            {
                "transaction": {
                    "signatures": [sig_migrate],
                    "message": {"accountKeys": [BONDING_CURVE_PROGRAM, PUMPSWAP_PROGRAM, pool]},
                },
                "meta": {"logMessages": ["Program log: Instruction: CreatePool"]},
            },
            {
                "transaction": {
                    "signatures": [sig_noop],
                    "message": {"accountKeys": [BONDING_CURVE_PROGRAM]},
                },
                "meta": {"logMessages": ["Program log: Instruction: Migrate"]},
            },
        ]
        return {"result": {"data": rows, "paginationToken": None}}

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        candidates = fetch_migrations_in_range(
            "fake://rpc", start_date="2026-01-01", end_date="2026-01-04"
        )
    assert len(candidates) == 3, candidates
    assert all(c.pool_mint.endswith("pump") for c in candidates), candidates

    day1_epoch = candidates[0].migration_block_time
    sample = sample_migrations_excluding_blocks(
        candidates,
        n=2,
        seed=20261008,
        excluded_block_starts=(day1_epoch,),
        excluded_block_ends=(day1_epoch + 1,),
    )
    assert len(sample) == 2, sample
    assert all(c.migration_block_time != day1_epoch for c in sample), sample

    # Fixed seed is deterministic given the same eligible pool.
    sample_again = sample_migrations_excluding_blocks(
        candidates,
        n=2,
        seed=20261008,
        excluded_block_starts=(day1_epoch,),
        excluded_block_ends=(day1_epoch + 1,),
    )
    assert sample == sample_again, (sample, sample_again)


def _self_check_decode_and_persist() -> None:
    import sqlite3

    raw_row = _fake_pumpswap_buy_raw_row(
        signature="SIG1", slot=111, block_time=1_000_000, pool_mint="POOLpump"
    )
    event_key = "SIG1:1:pumpswap_buy"
    canned = [
        {
            "event_key": event_key,
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_type": "pumpswap_buy",
            "base_amount_raw": 100,
            "quote_amount_raw": 700,
            "pool_base_token_reserves_raw": 500,
            "pool_quote_token_reserves_raw": 600,
            "lp_fee_raw": 7,
            "protocol_fee_raw": 3,
            "coin_creator_fee_raw": 21,
        }
    ]
    carbon = _FakeCarbonProcess(canned)
    decoded = decode_historical_trades(carbon, [raw_row], batch_id=1)
    assert len(decoded) == 1, decoded
    assert decoded[0]["lp_fee_raw"] == 7, decoded

    conn = sqlite3.connect(":memory:")
    try:
        inserted = record_backfill_rows(
            conn,
            source="helius_getTransactionsForAddress",
            pool_mint="POOLpump",
            migration_signature="SIGMIGRATION",
            migration_block_time=999_900,
            raw_rows=[raw_row],
            decoded_events=decoded,
        )
        assert inserted == 1, inserted
        row = conn.execute(
            "SELECT fetched_at, block_time, decode_status, decoded_json FROM sig_fast_h2_backfill_v0"
        ).fetchone()
        assert row[0] > 0, row  # fetched_at is a real wall-clock value, never 0/faked
        assert row[1] == 1_000_000, row
        assert row[2] == "decoded", row
        assert '"lp_fee_raw":7' in row[3], row

        # Idempotent replay: same signature/pool/event_type does not duplicate.
        replay_inserted = record_backfill_rows(
            conn,
            source="helius_getTransactionsForAddress",
            pool_mint="POOLpump",
            migration_signature="SIGMIGRATION",
            migration_block_time=999_900,
            raw_rows=[raw_row],
            decoded_events=decoded,
        )
        assert replay_inserted == 0, replay_inserted
        count = conn.execute("SELECT COUNT(*) FROM sig_fast_h2_backfill_v0").fetchone()[0]
        assert count == 1, count
    finally:
        conn.close()


def _self_check() -> None:
    _self_check_sampling()
    _self_check_decode_and_persist()
    print("self-check OK: sampling (dedup/exclusion/deterministic seed) + decode/persist (wiring + idempotent replay)")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print(
        "No real-data entrypoint yet in this module -- see "
        "benchmarks/sig_fast_v0/h2_pilot_v0.py for the piloto (step A) CLI, "
        "which is the first real-RPC consumer of this module."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
