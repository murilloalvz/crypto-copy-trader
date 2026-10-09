"""SIG-FAST H2 Passo B -- sela (download + hash + cobertura) UM bloco real
(discovery OU confirmacao), nunca os dois juntos.

Regra 5 (DRAFT, addendum Fase E parte 4): baixar -> gravar o bruto -> hash
commitado -> so entao calcular qualquer coisa. Este modulo persiste cada
assinatura/evento resolvido na tabela de proveniencia (sig_fast_h2_backfill_v0,
schema de benchmarks/sig_fast_v0/h2_historical_backfill_v0.py) ANTES de
reportar qualquer numero de cobertura, e grava um hash do banco apos cada
estagio.

NUNCA calcula retorno, MFE, barreira ou EV -- so cobertura e contagem de
sistema (migracoes, sobreviventes/nao-sobreviventes, % de buckets
resolvidos, % missing, % de eventos com reservas+fee, tempo e chamadas).

Separacao discovery/confirmacao e responsabilidade dos dois wrappers
(h2_seal_discovery_v0.py / h2_seal_confirmation_v0.py): cada um passa SEU
PROPRIO db_path/checkpoint_path, fixos no proprio arquivo, nunca vindos de
um parametro compartilhado que pudesse ser trocado -- este modulo nunca
sabe nem precisa saber que o "outro bloco" existe.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import (
    EndpointRotator,
    GRID_BUCKET_SECONDS,
    MigrationCandidate,
    POOL_TRADE_WINDOW_SECONDS,
    SIGNAL_MARKER_SECONDS,
    ensure_h2_backfill_schema,
    fetch_migrations_in_windows,
    fetch_pool_signatures_in_window,
    group_successful_signatures_by_bucket,
    record_backfill_rows,
    resolve_bucket_swap_price,
    resolve_price_at_marker,
    resolve_price_at_t0,
    sample_calendar_windows,
)
from benchmarks.sig_fast_v0.h2_pilot_v0 import (
    CarbonDecoderProcess,
    FULL_WINDOW_BUCKETS,
    LAST_5MIN_SECONDS,
    MIN_SUCCESSFUL_TRADES_LAST_5MIN_FOR_SURVIVOR,
    RpcUsageTracker,
    _survival_system_count_from_resolved,
)

VERSION = "sig_fast_h2_block_seal_v0"


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"windows_done": [], "candidates": [], "stage1": {}, "stage2": {}, "system_error_pools": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_hash_manifest(db_path: Path, *, stage: str, block_name: str, row_count: int) -> dict[str, Any]:
    """Regra 5: hash commitado ANTES de qualquer calculo de cobertura.
    Grava um manifesto append-only (uma linha por selagem de estagio) ao
    lado do banco -- nunca sobrescreve um hash anterior."""
    manifest_path = db_path.with_suffix(db_path.suffix + ".hashes.jsonl")
    entry = {
        "block_name": block_name,
        "stage": stage,
        "sha256": _hash_file(db_path),
        "row_count_sig_fast_h2_backfill_v0": row_count,
        "sealed_at": int(time.time()),
    }
    with open(manifest_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


@dataclass(frozen=True)
class Stage1SealResult:
    pool_mint: str
    migration_signature: str
    migration_block_time: int
    n_signatures_in_window: int
    n_failed_tx: int
    pct_failed_tx: float
    n_successful_trades_last_5min_before_marker: int
    survived_20min_system_count: bool | None
    n_events_decoded: int
    n_events_with_reserves_and_fee: int
    n_rpc_calls: int
    elapsed_seconds: float


def seal_stage1_token(
    conn: sqlite3.Connection,
    carbon: CarbonDecoderProcess,
    candidate: MigrationCandidate,
    *,
    rotator: EndpointRotator,
    tracker: RpcUsageTracker,
    source: str,
) -> Stage1SealResult:
    """Mesma classificacao de run_pilot_token (h2_pilot_v0.py, correcao de
    vies: baixo volume = nao-sobrevivente direto, sem gastar chamada de
    preco) -- mas aqui tambem GRAVA o bruto resolvido (T0/marco) na tabela
    de proveniencia antes de devolver o resumo."""
    t0_wall = time.monotonic()
    calls_before = len(tracker.calls)
    window_start = candidate.migration_block_time
    window_end = window_start + POOL_TRADE_WINDOW_SECONDS

    entries = fetch_pool_signatures_in_window(
        rotator, pool_mint=candidate.pool_mint, window_start=window_start, window_end=window_end
    )
    n_total = len(entries)
    n_failed = sum(1 for e in entries if e.failed)
    pct_failed = round(100.0 * n_failed / n_total, 2) if n_total else 0.0
    n_last_5min = sum(
        1
        for e in entries
        if not e.failed
        and e.block_time is not None
        and (SIGNAL_MARKER_SECONDS - LAST_5MIN_SECONDS) <= (e.block_time - window_start) < SIGNAL_MARKER_SECONDS
    )

    if n_last_5min < MIN_SUCCESSFUL_TRADES_LAST_5MIN_FOR_SURVIVOR:
        t0_resolved = None
        marker_resolved = None
        survived: bool | None = False
    else:
        buckets = group_successful_signatures_by_bucket(entries, window_start=window_start)
        t0_resolved = resolve_price_at_t0(rotator, carbon, buckets, max_buckets=FULL_WINDOW_BUCKETS)
        marker_resolved = resolve_price_at_marker(
            rotator, carbon, buckets, marker_seconds=SIGNAL_MARKER_SECONDS, max_buckets=FULL_WINDOW_BUCKETS
        )
        survived = _survival_system_count_from_resolved(t0_resolved, marker_resolved)

    raw_rows = [r["raw_tx"] for r in (t0_resolved, marker_resolved) if r is not None]
    decoded_events = [r["event"] for r in (t0_resolved, marker_resolved) if r is not None]
    if raw_rows:
        record_backfill_rows(
            conn,
            source=source,
            pool_mint=candidate.pool_mint,
            migration_signature=candidate.migration_signature,
            migration_block_time=window_start,
            raw_rows=raw_rows,
            decoded_events=decoded_events,
        )

    n_decoded = len(decoded_events)
    n_with_both = sum(
        1
        for e in decoded_events
        if e.get("pool_base_token_reserves_raw") is not None
        and (e.get("lp_fee_raw") is not None or e.get("fee_raw") is not None)
    )

    return Stage1SealResult(
        pool_mint=candidate.pool_mint,
        migration_signature=candidate.migration_signature,
        migration_block_time=window_start,
        n_signatures_in_window=n_total,
        n_failed_tx=n_failed,
        pct_failed_tx=pct_failed,
        n_successful_trades_last_5min_before_marker=n_last_5min,
        survived_20min_system_count=survived,
        n_events_decoded=n_decoded,
        n_events_with_reserves_and_fee=n_with_both,
        n_rpc_calls=len(tracker.calls) - calls_before,
        elapsed_seconds=round(time.monotonic() - t0_wall, 3),
    )


@dataclass(frozen=True)
class Stage2SealResult:
    pool_mint: str
    n_buckets_total: int
    n_buckets_resolved: int
    pct_buckets_resolved: float
    n_rpc_calls: int
    elapsed_seconds: float


def seal_stage2_grid_token(
    conn: sqlite3.Connection,
    carbon: CarbonDecoderProcess,
    candidate: MigrationCandidate,
    *,
    rotator: EndpointRotator,
    tracker: RpcUsageTracker,
    source: str,
) -> Stage2SealResult:
    """Regra 4 (addendum Fase E parte 4): grade COMPLETA (migracao a
    +80min), sem orcamento de tempo -- ao contrario do benchmark do
    piloto (run_price_grid_benchmark), aqui percorre a janela inteira e
    grava cada bucket resolvido antes de reportar % de cobertura."""
    t0_wall = time.monotonic()
    calls_before = len(tracker.calls)
    window_start = candidate.migration_block_time
    window_end = window_start + POOL_TRADE_WINDOW_SECONDS

    entries = fetch_pool_signatures_in_window(
        rotator, pool_mint=candidate.pool_mint, window_start=window_start, window_end=window_end
    )
    buckets = group_successful_signatures_by_bucket(entries, window_start=window_start)
    n_buckets_total = POOL_TRADE_WINDOW_SECONDS // GRID_BUCKET_SECONDS

    raw_rows: list[dict[str, Any]] = []
    decoded_events: list[dict[str, Any]] = []
    n_resolved = 0
    for bucket_index in range(n_buckets_total):
        resolved = resolve_bucket_swap_price(rotator, carbon, buckets.get(bucket_index, []))
        if resolved is not None:
            n_resolved += 1
            raw_rows.append(resolved["raw_tx"])
            decoded_events.append(resolved["event"])

    if raw_rows:
        record_backfill_rows(
            conn,
            source=source,
            pool_mint=candidate.pool_mint,
            migration_signature=candidate.migration_signature,
            migration_block_time=window_start,
            raw_rows=raw_rows,
            decoded_events=decoded_events,
        )

    return Stage2SealResult(
        pool_mint=candidate.pool_mint,
        n_buckets_total=n_buckets_total,
        n_buckets_resolved=n_resolved,
        pct_buckets_resolved=round(100.0 * n_resolved / n_buckets_total, 2) if n_buckets_total else 0.0,
        n_rpc_calls=len(tracker.calls) - calls_before,
        elapsed_seconds=round(time.monotonic() - t0_wall, 3),
    )


def seal_block(
    *,
    block_name: str,
    start_date: str,
    end_date: str,
    k_windows: int,
    window_minutes: int,
    seed: int,
    db_path: Path,
    checkpoint_path: Path,
    rpc_url: str,
    rotator: EndpointRotator,
    tracker: RpcUsageTracker,
    carbon: CarbonDecoderProcess,
    enumeration_rpc_call: Any = fetch_migrations_in_windows,
) -> dict[str, Any]:
    """Orquestra um bloco do inicio ao fim: enumeracao (checkpointada) ->
    Estagio 1 barato pra TODO candidato achado -> hash -> sobreviventes +
    baseline (amostra aleatoria seed-fixa de nao-sobreviventes do mesmo
    tamanho) -> Estagio 2 (grade completa) -> hash -> relatorio de
    cobertura (NUNCA retorno/EV). `enumeration_rpc_call` e
    fetch_migrations_in_windows em producao; parametro injetavel so pra
    self-checks (evita rede)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    ensure_h2_backfill_schema(conn)

    checkpoint = _load_checkpoint(checkpoint_path)
    windows = sample_calendar_windows(
        start_date=start_date, end_date=end_date, window_minutes=window_minutes, k=k_windows, seed=seed
    )
    windows_done = {tuple(w) for w in checkpoint["windows_done"]}
    candidates_by_pool: dict[str, MigrationCandidate] = {
        c["pool_mint"]: MigrationCandidate(**c) for c in checkpoint["candidates"]
    }
    stage1_done: dict[str, dict[str, Any]] = checkpoint["stage1"]
    system_error_pools: list[str] = checkpoint["system_error_pools"]

    for window in windows:
        if window in windows_done:
            continue
        new_candidates = enumeration_rpc_call(rpc_url, window_start=window[0], window_end=window[1])
        for candidate in new_candidates:
            candidates_by_pool.setdefault(candidate.pool_mint, candidate)
        windows_done.add(window)
        checkpoint["windows_done"] = [list(w) for w in windows_done]
        checkpoint["candidates"] = [asdict(c) for c in candidates_by_pool.values()]
        _save_checkpoint(checkpoint_path, checkpoint)

    for pool_mint, candidate in candidates_by_pool.items():
        if pool_mint in stage1_done or pool_mint in system_error_pools:
            continue
        try:
            result = seal_stage1_token(
                conn, carbon, candidate, rotator=rotator, tracker=tracker, source=f"{block_name}_stage1"
            )
        except Exception as exc:  # noqa: BLE001 -- erro de sistema, missing explicito
            system_error_pools.append(pool_mint)
            checkpoint["system_error_pools"] = system_error_pools
            _save_checkpoint(checkpoint_path, checkpoint)
            print(f"[selagem {block_name}] token {pool_mint} erro de sistema (missing): {type(exc).__name__}: {exc}")
            continue
        stage1_done[pool_mint] = asdict(result)
        checkpoint["stage1"] = stage1_done
        _save_checkpoint(checkpoint_path, checkpoint)

    conn.commit()
    stage1_rows = conn.execute("SELECT COUNT(*) FROM sig_fast_h2_backfill_v0").fetchone()[0]
    stage1_hash_entry = _write_hash_manifest(db_path, stage="stage1", block_name=block_name, row_count=stage1_rows)

    survivors = sorted(p for p, r in stage1_done.items() if r["survived_20min_system_count"] is True)
    non_survivors = sorted(p for p, r in stage1_done.items() if r["survived_20min_system_count"] is False)
    rng = random.Random(seed)
    baseline = rng.sample(non_survivors, k=min(len(survivors), len(non_survivors)))

    stage2_done: dict[str, dict[str, Any]] = checkpoint["stage2"]
    for pool_mint in [*survivors, *baseline]:
        if pool_mint in stage2_done:
            continue
        candidate = candidates_by_pool[pool_mint]
        result2 = seal_stage2_grid_token(
            conn, carbon, candidate, rotator=rotator, tracker=tracker, source=f"{block_name}_stage2_grid"
        )
        stage2_done[pool_mint] = asdict(result2)
        checkpoint["stage2"] = stage2_done
        _save_checkpoint(checkpoint_path, checkpoint)

    conn.commit()
    stage2_rows = conn.execute("SELECT COUNT(*) FROM sig_fast_h2_backfill_v0").fetchone()[0]
    stage2_hash_entry = _write_hash_manifest(db_path, stage="stage2", block_name=block_name, row_count=stage2_rows)
    conn.close()

    n_determinable = len(stage1_done)
    n_missing = len(system_error_pools)
    stage1_results = list(stage1_done.values())
    avg_pct_decoded_with_reserves_and_fee = (
        sum(
            (100.0 * r["n_events_with_reserves_and_fee"] / r["n_events_decoded"]) if r["n_events_decoded"] else 0.0
            for r in stage1_results
        )
        / n_determinable
        if n_determinable
        else 0.0
    )
    stage2_results = list(stage2_done.values())
    avg_pct_buckets_resolved = (
        sum(r["pct_buckets_resolved"] for r in stage2_results) / len(stage2_results) if stage2_results else 0.0
    )

    return {
        "version": VERSION,
        "classification": "COVERAGE_ONLY_NO_RETURN_NO_EV_NO_MFE_NO_BARRIER",
        "block_name": block_name,
        "start_date": start_date,
        "end_date": end_date,
        "k_windows": k_windows,
        "window_minutes": window_minutes,
        "seed": seed,
        "db_path": str(db_path),
        "checkpoint_path": str(checkpoint_path),
        "stage1_hash": stage1_hash_entry,
        "stage2_hash": stage2_hash_entry,
        "n_migrations_found": len(candidates_by_pool),
        "n_tokens_system_error_missing": n_missing,
        "tokens_system_error_pools": system_error_pools,
        "n_survivors": len(survivors),
        "n_non_survivors": len(non_survivors),
        "survival_rate_system_count": (len(survivors) / n_determinable) if n_determinable else None,
        "avg_pct_decoded_with_reserves_and_fee": round(avg_pct_decoded_with_reserves_and_fee, 2),
        "n_baseline_sampled": len(baseline),
        "baseline_pools": baseline,
        "avg_pct_buckets_resolved_stage2": round(avg_pct_buckets_resolved, 2),
        "n_stage2_tokens_sealed": len(stage2_results),
        "total_rpc_calls": len(tracker.calls),
        "total_credits": tracker.total_credits,
        "total_elapsed_seconds_stage1": round(sum(r["elapsed_seconds"] for r in stage1_results), 1),
        "total_elapsed_seconds_stage2": round(sum(r["elapsed_seconds"] for r in stage2_results), 1),
    }


def _self_check() -> None:
    import tempfile

    pool_a = "POOLApump"  # sobrevive
    pool_b = "POOLBpump"  # nao-sobrevive (baixo volume) -- vira baseline
    pool_c = "POOLCpump"  # erro de sistema na propria lista de assinaturas
    window_start_a = 10_000
    window_start_b = 20_000
    marker = SIGNAL_MARKER_SECONDS

    def _fake_swap_tx(signature: str, block_time: int) -> dict[str, Any]:
        from benchmarks.carbon_decoder_parity_v1.parity import (
            PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
            PUMPSWAP_PROGRAM_ID,
        )
        import base64 as _b64

        payload = _b64.b64encode(PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"\x00" * 16).decode("ascii")
        return {
            "slot": 1,
            "blockTime": block_time,
            "transaction": {"signatures": [signature], "message": {"accountKeys": [PUMPSWAP_PROGRAM_ID]}},
            "meta": {
                "logMessages": [
                    f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
                    f"Program data: {payload}",
                    f"Program {PUMPSWAP_PROGRAM_ID} success",
                ]
            },
        }

    sig_t0_a = "SIG_T0_A"
    sig_marker_a = "SIG_MARKER_A"
    last5min_a = [f"SIG_A_LAST5MIN_{i}" for i in range(MIN_SUCCESSFUL_TRADES_LAST_5MIN_FOR_SURVIVOR)]
    raw_rows_by_sig = {
        sig_t0_a: _fake_swap_tx(sig_t0_a, window_start_a),
        sig_marker_a: _fake_swap_tx(sig_marker_a, window_start_a + marker),
    }
    # Estagio 2 (grade completa) visita TODOS os buckets, incluindo os dos
    # trades do "ultimos 5min" que o Estagio 1 nunca precisou consultar
    # (so olhou bucket 0 e o bucket do marco) -- precisam de tx fake tambem.
    for i, sig in enumerate(last5min_a):
        raw_rows_by_sig[sig] = _fake_swap_tx(sig, window_start_a + marker - 290 + i * 10)
    raw_rows_by_sig["SIG_B_1"] = _fake_swap_tx("SIG_B_1", window_start_b + marker - 100)
    raw_rows_by_sig["SIG_B_2"] = _fake_swap_tx("SIG_B_2", window_start_b + marker - 50)

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSignaturesForAddress":
            pool_mint = params[0]
            if pool_mint == pool_a:
                rows = [{"signature": sig_t0_a, "blockTime": window_start_a, "err": None}]
                for i, sig in enumerate(last5min_a):
                    rows.append(
                        {"signature": sig, "blockTime": window_start_a + marker - 290 + i * 10, "err": None}
                    )
                rows.append({"signature": sig_marker_a, "blockTime": window_start_a + marker, "err": None})
                return {"result": rows}
            if pool_mint == pool_b:
                return {
                    "result": [
                        {"signature": "SIG_B_1", "blockTime": window_start_b + marker - 100, "err": None},
                        {"signature": "SIG_B_2", "blockTime": window_start_b + marker - 50, "err": None},
                    ]
                }
            if pool_mint == pool_c:
                raise RuntimeError("falha simulada na lista de assinaturas")
            raise AssertionError(f"unexpected pool_mint: {pool_mint}")
        if method == "getTransaction":
            signature = params[0]
            row = raw_rows_by_sig.get(signature)
            if row is None:
                raise AssertionError(f"unexpected getTransaction for {signature}")
            return {"result": row}
        raise AssertionError(f"unexpected RPC call in self-check: {method} {params}")

    class _FakeCarbon:
        def request(self, payload: dict[str, Any]) -> dict[str, Any]:
            event_key = payload["items"][0]["event_key"]
            signature = event_key.split(":")[0]
            reserves = {sig_t0_a: (1000, 600), sig_marker_a: (500, 900)}.get(signature, (100, 100))
            return {
                "type": "carbon_canonical_batch",
                "batch_id": payload["batch_id"],
                "items": [
                    {
                        "event_key": event_key,
                        "status": "decoded",
                        "event_type": "pumpswap_buy",
                        "signature": signature,
                        "pool_base_token_reserves_raw": reserves[0],
                        "pool_quote_token_reserves_raw": reserves[1],
                        "lp_fee_raw": 7,
                    }
                ],
            }

    def fake_enumeration(rpc_url: str, *, window_start: int, window_end: int) -> list[MigrationCandidate]:
        return [
            MigrationCandidate(pool_mint=pool_a, migration_signature="SIGMIGA", migration_block_time=window_start_a),
            MigrationCandidate(pool_mint=pool_b, migration_signature="SIGMIGB", migration_block_time=window_start_b),
            MigrationCandidate(pool_mint=pool_c, migration_signature="SIGMIGC", migration_block_time=30_000),
        ]

    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "self_check.db"
        checkpoint_path = Path(tmp) / "self_check_checkpoint.json"
        with patch(
            "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
            side_effect=fake_rpc,
        ):
            tracker = RpcUsageTracker()
            rotator = EndpointRotator(["fake://rpc"])
            report = seal_block(
                block_name="self_check",
                start_date="2026-01-01",
                end_date="2026-01-02",
                k_windows=1,
                window_minutes=10,
                seed=20261008,
                db_path=db_path,
                checkpoint_path=checkpoint_path,
                rpc_url="fake://rpc",
                rotator=rotator,
                tracker=tracker,
                carbon=_FakeCarbon(),
                enumeration_rpc_call=fake_enumeration,
            )

        assert report["n_migrations_found"] == 3, report
        assert report["n_tokens_system_error_missing"] == 1, report
        assert report["tokens_system_error_pools"] == [pool_c], report
        assert report["n_survivors"] == 1, report
        assert report["n_non_survivors"] == 1, report
        assert report["survival_rate_system_count"] == 0.5, report
        assert report["n_baseline_sampled"] == 1, report
        assert report["baseline_pools"] == [pool_b], report
        assert report["n_stage2_tokens_sealed"] == 2, report
        # Regra 5: hash commitado, e DIFERENTE entre os dois estagios
        # (estagio 2 grava mais linhas que o estagio 1).
        assert report["stage1_hash"]["sha256"] != report["stage2_hash"]["sha256"], report
        assert report["stage2_hash"]["row_count_sig_fast_h2_backfill_v0"] >= report["stage1_hash"][
            "row_count_sig_fast_h2_backfill_v0"
        ], report
        assert db_path.exists(), "banco deveria ter sido criado"
        assert db_path.with_suffix(db_path.suffix + ".hashes.jsonl").exists(), "manifesto de hash deveria existir"

        # Resumir de novo (checkpoint ja preenchido) nao deveria levantar
        # nem duplicar linhas -- idempotente.
        with patch(
            "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
            side_effect=fake_rpc,
        ):
            tracker2 = RpcUsageTracker()
            rotator2 = EndpointRotator(["fake://rpc"])
            report2 = seal_block(
                block_name="self_check",
                start_date="2026-01-01",
                end_date="2026-01-02",
                k_windows=1,
                window_minutes=10,
                seed=20261008,
                db_path=db_path,
                checkpoint_path=checkpoint_path,
                rpc_url="fake://rpc",
                rotator=rotator2,
                tracker=tracker2,
                carbon=_FakeCarbon(),
                enumeration_rpc_call=fake_enumeration,
            )
        assert tracker2.calls == [], "resume do checkpoint nao deveria gastar nenhuma chamada nova"
        assert report2["stage2_hash"]["row_count_sig_fast_h2_backfill_v0"] == report["stage2_hash"][
            "row_count_sig_fast_h2_backfill_v0"
        ], (report, report2)

    print(
        "self-check OK: seal_block (enumeracao + Estagio 1 com missing explicito + hash + "
        "baseline seed-fixa + Estagio 2 grade completa + hash + cobertura, sem retorno/EV) + "
        "resume idempotente do checkpoint"
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
        "Modulo compartilhado, sem entrypoint de producao proprio -- ver "
        "h2_seal_discovery_v0.py / h2_seal_confirmation_v0.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
