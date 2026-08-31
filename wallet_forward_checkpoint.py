import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.causal_quote_store import load_causal_quotes
from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_causal_replay import (
    WalletCausalReplayConfig,
    replay_wallet_actions,
    summarize_wallet_causal_replay,
)
from src.wallet_forward_metrics import (
    summarize_forward_wallet_latency,
    summarize_forward_wallet_latency_by_address,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import (
    WalletForwardRun,
    get_wallet_forward_run,
    latest_wallet_forward_run,
)
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import load_successful_quote_keys_by_event


DEFAULT_DELAYS = (0, 15, 30, 60, 120)


@dataclass(frozen=True)
class ScopedForwardObservation:
    id: int
    observation_key: str
    action: WalletActionObservation


def _load_addresses(path_value: str) -> list[str]:
    path = Path(path_value)
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    addresses = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not addresses:
        raise ValueError("arquivo da coorte está vazio")
    return list(dict.fromkeys(addresses))


def _load_scoped_observations(
    addresses: list[str] | tuple[str, ...],
    *,
    after_id: int = 0,
    through_id: int | None = None,
) -> list[ScopedForwardObservation]:
    if after_id < 0:
        raise ValueError("after_id must be non-negative")
    if through_id is not None and through_id < after_id:
        raise ValueError("through_id cannot precede after_id")
    normalized = tuple(dict.fromkeys(item.strip() for item in addresses if item.strip()))
    if not normalized:
        return []

    ensure_wallet_forward_observation_schema()
    placeholders = ",".join("?" for _ in normalized)
    query = f"""SELECT id, observation_key, wallet_address, token_mint, side,
        chain_time, observed_at
        FROM wallet_forward_observations
        WHERE id > ? AND wallet_address IN ({placeholders})"""
    params: list[object] = [after_id, *normalized]
    if through_id is not None:
        query += " AND id <= ?"
        params.append(through_id)
    query += " ORDER BY observed_at, id"
    result = rows(query, tuple(params))
    return [
        ScopedForwardObservation(
            id=int(item["id"]),
            observation_key=str(item["observation_key"]),
            action=WalletActionObservation(
                address=str(item["wallet_address"]),
                token_mint=str(item["token_mint"]),
                side=str(item["side"]),
                chain_time=int(item["chain_time"]),
                observed_at=int(item["observed_at"]),
            ),
        )
        for item in result
    ]


def _replay_event_scoped(
    observations: list[ScopedForwardObservation],
    *,
    config: WalletCausalReplayConfig,
):
    """Replay each BUY only against quotes captured for that exact forward event."""
    buy_observations = [item for item in observations if item.action.side == "buy"]
    quote_keys_by_event = load_successful_quote_keys_by_event(
        [item.observation_key for item in buy_observations]
    )
    results = []
    for item in buy_observations:
        quote_keys = quote_keys_by_event.get(item.observation_key, ())
        quotes = load_causal_quotes(quote_keys=list(quote_keys))
        results.extend(replay_wallet_actions([item.action], quotes, config=config))
    return results


def _resolve_run(run_key: str | None) -> WalletForwardRun | None:
    if run_key:
        return get_wallet_forward_run(run_key)
    return latest_wallet_forward_run(completed_only=True)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Relatório único de observabilidade wallet + route quotes + causal replay. "
            "RESEARCH/READ ONLY; não calcula PnL nem envia ordens."
        )
    )
    parser.add_argument(
        "--file",
        default="wallets/forward-watch-archetypes-2026-08-31.txt",
        help="coorte usada apenas no modo legado sem run manifest",
    )
    parser.add_argument(
        "--run-key",
        help=(
            "run manifest específico; se omitido usa a run COMPLETED mais recente. "
            "Sem manifest disponível, cai em modo legado sem causal replay."
        ),
    )
    parser.add_argument(
        "--delays-seconds", type=int, nargs="+", default=list(DEFAULT_DELAYS)
    )
    parser.add_argument("--slippage-bps", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    delays = tuple(dict.fromkeys(args.delays_seconds))
    if not delays or any(delay < 0 for delay in delays):
        print("Erro: delays precisam ser >= 0.")
        return 2
    if not 0 <= args.slippage_bps <= 10_000:
        print("Erro: --slippage-bps precisa ficar entre 0 e 10000.")
        return 2

    initialize_database()
    run = _resolve_run(args.run_key)
    if args.run_key and run is None:
        print(f"Erro: run manifest não encontrado: {args.run_key}")
        return 2

    if run is not None:
        addresses = list(run.cohort)
        after_id = run.baseline_observation_id
        through_id = run.end_observation_id
        scoped = True
    else:
        try:
            addresses = _load_addresses(args.file)
        except ValueError as exc:
            print(f"Erro: {exc}")
            return 2
        after_id = 0
        through_id = None
        scoped = False

    scoped_observations = _load_scoped_observations(
        addresses,
        after_id=after_id,
        through_id=through_id,
    )
    actions = [item.action for item in scoped_observations]
    buy_observations = [item for item in scoped_observations if item.action.side == "buy"]
    buy_event_keys = [item.observation_key for item in buy_observations]

    forward = summarize_forward_wallet_latency(actions)
    by_wallet = summarize_forward_wallet_latency_by_address(actions)
    quote_metrics = summarize_wallet_quote_metrics(
        wallet_addresses=addresses,
        source_event_keys=buy_event_keys if scoped else [],
    )

    strict_reports = []
    proxy_reports = []
    if scoped:
        for delay in delays:
            strict_config = WalletCausalReplayConfig(
                decision_delay_seconds=delay,
                slippage_bps=args.slippage_bps,
                require_executable_quote=True,
            )
            proxy_config = WalletCausalReplayConfig(
                decision_delay_seconds=delay,
                slippage_bps=args.slippage_bps,
                require_executable_quote=False,
            )
            strict_reports.append(
                (
                    delay,
                    summarize_wallet_causal_replay(
                        _replay_event_scoped(scoped_observations, config=strict_config)
                    ),
                )
            )
            proxy_reports.append(
                (
                    delay,
                    summarize_wallet_causal_replay(
                        _replay_event_scoped(scoped_observations, config=proxy_config)
                    ),
                )
            )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "scope": "RUN_MANIFEST" if scoped else "LEGACY_UNSCOPED",
                    "run": asdict(run) if run is not None else None,
                    "cohort": addresses,
                    "forward": asdict(forward),
                    "forward_buy_count_for_replay": len(buy_observations),
                    "by_wallet": {
                        address: asdict(summary) for address, summary in by_wallet.items()
                    },
                    "quote_metrics": asdict(quote_metrics),
                    "strict_replay": [
                        {"delay_seconds": delay, **asdict(summary)}
                        for delay, summary in strict_reports
                    ],
                    "proxy_replay": [
                        {"delay_seconds": delay, **asdict(summary)}
                        for delay, summary in proxy_reports
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Checkpoint v2")
    print("Modo: RESEARCH / READ ONLY — observabilidade, não edge/PnL.")
    if run is not None:
        print(
            f"Escopo: RUN_MANIFEST {run.run_key} | status {run.status} | "
            f"ids ({run.baseline_observation_id}, {run.end_observation_id}] | "
            f"quote mode {run.quote_mode}"
        )
    else:
        print(
            "Escopo: LEGACY_UNSCOPED — sem run manifest. Wallet latency pode ser vista, "
            "mas route quotes/replay ficam bloqueados para evitar mistura de execuções."
        )

    print()
    print("1. WALLET OBSERVABILITY")
    print(
        f"ações {forward.observation_count} | wallets {forward.wallet_count} | "
        f"tokens {forward.token_count} | buy/sell {forward.buy_count}/{forward.sell_count}"
    )
    print(
        f"lag chain→observed p50/p95/max {_fmt(forward.median_lag_seconds)} / "
        f"{_fmt(forward.p95_lag_seconds)} / {_fmt(forward.max_lag_seconds)} | "
        f"<=30s {forward.within_30s_share_pct:.1f}% | <=60s {forward.within_60s_share_pct:.1f}%"
    )
    for address, summary in by_wallet.items():
        print(
            f"- {address[:12]}… n={summary.observation_count} | "
            f"p50/p95 {_fmt(summary.median_lag_seconds)}/{_fmt(summary.p95_lag_seconds)}"
        )

    print()
    print("2. ROUTE QUOTE OBSERVABILITY")
    if not scoped:
        print("BLOQUEADO: sem run manifest não usamos tentativas/quotes antigos no checkpoint.")
    else:
        print(
            f"BUYs forward elegíveis {len(buy_observations)} | tentativas {quote_metrics.attempt_count} | "
            f"sucesso {quote_metrics.success_count} ({quote_metrics.success_pct:.1f}%) | "
            f"falhas {quote_metrics.failure_count} | tx candidata {quote_metrics.executable_count} | "
            f"proxy {quote_metrics.proxy_count}"
        )
        for item in quote_metrics.delays:
            print(
                f"- +{item.delay_seconds}s: {item.success_count}/{item.attempt_count} "
                f"({item.success_pct:.1f}%) | request lag p50/p95 "
                f"{_fmt(item.median_request_lag_seconds)}/{_fmt(item.p95_request_lag_seconds)}"
            )

    print()
    print("3. CAUSAL REPLAY COVERAGE — ENTRY BUY ONLY")
    print(
        "Cada BUY é reprocessado somente com quotes ligados ao MESMO evento forward. "
        "SELLs não entram no denominador deste experimento de viabilidade de entrada."
    )
    if not scoped:
        print("BLOQUEADO: causal replay exige run manifest.")
    else:
        print("Strict = transação candidata montada; Proxy = quote-only permitido.")
        if run is not None and run.quote_mode == "proxy":
            print(
                "Nota: esta run foi quote-only; strict=0 é esperado e NÃO significa falha "
                "da rota proxy."
            )
        for (delay, strict), (_, proxy) in zip(strict_reports, proxy_reports):
            print(
                f"+{delay}s | strict {strict.filled_count}/{strict.action_count} "
                f"({strict.fill_coverage_pct:.1f}%) | proxy {proxy.filled_count}/{proxy.action_count} "
                f"({proxy.fill_coverage_pct:.1f}%) | strict p95 chain→quote "
                f"{_fmt(strict.p95_total_chain_to_quote_seconds)}"
            )

    print()
    print("GATE")
    if not scoped:
        print("BLOQUEADO: execute uma nova coleta via wallet_forward_experiment.py para criar manifest.")
    elif run is not None and run.status != "COMPLETED":
        print("BLOQUEADO: run não está COMPLETED; dados podem ser auditados, não promovidos.")
    elif forward.observation_count == 0:
        print("SEM AMOSTRA: nenhuma ação forward da coorte ocorreu nesta run.")
    elif len(buy_observations) == 0:
        print("SEM AMOSTRA DE ENTRADA: houve ações forward, mas nenhum BUY nesta run.")
    elif run is not None and not run.with_jupiter_quotes:
        print("WALLET OBSERVABILITY COLETADA; esta run não habilitou route quotes.")
    elif quote_metrics.attempt_count == 0:
        print("BLOQUEADO: houve BUY forward, mas nenhuma tentativa de route quote foi auditada.")
    else:
        print(
            "Há dados run-scoped para auditar observabilidade de entrada. Próxima decisão depende "
            "de cobertura, timing e missingness; este relatório não promove estratégia sozinho."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
