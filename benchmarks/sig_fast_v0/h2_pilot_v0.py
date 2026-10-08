"""SIG-FAST H2 piloto -- step A (rev. 4, 2026-10-08 operator review).

Pure systems check: measures Helius cost and decode coverage on migrations
SAMPLED OUTSIDE the frozen discovery/confirmation calendar blocks. Never
reads a return, never touches the sealed blocks, never spends a hypothesis
attempt (registry rule 5). The one price-derived number this script computes
(20-minute MemeTrans survival, as a 0/1 system count) was explicitly
authorized by the operator for N-sizing only -- "a taxa de sobrevivencia do
piloto e contagem de sistema, nao retorno" -- and is never used to judge H2
itself; step B (real download) and any EV/PF/edge computation stay gated
behind the operator's separate OK on the coverage report.

See docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md (rev. 4,
"Regras anti-vies do discovery historico de H2") for the frozen protocol.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.move_first_h_coverage_audit_v0 import sample_migration_account as _mfh
from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import (
    CarbonDecoderProcess,
    MigrationCandidate,
    POOL_TRADE_WINDOW_SECONDS,
    SIGNAL_MARKER_SECONDS,
    _load_rpc_url,
    decode_historical_trades,
    fetch_migrations_in_range,
    fetch_pool_trades_raw,
    sample_migrations_excluding_blocks,
)
from src.opportunity_path_metrics_v0 import PathTrade, mid_price_sol

VERSION = "sig_fast_h2_pilot_v0"

# DRAFT rev. 4, regra 2 -- blocos congelados, o piloto nunca os toca.
DISCOVERY_BLOCK_START = "2026-08-20"
DISCOVERY_BLOCK_END = "2026-09-17"
CONFIRMATION_BLOCK_START = "2026-09-24"
CONFIRMATION_BLOCK_END = "2026-10-08"
PILOT_SEED = 20261008
PILOT_N_DEFAULT = 10
# Lookback pro universo de ONDE sortear o piloto: janela ampla e anterior ao
# embargo, deliberadamente sem overlap mesmo por acidente (ver regra 2).
PILOT_LOOKBACK_START = "2026-07-21"  # pos-BOOST, mesmo piso do resto da rodada
PILOT_LOOKBACK_END = DISCOVERY_BLOCK_START

# Helius pricing (helius.dev/docs/billing/credits, lido 2026-10-08 via
# WebFetch; a pagina nao mostra data/versao -- ver handoff pra a ressalva
# completa sobre fontes conflitantes encontradas em paginas de outros
# idiomas). getTransaction / getSignaturesForAddress = 1 credito flat (nao
# usados neste piloto). getTransactionsForAddress = 10 creditos por bloco
# iniciado de 100 transacoes completas retornadas.
HELIUS_CREDITS_PER_BLOCK = 10
HELIUS_BLOCK_SIZE = 100


def _credits_for_tx_count(n_tx: int) -> int:
    if n_tx <= 0:
        return 0
    return HELIUS_CREDITS_PER_BLOCK * math.ceil(n_tx / HELIUS_BLOCK_SIZE)


def _date_epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def resolve_migration_block_time(rpc_url: str, signature: str) -> int:
    """The real on-chain instant of the migration tx -- fetch_day_classified
    only gives a day-granularity placeholder (see h2_historical_backfill_v0.
    _day_start_epoch); the piloto/real fetch need the exact second."""
    result = _mfh._rpc(
        rpc_url,
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )
    tx = result.get("result")
    if tx is None or tx.get("blockTime") is None:
        raise RuntimeError(f"could not resolve blockTime for migration signature {signature}")
    return int(tx["blockTime"])


@dataclass(frozen=True)
class PilotTokenResult:
    pool_mint: str
    migration_signature: str
    migration_block_time: int
    n_tx_in_window: int
    n_events_decoded: int
    n_events_with_reserves_and_fee: int
    pct_decoded_with_reserves_and_fee: float
    estimated_credits: int
    survived_20min_system_count: bool | None


def _survival_system_count(
    decoded_events: list[dict[str, Any]],
    signature_to_block_time: dict[str, int],
    *,
    migration_block_time: int,
) -> bool | None:
    """MemeTrans 20-minute survival proxy, operator-authorized as a system
    count for N-sizing only (never an H2 verdict input). price(T0) from the
    first decoded swap in the window; price(marker) from the last decoded
    swap at or before migration+20min. None if either side is missing --
    never inferred as 0."""
    swaps = [
        event
        for event in decoded_events
        if event.get("status") == "decoded"
        and event.get("event_type") in ("pumpswap_buy", "pumpswap_sell")
        and event.get("pool_base_token_reserves_raw") is not None
        and event.get("pool_quote_token_reserves_raw") is not None
    ]
    if not swaps:
        return None
    marker = migration_block_time + SIGNAL_MARKER_SECONDS
    ordered = sorted(
        swaps, key=lambda event: signature_to_block_time.get(str(event.get("signature")), 0)
    )
    first = ordered[0]
    at_or_before_marker = [
        event
        for event in ordered
        if signature_to_block_time.get(str(event.get("signature")), 0) <= marker
    ]
    if not at_or_before_marker:
        return None
    last_before_marker = at_or_before_marker[-1]

    price_first = mid_price_sol(
        PathTrade(
            chain_time=0,
            venue="pumpswap",
            base_reserves_raw=first["pool_base_token_reserves_raw"],
            quote_reserves_raw=first["pool_quote_token_reserves_raw"],
        )
    )
    price_marker = mid_price_sol(
        PathTrade(
            chain_time=0,
            venue="pumpswap",
            base_reserves_raw=last_before_marker["pool_base_token_reserves_raw"],
            quote_reserves_raw=last_before_marker["pool_quote_token_reserves_raw"],
        )
    )
    if price_first is None or price_marker is None or price_first <= 0:
        return None
    return (price_marker / price_first) >= 0.40


def run_pilot_token(
    rpc_url: str, carbon: CarbonDecoderProcess, candidate: MigrationCandidate
) -> PilotTokenResult:
    migration_block_time = resolve_migration_block_time(rpc_url, candidate.migration_signature)
    raw_rows = fetch_pool_trades_raw(
        rpc_url,
        pool_mint=candidate.pool_mint,
        window_start=migration_block_time,
        window_end=migration_block_time + POOL_TRADE_WINDOW_SECONDS,
    )
    decoded = decode_historical_trades(carbon, raw_rows, batch_id=1)
    n_decoded = sum(1 for event in decoded if event.get("status") == "decoded")
    n_with_both = sum(
        1
        for event in decoded
        if event.get("status") == "decoded"
        and event.get("pool_base_token_reserves_raw") is not None
        and (event.get("lp_fee_raw") is not None or event.get("fee_raw") is not None)
    )
    pct = round(100.0 * n_with_both / len(decoded), 2) if decoded else 0.0
    signature_to_block_time = {
        row["transaction"]["signatures"][0]: row.get("blockTime") for row in raw_rows
    }

    return PilotTokenResult(
        pool_mint=candidate.pool_mint,
        migration_signature=candidate.migration_signature,
        migration_block_time=migration_block_time,
        n_tx_in_window=len(raw_rows),
        n_events_decoded=n_decoded,
        n_events_with_reserves_and_fee=n_with_both,
        pct_decoded_with_reserves_and_fee=pct,
        estimated_credits=_credits_for_tx_count(len(raw_rows)),
        survived_20min_system_count=_survival_system_count(
            decoded, signature_to_block_time, migration_block_time=migration_block_time
        ),
    )


@dataclass(frozen=True)
class PilotSummary:
    n_sampled: int
    n_with_any_trade: int
    avg_tx_per_window: float
    avg_credits_per_token: float
    avg_pct_decoded_with_reserves_and_fee: float
    n_survived_system_count: int
    n_survival_determinable: int
    survival_rate_system_count: float | None
    estimated_credits_for_n_30_survivors: int | None
    proposed_n_migrations_to_sample: int | None


def summarize_pilot(results: list[PilotTokenResult]) -> PilotSummary:
    n = len(results)
    with_trade = [r for r in results if r.n_tx_in_window > 0]
    determinable = [r for r in results if r.survived_20min_system_count is not None]
    survived = [r for r in determinable if r.survived_20min_system_count]
    survival_rate = (len(survived) / len(determinable)) if determinable else None

    estimated_credits_for_30 = None
    proposed_n = None
    if survival_rate and survival_rate > 0 and with_trade:
        avg_credits = sum(r.estimated_credits for r in with_trade) / len(with_trade)
        proposed_n = math.ceil(30 / survival_rate)
        estimated_credits_for_30 = math.ceil(proposed_n * avg_credits)

    return PilotSummary(
        n_sampled=n,
        n_with_any_trade=len(with_trade),
        avg_tx_per_window=(sum(r.n_tx_in_window for r in results) / n) if n else 0.0,
        avg_credits_per_token=(sum(r.estimated_credits for r in results) / n) if n else 0.0,
        avg_pct_decoded_with_reserves_and_fee=(
            sum(r.pct_decoded_with_reserves_and_fee for r in with_trade) / len(with_trade)
            if with_trade
            else 0.0
        ),
        n_survived_system_count=len(survived),
        n_survival_determinable=len(determinable),
        survival_rate_system_count=survival_rate,
        estimated_credits_for_n_30_survivors=estimated_credits_for_30,
        proposed_n_migrations_to_sample=proposed_n,
    )


def _self_check_credits_formula() -> None:
    # Matches the worked examples on helius.dev/docs/billing/credits (read
    # 2026-10-08): 1-100 full tx = 10 credits (one started block, minimum);
    # 250 = 30; 1000 = 100.
    assert _credits_for_tx_count(0) == 0
    assert _credits_for_tx_count(1) == 10
    assert _credits_for_tx_count(100) == 10
    assert _credits_for_tx_count(101) == 20
    assert _credits_for_tx_count(250) == 30
    assert _credits_for_tx_count(1000) == 100


def _self_check_survival() -> None:
    migration_block_time = 1_000_000
    sig_a, sig_b, sig_c = "SIGA", "SIGB", "SIGC"
    signature_to_block_time = {
        sig_a: migration_block_time,
        sig_b: migration_block_time + SIGNAL_MARKER_SECONDS - 10,
        sig_c: migration_block_time + SIGNAL_MARKER_SECONDS + 999_999,  # after marker, ignored
    }

    def _swap(signature: str, base_reserves: int, quote_reserves: int) -> dict[str, Any]:
        return {
            "status": "decoded",
            "event_type": "pumpswap_buy",
            "signature": signature,
            "pool_base_token_reserves_raw": base_reserves,
            "pool_quote_token_reserves_raw": quote_reserves,
        }

    # Survives: price at marker (quote/base = 60/1000=0.06) is exactly the
    # same as at migration (600/10000=0.06) -- ratio 1.0 >= 0.40.
    survived = _survival_system_count(
        [_swap(sig_a, 10_000, 600), _swap(sig_b, 10_000, 600)],
        signature_to_block_time,
        migration_block_time=migration_block_time,
    )
    assert survived is True, survived

    # Dies: price at marker is 10% of price at migration -- ratio 0.10 < 0.40.
    died = _survival_system_count(
        [_swap(sig_a, 10_000, 600), _swap(sig_b, 10_000, 60)],
        signature_to_block_time,
        migration_block_time=migration_block_time,
    )
    assert died is False, died

    # Undeterminable: no swap at or before the marker (sig_c is after it).
    undeterminable = _survival_system_count(
        [_swap(sig_c, 10_000, 600)],
        signature_to_block_time,
        migration_block_time=migration_block_time,
    )
    assert undeterminable is None, undeterminable

    # Undeterminable: no swaps at all.
    assert _survival_system_count([], signature_to_block_time, migration_block_time=migration_block_time) is None


def _self_check_summary() -> None:
    results = [
        PilotTokenResult("P1", "S1", 0, 50, 50, 50, 100.0, 10, True),
        PilotTokenResult("P2", "S2", 0, 150, 150, 150, 100.0, 20, False),
        PilotTokenResult("P3", "S3", 0, 0, 0, 0, 0.0, 0, None),
    ]
    summary = summarize_pilot(results)
    assert summary.n_sampled == 3, summary
    assert summary.n_with_any_trade == 2, summary
    assert summary.n_survival_determinable == 2, summary
    assert summary.n_survived_system_count == 1, summary
    assert summary.survival_rate_system_count == 0.5, summary
    # proposed_n = ceil(30 / 0.5) = 60; avg credits over tokens WITH a trade
    # (10, 20) = 15; estimated = ceil(60 * 15) = 900.
    assert summary.proposed_n_migrations_to_sample == 60, summary
    assert summary.estimated_credits_for_n_30_survivors == 900, summary


def _self_check_run_pilot_token_wiring() -> None:
    from unittest.mock import patch

    migration_sig = "SIGMIGRATION"
    pool_mint = "POOLpump"
    migration_block_time = 2_000_000
    trade_sig = "SIGTRADE1"

    def fake_rpc(rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getTransaction":
            assert params[0] == migration_sig
            return {"result": {"blockTime": migration_block_time}}
        if method == "getTransactionsForAddress":
            assert params[0] == pool_mint
            from benchmarks.carbon_decoder_parity_v1.parity import (
                PUMPSWAP_BUY_EVENT_DISCRIMINATOR,
                PUMPSWAP_PROGRAM_ID,
            )
            import base64 as _b64

            payload = _b64.b64encode(PUMPSWAP_BUY_EVENT_DISCRIMINATOR + b"\x00" * 16).decode("ascii")
            row = {
                "transaction": {"signatures": [trade_sig], "message": {"accountKeys": [PUMPSWAP_PROGRAM_ID]}},
                "slot": 42,
                "blockTime": migration_block_time + 10,
                "meta": {
                    "logMessages": [
                        f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
                        f"Program data: {payload}",
                        f"Program {PUMPSWAP_PROGRAM_ID} success",
                    ]
                },
            }
            return {"result": {"data": [row], "paginationToken": None}}
        raise AssertionError(f"unexpected RPC method in self-check: {method}")

    class _FakeCarbon:
        def request(self, payload: dict[str, Any]) -> dict[str, Any]:
            event_key = payload["items"][0]["event_key"]
            return {
                "type": "carbon_canonical_batch",
                "batch_id": payload["batch_id"],
                "items": [
                    {
                        "event_key": event_key,
                        "status": "decoded",
                        "event_type": "pumpswap_buy",
                        "signature": trade_sig,
                        "pool_base_token_reserves_raw": 500,
                        "pool_quote_token_reserves_raw": 600,
                        "lp_fee_raw": 7,
                    }
                ],
            }

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc",
        side_effect=fake_rpc,
    ):
        result = run_pilot_token(
            "fake://rpc",
            _FakeCarbon(),
            MigrationCandidate(
                pool_mint=pool_mint, migration_signature=migration_sig, migration_block_time=0
            ),
        )
    assert result.migration_block_time == migration_block_time, result
    assert result.n_tx_in_window == 1, result
    assert result.n_events_decoded == 1, result
    assert result.n_events_with_reserves_and_fee == 1, result
    assert result.pct_decoded_with_reserves_and_fee == 100.0, result
    assert result.estimated_credits == 10, result


def _self_check() -> None:
    _self_check_credits_formula()
    _self_check_survival()
    _self_check_summary()
    _self_check_run_pilot_token_wiring()
    print("self-check OK: credits formula + survival system-count + summary arithmetic + run_pilot_token wiring")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--n", type=int, default=PILOT_N_DEFAULT)
    parser.add_argument("--seed", type=int, default=PILOT_SEED)
    parser.add_argument("--lookback-start", default=PILOT_LOOKBACK_START)
    parser.add_argument("--lookback-end", default=PILOT_LOOKBACK_END)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts/sig_fast_h2_pilot_v0/report.json")
    )
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    rpc_url = _load_rpc_url()
    candidates = fetch_migrations_in_range(
        rpc_url, start_date=args.lookback_start, end_date=args.lookback_end
    )
    sample = sample_migrations_excluding_blocks(
        candidates,
        n=args.n,
        seed=args.seed,
        excluded_block_starts=(
            _date_epoch(DISCOVERY_BLOCK_START),
            _date_epoch(CONFIRMATION_BLOCK_START),
        ),
        excluded_block_ends=(
            _date_epoch(DISCOVERY_BLOCK_END),
            _date_epoch(CONFIRMATION_BLOCK_END),
        ),
    )

    from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
        JsonLineProcess,
        _carbon_command,
    )

    carbon = JsonLineProcess(_carbon_command(args.cargo), ready_type="carbon_stream_decoder_ready")
    carbon.start()
    try:
        results = [run_pilot_token(rpc_url, carbon, candidate) for candidate in sample]
    finally:
        carbon.close()

    summary = summarize_pilot(results)
    payload = {
        "version": VERSION,
        "classification": "SYSTEMS_COST_AND_COVERAGE_ONLY_NOT_AN_ECONOMIC_TEST",
        "seed": args.seed,
        "lookback_start": args.lookback_start,
        "lookback_end": args.lookback_end,
        "excluded_blocks": {
            "discovery": [DISCOVERY_BLOCK_START, DISCOVERY_BLOCK_END],
            "confirmation": [CONFIRMATION_BLOCK_START, CONFIRMATION_BLOCK_END],
        },
        "tokens": [asdict(r) for r in results],
        "summary": asdict(summary),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
