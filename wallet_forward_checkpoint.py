import argparse
import json
from dataclasses import asdict
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
from src.wallet_quote_metrics import summarize_wallet_quote_metrics


DEFAULT_DELAYS = (0, 15, 30, 60, 120)


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


def _load_actions(addresses: list[str]) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    placeholders = ",".join("?" for _ in addresses)
    result = rows(
        f"""SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations
        WHERE wallet_address IN ({placeholders})
        ORDER BY observed_at, id""",
        tuple(addresses),
    )
    return [
        WalletActionObservation(
            address=str(item["wallet_address"]),
            token_mint=str(item["token_mint"]),
            side=str(item["side"]),
            chain_time=int(item["chain_time"]),
            observed_at=int(item["observed_at"]),
        )
        for item in result
    ]


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
        help="arquivo da coorte forward",
    )
    parser.add_argument(
        "--delays-seconds", type=int, nargs="+", default=list(DEFAULT_DELAYS)
    )
    parser.add_argument("--slippage-bps", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        addresses = _load_addresses(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2
    delays = tuple(dict.fromkeys(args.delays_seconds))
    if not delays or any(delay < 0 for delay in delays):
        print("Erro: delays precisam ser >= 0.")
        return 2
    if not 0 <= args.slippage_bps <= 10_000:
        print("Erro: --slippage-bps precisa ficar entre 0 e 10000.")
        return 2

    initialize_database()
    actions = _load_actions(addresses)
    forward = summarize_forward_wallet_latency(actions)
    by_wallet = summarize_forward_wallet_latency_by_address(actions)
    quote_metrics = summarize_wallet_quote_metrics(wallet_addresses=addresses)
    quotes = load_causal_quotes()

    strict_reports = []
    proxy_reports = []
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
                    replay_wallet_actions(actions, quotes, config=strict_config)
                ),
            )
        )
        proxy_reports.append(
            (
                delay,
                summarize_wallet_causal_replay(
                    replay_wallet_actions(actions, quotes, config=proxy_config)
                ),
            )
        )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "cohort": addresses,
                    "forward": asdict(forward),
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

    print("Crypto Copy Trader — Wallet Forward Checkpoint v1")
    print("Modo: RESEARCH / READ ONLY — observabilidade, não edge/PnL.")
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
    print(
        f"tentativas {quote_metrics.attempt_count} | sucesso {quote_metrics.success_count} "
        f"({quote_metrics.success_pct:.1f}%) | falhas {quote_metrics.failure_count} | "
        f"tx candidata {quote_metrics.executable_count} | proxy {quote_metrics.proxy_count}"
    )
    for item in quote_metrics.delays:
        print(
            f"- +{item.delay_seconds}s: {item.success_count}/{item.attempt_count} "
            f"({item.success_pct:.1f}%) | request lag p50/p95 "
            f"{_fmt(item.median_request_lag_seconds)}/{_fmt(item.p95_request_lag_seconds)}"
        )

    print()
    print("3. CAUSAL REPLAY COVERAGE")
    print("Strict = só quote com transação candidata montada; Proxy = quote-only permitido.")
    for (delay, strict), (_, proxy) in zip(strict_reports, proxy_reports):
        print(
            f"+{delay}s | strict {strict.filled_count}/{strict.action_count} "
            f"({strict.fill_coverage_pct:.1f}%) | proxy {proxy.filled_count}/{proxy.action_count} "
            f"({proxy.fill_coverage_pct:.1f}%) | strict p95 chain→quote "
            f"{_fmt(strict.p95_total_chain_to_quote_seconds)}"
        )

    print()
    print("GATE")
    if forward.observation_count == 0:
        print("BLOQUEADO: ainda não há ações forward da coorte.")
    elif quote_metrics.attempt_count == 0:
        print(
            "WALLET OBSERVABILITY EM COLETA; route-quote gate ainda sem dados. "
            "Não inferir copyability por preço."
        )
    else:
        print(
            "Há dados para auditar observabilidade. Próxima decisão depende de cobertura, "
            "timing e missingness; este relatório não promove estratégia automaticamente."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
