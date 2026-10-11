"""Addendum DRAFT 2026-10-11 (correcao de implementacao do gate de
cobertura, decisao do operador) -- recomputa SOMENTE o denominador de
buckets que o `Stage2SealResult` antigo nunca guardou (quantos buckets de
5s tinham >=1 transacao bem-sucedida), para o bloco de discovery JA
selado, SEM tocar em nenhum preco/economico.

READ-ONLY, mesma chamada ja usada em producao (`getSignaturesForAddress`
via `fetch_pool_signatures_in_window`, 1 credito), mesmos pools e mesmas
janelas de 80min ja congeladas -- nenhum pool novo, nenhuma janela nova,
nenhum `getTransaction`/decode novo (os precos ja resolvidos continuam
exatamente os do banco selado, hash-verificado). Classificado
COVERAGE_ONLY, igual ao resto da Fase 3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.sig_fast_v0.h2_block_seal_v0 import (
    _avg_pct_decoded_with_reserves_and_fee,
    _hash_file,
    _pooled_pct_buckets_resolved,
)
from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import (
    EndpointRotator,
    GRID_BUCKET_SECONDS,
    POOL_TRADE_WINDOW_SECONDS,
    fetch_pool_signatures_in_window,
    group_successful_signatures_by_bucket,
)

VERSION = "h2_coverage_recount_v0"


def count_buckets_with_tx(
    rotator: EndpointRotator,
    *,
    pool_mint: str,
    window_start: int,
    window_seconds: int = POOL_TRADE_WINDOW_SECONDS,
    bucket_seconds: int = GRID_BUCKET_SECONDS,
) -> int:
    """So conta quantos buckets de `bucket_seconds` tem >=1 transacao
    BEM-SUCEDIDA -- nunca chama getTransaction/decode. Mesma janela e
    mesma chamada ja usadas por `seal_stage2_grid_token`, so sem o passo
    de resolucao de preco (esse ja esta no banco selado)."""
    entries = fetch_pool_signatures_in_window(
        rotator, pool_mint=pool_mint, window_start=window_start, window_end=window_start + window_seconds
    )
    buckets = group_successful_signatures_by_bucket(
        entries, window_start=window_start, bucket_seconds=bucket_seconds
    )
    return len(buckets)


def recount_bucket_denominators(
    rotator: EndpointRotator,
    *,
    stage1_done: dict[str, dict[str, Any]],
    stage2_done: dict[str, dict[str, Any]],
    db_path: Path,
    output_path: Path,
) -> dict[str, int]:
    """Para cada pool ja selado no Estagio 2, recupera (read-only) quantos
    buckets tinham >=1 transacao -- a unica informacao que o
    `Stage2SealResult` antigo nao guardava. Grava o hash do banco selado
    (deve continuar inalterado, confere separadamente) + o resultado ANTES
    de qualquer calculo de cobertura corrigido."""
    db_hash = _hash_file(db_path)
    counts: dict[str, int] = {}
    for pool_mint in stage2_done:
        migration_block_time = stage1_done[pool_mint]["migration_block_time"]
        counts[pool_mint] = count_buckets_with_tx(rotator, pool_mint=pool_mint, window_start=migration_block_time)
    manifest = {
        "version": VERSION,
        "db_path": str(db_path),
        "db_sha256": db_hash,
        "n_pools_recounted": len(counts),
        "n_buckets_with_tx_by_pool": counts,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    return counts


def build_corrected_report(
    coverage_report: dict[str, Any],
    checkpoint: dict[str, Any],
    bucket_with_tx_by_pool: dict[str, int],
) -> dict[str, Any]:
    """Monta um `report` corrigido pronto pra `evaluate_coverage_gate`,
    reaproveitando as funcoes puras ja corrigidas em `h2_block_seal_v0.py`
    (nenhuma logica nova aqui, so combinacao dos dados ja selados + a
    contagem recuperada por `recount_bucket_denominators`)."""
    stage1_done = checkpoint["stage1"]
    stage2_done_old = checkpoint["stage2"]

    stage2_done_corrected = {}
    for pool, old in stage2_done_old.items():
        n_with_tx = bucket_with_tx_by_pool[pool]
        stage2_done_corrected[pool] = {
            **old,
            "n_buckets_with_tx": n_with_tx,
            "n_buckets_carried_forward": old["n_buckets_total"] - n_with_tx,
        }

    survivors = sorted(p for p, r in stage1_done.items() if r["survived_20min_system_count"] is True)
    baseline = coverage_report["baseline_pools"]

    stage1_results = list(stage1_done.values())
    avg_reserves_fee, n_no_attempt = _avg_pct_decoded_with_reserves_and_fee(stage1_results)
    pct_total, n_resolved_total, n_with_tx_total = _pooled_pct_buckets_resolved(
        stage2_done_corrected.keys(), stage2_done_corrected
    )
    pct_signal, n_resolved_signal, n_with_tx_signal = _pooled_pct_buckets_resolved(survivors, stage2_done_corrected)
    pct_baseline, n_resolved_baseline, n_with_tx_baseline = _pooled_pct_buckets_resolved(
        baseline, stage2_done_corrected
    )
    n_carried_total = sum(r["n_buckets_carried_forward"] for r in stage2_done_corrected.values())

    corrected = dict(coverage_report)
    corrected["avg_pct_decoded_with_reserves_and_fee"] = avg_reserves_fee
    corrected["n_tokens_no_decode_attempt"] = n_no_attempt
    corrected["avg_pct_buckets_resolved_stage2"] = pct_total
    corrected["pct_buckets_resolved_signal_group"] = pct_signal
    corrected["pct_buckets_resolved_baseline_group"] = pct_baseline
    corrected["n_buckets_resolved_total"] = n_resolved_total
    corrected["n_buckets_with_tx_total"] = n_with_tx_total
    corrected["n_buckets_resolved_signal_group"] = n_resolved_signal
    corrected["n_buckets_with_tx_signal_group"] = n_with_tx_signal
    corrected["n_buckets_resolved_baseline_group"] = n_resolved_baseline
    corrected["n_buckets_with_tx_baseline_group"] = n_with_tx_baseline
    corrected["n_buckets_carried_forward_total"] = n_carried_total
    corrected["classification"] = "COVERAGE_ONLY_CORRECTED_IMPLEMENTATION_2026_10_11"
    return corrected


# ------------------------------ self-check -----------------------------


class _FakeRotator:
    """Fake de `EndpointRotator.call` -- sem rede. `signatures_by_pool`
    mapeia pool_mint -> lista de (signature, block_time, failed)."""

    def __init__(self, signatures_by_pool: dict[str, list[tuple[str, int, bool]]]):
        self._signatures_by_pool = signatures_by_pool

    def call(self, method: str, params: list) -> dict[str, Any]:
        assert method == "getSignaturesForAddress", method
        pool_mint = params[0]
        before = params[1].get("before")
        all_entries = self._signatures_by_pool.get(pool_mint, [])
        # mais novo primeiro (mesma ordem real de getSignaturesForAddress).
        ordered = sorted(all_entries, key=lambda e: e[1], reverse=True)
        if before is not None:
            idx = next(i for i, e in enumerate(ordered) if e[0] == before)
            ordered = ordered[idx + 1 :]
        page = ordered[:1000]
        return {
            "result": [
                {"signature": sig, "blockTime": bt, "err": ({"InstructionError": []} if failed else None)}
                for sig, bt, failed in page
            ]
        }


def _self_check() -> None:
    import tempfile

    window_start = 100_000
    bucket_seconds = GRID_BUCKET_SECONDS
    # SIG1pump: 1 tx bem-sucedida em cada um de 3 buckets distintos.
    sig1_sigs = [
        (f"sig1-{i}", window_start + i * bucket_seconds, False) for i in range(3)
    ]
    # BASE1pump: nenhuma transacao (token morto na grade inteira).
    base1_sigs: list[tuple[str, int, bool]] = []
    # BASE2pump: 2 buckets com tx, mas uma delas falhou (err != None) --
    # nao conta pro denominador (so BEM-SUCEDIDA conta).
    base2_sigs = [
        ("base2-ok", window_start + 0 * bucket_seconds, False),
        ("base2-failed", window_start + 1 * bucket_seconds, True),
    ]
    rotator = _FakeRotator(
        {"SIG1pump": sig1_sigs, "BASE1pump": base1_sigs, "BASE2pump": base2_sigs}
    )

    assert count_buckets_with_tx(rotator, pool_mint="SIG1pump", window_start=window_start, window_seconds=20) == 3
    assert count_buckets_with_tx(rotator, pool_mint="BASE1pump", window_start=window_start, window_seconds=20) == 0
    # so 1 bucket conta (a falha nao gera entrada em group_successful_signatures_by_bucket).
    assert count_buckets_with_tx(rotator, pool_mint="BASE2pump", window_start=window_start, window_seconds=20) == 1

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fake.db"
        db_path.write_bytes(b"fake discovery.db contents")
        output_path = Path(tmp) / "recount.json"

        stage1_done = {
            "SIG1pump": {
                "migration_block_time": window_start,
                "survived_20min_system_count": True,
                "n_events_decoded": 2,
                "n_events_with_reserves_and_fee": 2,
            },
            "BASE1pump": {
                "migration_block_time": window_start,
                "survived_20min_system_count": False,
                "n_events_decoded": 0,
                "n_events_with_reserves_and_fee": 0,
            },
            "BASE2pump": {
                "migration_block_time": window_start,
                "survived_20min_system_count": False,
                "n_events_decoded": 0,
                "n_events_with_reserves_and_fee": 0,
            },
        }
        stage2_done = {
            "SIG1pump": {"n_buckets_total": 20, "n_buckets_resolved": 3},
            "BASE1pump": {"n_buckets_total": 20, "n_buckets_resolved": 0},
            "BASE2pump": {"n_buckets_total": 20, "n_buckets_resolved": 1},
        }
        counts = recount_bucket_denominators(
            rotator, stage1_done=stage1_done, stage2_done=stage2_done, db_path=db_path, output_path=output_path
        )
        assert counts == {"SIG1pump": 3, "BASE1pump": 0, "BASE2pump": 1}, counts

        manifest = json.loads(output_path.read_text(encoding="utf-8"))
        assert manifest["db_sha256"] == _hash_file(db_path)
        assert manifest["n_pools_recounted"] == 3

        coverage_report = {
            "baseline_pools": ["BASE1pump", "BASE2pump"],
            "n_migrations_found": 3,
            "aborted": False,
        }
        checkpoint = {"stage1": stage1_done, "stage2": stage2_done}
        corrected = build_corrected_report(coverage_report, checkpoint, counts)

        # sinal (so SIG1): 3 resolvidos / 3 com-tx = 100%.
        assert corrected["pct_buckets_resolved_signal_group"] == 100.0, corrected
        # baseline (BASE1 ignorado, 0 com-tx; BASE2: 1/1): 1 resolvido / 1 com-tx = 100%.
        assert corrected["pct_buckets_resolved_baseline_group"] == 100.0, corrected
        # total (BASE1 ainda ignorado): (3+1)/(3+1) = 100%.
        assert corrected["avg_pct_buckets_resolved_stage2"] == 100.0, corrected
        # carregados: SIG1 17 + BASE1 20 + BASE2 19 = 56.
        assert corrected["n_buckets_carried_forward_total"] == 56, corrected
        # campos originais do coverage_report preservados.
        assert corrected["n_migrations_found"] == 3
        assert corrected["classification"] == "COVERAGE_ONLY_CORRECTED_IMPLEMENTATION_2026_10_11"

    print(
        "self-check OK: contagem de buckets-com-tx isolada (so transacao BEM-SUCEDIDA conta, "
        "token morto da 0, falha nao conta) + manifesto com hash do banco gravado antes do "
        "numero + relatorio corrigido monta corretamente total/sinal/baseline pooled"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print("Modulo de recomputacao -- sem entrypoint de producao proprio (chamado manualmente contra o banco real).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
