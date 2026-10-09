"""SIG-FAST H2 historical backfill (rev. 4, 2026-10-08 operator review; Fase
E parte 2 addendum same day: windowed cluster sampling for enumeration).

Fetches already-happened pump->PumpSwap migrations and their pool trades via
RPC (Helius for migration enumeration, rotated endpoints for pool trades),
decodes them with the same Carbon decoder extended in item (a)
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
import os
import random
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from benchmarks.carbon_decoder_parity_v1.parity import extract_contextual_target_payloads
from benchmarks.move_first_h_coverage_audit_v0 import sample_migration_account as _mfh
from benchmarks.move_first_h_coverage_audit_v0.sample_migration_account import (
    BONDING_CURVE_PROGRAM,
    MIGRATION_AUTHORITY,
    PUMPSWAP_PROGRAM,
)

VERSION = "sig_fast_h2_historical_backfill_v0"

# Rule 3 (DRAFT rev. 4): per sampled token, trades from migration through
# migration + 20min (signal marker) + 60min (max window).
SIGNAL_MARKER_SECONDS = 20 * 60
MAX_WINDOW_SECONDS = 60 * 60
POOL_TRADE_WINDOW_SECONDS = SIGNAL_MARKER_SECONDS + MAX_WINDOW_SECONDS

CARBON_MANIFEST = "benchmarks/carbon_decoder_parity_v1/rust_runner/Cargo.toml"

# Public cluster endpoint, not a secret -- fine to keep as a literal constant.
PUBLIC_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"


def _load_rpc_url() -> str:
    match = re.search(r"^SOLANA_RPC_URL=(.*)$", open(".env").read(), re.MULTILINE)
    if not match or not match.group(1).strip():
        raise RuntimeError("SOLANA_RPC_URL not configured in .env")
    return match.group(1).strip()


def load_rotation_rpc_urls() -> list[str]:
    """Rotation pool for Stage 2 (getSignaturesForAddress + getTransaction):
    H2_BACKFILL_RPC_URLS (comma-separated env var, e.g. a free QuickNode
    endpoint) first, then the public cluster endpoint, then Helius LAST --
    operator instruction (Fase E parte 2): poupar a Helius pra Estagio 1
    (enumeracao), que so ela consegue fazer de forma barata (filtro
    blockTime exclusivo). Returns the raw URLs for EndpointRotator's own
    use -- callers must never print or log an entry of this list (operator
    instruction: never print/commit a URL)."""
    urls: list[str] = []
    extra = os.environ.get("H2_BACKFILL_RPC_URLS", "")
    urls.extend(u.strip() for u in extra.split(",") if u.strip())
    urls.append(PUBLIC_SOLANA_RPC_URL)
    urls.append(_load_rpc_url())
    return urls


def _sanitize_rpc_error(error: Exception, rpc_url: str) -> Exception:
    """Strip the raw endpoint URL out of an exception before it is allowed to
    propagate into a log/print/report -- urllib errors sometimes embed the
    request URL verbatim in their message."""
    text = str(error)
    if rpc_url in text:
        text = text.replace(rpc_url, "<redacted-rpc-url>")
    if text == str(error):
        return error
    sanitized = type(error)(text)
    return sanitized


class EndpointRotator:
    """Tries RPC endpoints in PRIORITY order (not round-robin): always
    starts from index 0, falling through to the next endpoint on a single
    endpoint's failure rather than aborting; only raises once every endpoint
    has failed for one call. Pass the most-preferred endpoint first -- Stage
    2 passes QuickNode/public first and Helius last (load_rotation_rpc_urls),
    so a successful call never touches Helius unless the others are down,
    sparing it for Stage 1 enumeration (operador, Fase E parte 2). Identifies
    a failing endpoint by its index only -- never logs a URL. Calls through
    `_mfh._rpc` (not a separate HTTP client) so the same rate limiter /
    circuit breaker that `install_rate_limited_rpc` installs on it (see
    h2_pilot_v0.py) still throttles every rotation call globally."""

    def __init__(self, rpc_urls: list[str]):
        if not rpc_urls:
            raise ValueError("EndpointRotator needs at least one RPC URL")
        self._urls = list(rpc_urls)

    def call(self, method: str, params: list, *, retries: int = 2) -> dict[str, Any]:
        errors: list[str] = []
        for index, url in enumerate(self._urls):
            try:
                return _mfh._rpc(url, method, params, retries=retries)
            except Exception as exc:  # noqa: BLE001 -- must try every endpoint before giving up
                errors.append(f"endpoint[{index}]: {_sanitize_rpc_error(exc, url)}")
        raise RuntimeError(f"all {len(self._urls)} rotation endpoints failed for {method}: {errors}")


# Addendum Fase E parte 4 (operador, 2026-10-09): tamanho do bucket da
# grade de preco. Achado que motivou isso: uma migracao real teve 16.473
# transacoes numa janela de 80min -- 1 getTransaction por trade e
# proibitivo; a grade reduz isso pra ~1 getTransaction por bucket.
GRID_BUCKET_SECONDS = 5

# Nao martelar um bucket anomalo cheio de tx nao-swap -- regra 2.
DEFAULT_BUCKET_SEARCH_MAX_LOOKBACK = 5
# Quantos buckets o preco em T0/no marco pode andar (pra frente em T0, pra
# tras no marco) procurando o primeiro swap resolvivel antes de desistir.
DEFAULT_PRICE_SEARCH_MAX_BUCKETS = 20


@dataclass(frozen=True)
class PoolSignatureEntry:
    signature: str
    block_time: int | None
    failed: bool


def fetch_pool_signatures_in_window(
    rotator: "EndpointRotator", *, pool_mint: str, window_start: int, window_end: int
) -> list[PoolSignatureEntry]:
    """Regra 1 (addendum Fase E parte 4): lista COMPLETA de assinaturas do
    pool na janela, via getSignaturesForAddress -- barato (1 credito
    flat), sem getTransaction nenhum, porque block_time e err ja vem na
    propria resposta. getSignaturesForAddress so caminha pra tras (mais
    novo primeiro) via `before`, entao pagina a partir de "agora" ate
    passar window_start, mantendo so o que cai em [window_start,
    window_end). Devolve em ordem crescente de block_time (mais antigo
    primeiro), pronta pra agrupar em buckets."""
    kept: list[PoolSignatureEntry] = []
    before: str | None = None
    while True:
        params: list = [pool_mint, {"limit": 1000}]
        if before is not None:
            params[1]["before"] = before
        result = rotator.call("getSignaturesForAddress", params)
        page = result.get("result") or []
        if not page:
            break
        for entry in page:
            bt = entry.get("blockTime")
            if bt is not None and window_start <= bt < window_end:
                kept.append(
                    PoolSignatureEntry(
                        signature=entry["signature"],
                        block_time=bt,
                        failed=entry.get("err") is not None,
                    )
                )
        before = page[-1]["signature"]
        oldest_bt = page[-1].get("blockTime")
        if len(page) < 1000:
            break
        if oldest_bt is not None and oldest_bt <= window_start:
            break
    kept.sort(key=lambda e: e.block_time if e.block_time is not None else 0)
    return kept


def group_successful_signatures_by_bucket(
    entries: list[PoolSignatureEntry], *, window_start: int, bucket_seconds: int = GRID_BUCKET_SECONDS
) -> dict[int, list[PoolSignatureEntry]]:
    """Agrupa as entradas BEM-SUCEDIDAS (err descartado -- regra 1) por
    bucket de `bucket_seconds`, preservando a ordem crescente de
    block_time dentro de cada bucket -- precisa disso pra andar pra tras
    (regra 2: "tenta a anterior no bucket")."""
    buckets: dict[int, list[PoolSignatureEntry]] = defaultdict(list)
    for entry in entries:
        if entry.failed or entry.block_time is None:
            continue
        bucket_index = (entry.block_time - window_start) // bucket_seconds
        buckets[bucket_index].append(entry)
    return dict(buckets)


def resolve_bucket_swap_price(
    rotator: "EndpointRotator",
    carbon: "CarbonDecoderProcess",
    candidates_in_bucket: list[PoolSignatureEntry],
    *,
    max_lookback: int = DEFAULT_BUCKET_SEARCH_MAX_LOOKBACK,
) -> dict[str, Any] | None:
    """Regra 2: pega a ULTIMA transacao bem-sucedida do bucket; se nao for
    (ou nao decodificar como) swap PumpSwap, tenta a anterior dentro do
    MESMO bucket, até achar um swap ou esgotar `max_lookback` tentativas
    (nunca martela um bucket anomalo sem fim). None se nenhum swap foi
    resolvido -- quem chama decide se carrega o preco do bucket anterior
    (regra 2) ou busca pra frente (preco em T0, regra 2)."""
    if not candidates_in_bucket:
        return None
    for entry in reversed(candidates_in_bucket[-max_lookback:]):
        result = rotator.call(
            "getTransaction",
            [entry.signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        tx = result.get("result")
        if tx is None:
            continue
        decoded = decode_historical_trades(carbon, [tx], batch_id=1)
        swap = next(
            (
                e
                for e in decoded
                if e.get("status") == "decoded" and e.get("event_type") in ("pumpswap_buy", "pumpswap_sell")
            ),
            None,
        )
        if swap is not None:
            return {"signature": entry.signature, "block_time": entry.block_time, "event": swap, "raw_tx": tx}
    return None


def resolve_price_at_t0(
    rotator: "EndpointRotator",
    carbon: "CarbonDecoderProcess",
    buckets_by_index: dict[int, list[PoolSignatureEntry]],
    *,
    max_buckets: int = DEFAULT_PRICE_SEARCH_MAX_BUCKETS,
) -> dict[str, Any] | None:
    """Preco em T0 (migracao): bucket 0 nao tem "anterior" pra carregar de
    (regra 2), entao busca pra FRENTE a partir dele até achar o primeiro
    swap resolvivel -- equivalente ao "price_first" do design anterior,
    so que restrito a um bucket por vez em vez de qualquer swap na janela
    inteira."""
    for bucket_index in range(0, max_buckets):
        resolved = resolve_bucket_swap_price(rotator, carbon, buckets_by_index.get(bucket_index, []))
        if resolved is not None:
            return resolved
    return None


def resolve_price_at_marker(
    rotator: "EndpointRotator",
    carbon: "CarbonDecoderProcess",
    buckets_by_index: dict[int, list[PoolSignatureEntry]],
    *,
    marker_seconds: int,
    bucket_seconds: int = GRID_BUCKET_SECONDS,
    max_buckets: int = DEFAULT_PRICE_SEARCH_MAX_BUCKETS,
) -> dict[str, Any] | None:
    """Preco no marco (ex. +20min): acha o bucket do marco; se nao tiver
    swap resolvivel, carrega do bucket anterior (regra 2: "bucket sem tx
    -> preco carregado do anterior, sem swap o pool nao muda"), andando
    pra tras até `max_buckets` ou o bucket 0."""
    target_bucket = marker_seconds // bucket_seconds
    for bucket_index in range(target_bucket, max(-1, target_bucket - max_buckets), -1):
        resolved = resolve_bucket_swap_price(rotator, carbon, buckets_by_index.get(bucket_index, []))
        if resolved is not None:
            return resolved
    return None


@dataclass(frozen=True)
class MigrationCandidate:
    pool_mint: str
    migration_signature: str
    migration_block_time: int


def sample_calendar_windows(
    *, start_date: str, end_date: str, window_minutes: int, k: int, seed: int
) -> list[tuple[int, int]]:
    """Operador, 2026-10-08 (Fase E parte 2): sorteia k janelas de
    window_minutes minutos sobre [start_date, end_date), seed fixa.
    Substitui caminhar a conta de migracao inteira (fetch_migrations_in_range,
    removido) -- enumeracao dia-a-dia cara, foi o que disparou o 429
    sustentado na conta de alto volume (MIGRATION_AUTHORITY). As janelas
    vem de um grid NAO-SOBREPOSTO de tamanho fixo e sao sorteadas sem
    reposicao dentro dele (random.Random(seed).sample) -- isso garante
    uniformidade e zero overlap por construcao, sem precisar de rejection
    sampling."""
    start_epoch = int(
        datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )
    end_epoch = int(
        datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )
    window_seconds = window_minutes * 60
    n_slots = max(0, (end_epoch - start_epoch) // window_seconds)
    if n_slots == 0:
        return []
    rng = random.Random(seed)
    chosen = sorted(rng.sample(range(n_slots), k=min(k, n_slots)))
    return [
        (start_epoch + i * window_seconds, start_epoch + (i + 1) * window_seconds)
        for i in chosen
    ]


def fetch_migrations_in_windows(
    rpc_url: str, *, window_start: int, window_end: int
) -> list[MigrationCandidate]:
    """Operador, 2026-10-08 (Fase E parte 2): todas as migracoes pump->PumpSwap
    bem-sucedidas dentro de UMA janela sorteada (getTransactionsForAddress
    com filtro blockTime), dedup por pool_mint. Unidade de amostra = a
    janela (conglomerado) -- toda migracao bem-sucedida dentro dela entra,
    nunca so "a proxima depois de um horario aleatorio" (enviesaria pra
    migracoes apos hiatos calmos, regra explicita do operador). "Bem-
    sucedida" exige as DUAS coisas: completed_create_pool=True E
    meta.err is None -- um no-op de "ja migrado" tambem tem err=null (achado
    ja confirmado em MOVE-FIRST-H-DISC-V0), entao err por si so nao basta."""
    seen_pools: set[str] = set()
    candidates: list[MigrationCandidate] = []
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
        result = _mfh._rpc(rpc_url, "getTransactionsForAddress", [MIGRATION_AUTHORITY, params])
        payload = result.get("result") or {}
        rows = payload.get("data") or []
        for row in rows:
            message = row["transaction"]["message"]
            if not _mfh._touches_pumpfun_programs(message):
                continue
            logs = row.get("meta", {}).get("logMessages") or []
            if not any("Instruction: CreatePool" in line for line in logs):
                continue
            if row.get("meta", {}).get("err") is not None:
                continue
            pool_mint = _mfh._extract_pool_mint(message)
            if not pool_mint or pool_mint in seen_pools:
                continue
            seen_pools.add(pool_mint)
            candidates.append(
                MigrationCandidate(
                    pool_mint=pool_mint,
                    migration_signature=row["transaction"]["signatures"][0],
                    migration_block_time=row.get("blockTime") or window_start,
                )
            )
        pagination_token = payload.get("paginationToken")
        if not pagination_token or not rows:
            break
    return candidates


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

    # sample_calendar_windows: deterministic, non-overlapping, uniform grid.
    windows = sample_calendar_windows(
        start_date="2026-01-01", end_date="2026-01-02", window_minutes=10, k=3, seed=20261008
    )
    assert len(windows) == 3, windows
    for start, end in windows:
        assert end - start == 600, (start, end)
    assert len(set(windows)) == 3, windows  # no duplicate/overlapping windows
    windows_again = sample_calendar_windows(
        start_date="2026-01-01", end_date="2026-01-02", window_minutes=10, k=3, seed=20261008
    )
    assert windows == windows_again, (windows, windows_again)

    # fetch_migrations_in_windows: dedup by pool; "successful" requires BOTH
    # completed_create_pool AND err is None -- an "already migrated" no-op
    # also has err=null (real finding from sample_migration_account.py), and
    # a failed CreatePool attempt on the same pool must stay excluded too.
    window_start, window_end = windows[0]
    pool = "POOLwindowpump"
    sig_migrate, sig_noop, sig_failed = "SIGMIGRATE", "SIGNOOP", "SIGFAILED"

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        assert method == "getTransactionsForAddress"
        assert params[0] == MIGRATION_AUTHORITY
        assert params[1]["filters"]["blockTime"] == {"gte": window_start, "lt": window_end}
        rows = [
            {
                "transaction": {
                    "signatures": [sig_migrate],
                    "message": {"accountKeys": [BONDING_CURVE_PROGRAM, PUMPSWAP_PROGRAM, pool]},
                },
                "blockTime": window_start + 5,
                "meta": {"logMessages": ["Program log: Instruction: CreatePool"], "err": None},
            },
            {
                "transaction": {
                    "signatures": [sig_noop],
                    "message": {"accountKeys": [BONDING_CURVE_PROGRAM]},
                },
                "blockTime": window_start + 6,
                "meta": {"logMessages": ["Program log: Instruction: Migrate"], "err": None},
            },
            {
                "transaction": {
                    "signatures": [sig_failed],
                    "message": {"accountKeys": [BONDING_CURVE_PROGRAM, PUMPSWAP_PROGRAM, pool]},
                },
                "blockTime": window_start + 7,
                "meta": {
                    "logMessages": ["Program log: Instruction: CreatePool"],
                    "err": {"InstructionError": [0, "boom"]},
                },
            },
        ]
        return {"result": {"data": rows, "paginationToken": None}}

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        candidates = fetch_migrations_in_windows(
            "fake://rpc", window_start=window_start, window_end=window_end
        )
    assert len(candidates) == 1, candidates
    assert candidates[0].pool_mint == pool, candidates
    assert candidates[0].migration_signature == sig_migrate, candidates
    assert candidates[0].migration_block_time == window_start + 5, candidates


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


def _self_check_rotation() -> None:
    from unittest.mock import patch

    calls: list[str] = []

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        calls.append(rpc_url)
        if rpc_url == "fake://bad":
            raise RuntimeError(f"boom at {rpc_url}")
        return {"result": "ok-from-good"}

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        rotator = EndpointRotator(["fake://bad", "fake://good"])
        result = rotator.call("getSlot", [])
        assert result["result"] == "ok-from-good", result
        assert calls == ["fake://bad", "fake://good"], calls

        all_bad = EndpointRotator(["fake://bad", "fake://bad"])
        try:
            all_bad.call("getSlot", [])
            raise AssertionError("expected RuntimeError when every endpoint fails")
        except RuntimeError as exc:
            assert "fake://bad" not in str(exc), exc
            assert "<redacted-rpc-url>" in str(exc), exc

    window_start, window_end = 1_000_000, 1_000_100

    def fake_rpc_pool(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSignaturesForAddress":
            return {
                "result": [
                    {"signature": "SIG_NEW", "blockTime": 1_000_200, "err": None},
                    {"signature": "SIG_IN_WINDOW", "blockTime": 1_000_050, "err": None},
                    {"signature": "SIG_FAILED_IN_WINDOW", "blockTime": 1_000_060, "err": {"InstructionError": [0, "boom"]}},
                    {"signature": "SIG_OLD", "blockTime": 900_000, "err": None},
                ]
            }
        raise AssertionError(f"unexpected method: {method}")

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc_pool,
    ):
        rotator = EndpointRotator(["fake://only"])
        entries = fetch_pool_signatures_in_window(
            rotator, pool_mint="POOLpump", window_start=window_start, window_end=window_end
        )
    # regra 1: so o que cai na janela, mas AMBAS sucesso e falha (err !=
    # null nao e descartado AQUI -- so no agrupamento por bucket).
    assert [e.signature for e in entries] == ["SIG_IN_WINDOW", "SIG_FAILED_IN_WINDOW"], entries
    assert entries[0].failed is False and entries[1].failed is True, entries


def _self_check_price_grid() -> None:
    from unittest.mock import patch

    window_start = 1_000
    pool_mint = "POOLpump"
    sig_t0 = "SIG_T0"
    sig_marker_swap = "SIG_MARKER_SWAP"
    sig_marker_notswap = "SIG_MARKER_NOTSWAP"
    sig_failed = "SIG_FAILED"

    raw_rows_by_sig = {
        sig_t0: _fake_pumpswap_buy_raw_row(
            signature=sig_t0, slot=1, block_time=window_start, pool_mint=pool_mint
        ),
        sig_marker_swap: _fake_pumpswap_buy_raw_row(
            signature=sig_marker_swap, slot=2, block_time=window_start + 21, pool_mint=pool_mint
        ),
        # Sem log de PumpSwap nenhum -- extract_contextual_target_payloads
        # nao acha target, decode_historical_trades devolve [] -- "nao e
        # swap", regra 2 deve andar pra tras no bucket a partir daqui.
        sig_marker_notswap: {
            "transaction": {"signatures": [sig_marker_notswap], "message": {"accountKeys": []}},
            "slot": 3,
            "blockTime": window_start + 23,
            "meta": {"logMessages": []},
        },
    }

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSignaturesForAddress":
            return {
                "result": [
                    {"signature": sig_t0, "blockTime": window_start, "err": None},
                    {"signature": sig_marker_swap, "blockTime": window_start + 21, "err": None},
                    {"signature": sig_marker_notswap, "blockTime": window_start + 23, "err": None},
                    {
                        "signature": sig_failed,
                        "blockTime": window_start + 24,
                        "err": {"InstructionError": [0, "boom"]},
                    },
                ]
            }
        if method == "getTransaction":
            signature = params[0]
            row = raw_rows_by_sig.get(signature)
            if row is None:
                raise AssertionError(f"unexpected getTransaction for failed/unknown signature {signature}")
            return {"result": row}
        raise AssertionError(f"unexpected method: {method}")

    canned = [
        {
            "event_key": f"{sig_t0}:1:pumpswap_buy",
            "status": "decoded",
            "event_type": "pumpswap_buy",
            "pool_base_token_reserves_raw": 1000,
            "pool_quote_token_reserves_raw": 600,
        },
        {
            "event_key": f"{sig_marker_swap}:1:pumpswap_buy",
            "status": "decoded",
            "event_type": "pumpswap_buy",
            "pool_base_token_reserves_raw": 500,
            "pool_quote_token_reserves_raw": 900,
        },
    ]
    carbon = _FakeCarbonProcess(canned)

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        rotator = EndpointRotator(["fake://only"])
        entries = fetch_pool_signatures_in_window(
            rotator, pool_mint=pool_mint, window_start=window_start, window_end=window_start + 100
        )
        assert len(entries) == 4, entries
        assert sum(1 for e in entries if e.failed) == 1, entries

        buckets = group_successful_signatures_by_bucket(entries, window_start=window_start)
        # bucket 0 (0-4s): so sig_t0; bucket 4 (20-24s): sig_marker_swap(21)
        # seguido de sig_marker_notswap(23), que e o ULTIMO cronologicamente.
        assert [e.signature for e in buckets[0]] == [sig_t0], buckets
        assert [e.signature for e in buckets[4]] == [sig_marker_swap, sig_marker_notswap], buckets

        t0_resolved = resolve_price_at_t0(rotator, carbon, buckets)
        assert t0_resolved is not None and t0_resolved["signature"] == sig_t0, t0_resolved

        # regra 2: a ULTIMA tx do bucket (sig_marker_notswap) nao e swap --
        # tem que andar pra tras e achar sig_marker_swap, nunca pular pra
        # outro bucket enquanto o atual nao se esgota.
        marker_resolved = resolve_price_at_marker(rotator, carbon, buckets, marker_seconds=20)
        assert marker_resolved is not None and marker_resolved["signature"] == sig_marker_swap, marker_resolved

        # Bucket vazio (nenhuma entrada bem-sucedida) -> None; quem chama
        # decide se carrega o preco do bucket anterior.
        assert resolve_bucket_swap_price(rotator, carbon, buckets.get(1, [])) is None


def _self_check() -> None:
    _self_check_sampling()
    _self_check_decode_and_persist()
    _self_check_rotation()
    _self_check_price_grid()
    print(
        "self-check OK: sampling (dedup/exclusion/deterministic seed) + decode/persist "
        "(wiring + idempotent replay) + rotation (fallback-not-abort + sanitized errors) + "
        "price grid (signature list w/ err + bucket grouping + swap search w/ backward "
        "lookback + T0/marker resolution)"
    )


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
