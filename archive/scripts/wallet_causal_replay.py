import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.causal_quote_store import ensure_causal_quote_schema, load_causal_quotes
from src.database import connection, initialize_database
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_causal_replay import (
    WalletCausalReplayConfig,
    replay_wallet_actions,
    summarize_wallet_causal_replay,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema


def _load_file(path_value: str | None) -> list[str]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _load_forward_actions(
    *,
    addresses: list[str],
    as_of: int | None,
) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    clauses: list[str] = []
    params: list[object] = []
    if addresses:
        placeholders = ",".join("?" for _ in addresses)
        clauses.append(f"wallet_address IN ({placeholders})")
        params.extend(addresses)
    if as_of is not None:
        clauses.append("observed_at<=?")
        params.append(as_of)

    query = """SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY observed_at, id"

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [
        WalletActionObservation(
            address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
        )
        for row in rows
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay causal das ações forward de wallets contra quotes persistidos. "
            "RESEARCH/READ ONLY: não envia ordens e não transforma candles em quotes executáveis."
        )
    )
    parser.add_argument("addresses", nargs="*", help="wallets específicas; vazio = todas")
    parser.add_argument("--file", help="arquivo UTF-8 com uma wallet por linha")
    parser.add_argument("--as-of", type=int, help="limita observações pelo observed_at")
    parser.add_argument(
        "--delay-seconds",
        type=int,
        nargs="*",
        default=[0, 15, 30, 60, 120],
        help="delays adicionais após detectar a ação (padrão: 0 15 30 60 120)",
    )
    parser.add_argument("--slippage-bps", type=int, default=100)
    parser.add_argument("--max-quote-age-seconds", type=int, default=15)
    parser.add_argument("--max-quote-wait-seconds", type=int, default=30)
    parser.add_argument(
        "--allow-proxy-quotes",
        action="store_true",
        help=(
            "permite quotes marcados como não executáveis; apenas diagnóstico. "
            "Nunca use isso como evidência de execução live."
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.as_of is not None and args.as_of < 0:
        print("Erro: --as-of precisa ser >= 0.", file=sys.stderr)
        return 2
    if not args.delay_seconds:
        print("Erro: informe ao menos um --delay-seconds.", file=sys.stderr)
        return 2
    if any(delay < 0 for delay in args.delay_seconds):
        print("Erro: delays precisam ser >= 0.", file=sys.stderr)
        return 2

    try:
        addresses = list(args.addresses) + _load_file(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    addresses = list(dict.fromkeys(item.strip() for item in addresses if item.strip()))

    initialize_database()
    ensure_causal_quote_schema()
    actions = _load_forward_actions(addresses=addresses, as_of=args.as_of)
    quotes = load_causal_quotes(as_of=args.as_of)

    reports = []
    for delay in dict.fromkeys(args.delay_seconds):
        config = WalletCausalReplayConfig(
            decision_delay_seconds=delay,
            slippage_bps=args.slippage_bps,
            max_quote_age_seconds=args.max_quote_age_seconds,
            max_quote_wait_seconds=args.max_quote_wait_seconds,
            require_executable_quote=not args.allow_proxy_quotes,
        )
        results = replay_wallet_actions(actions, quotes, config=config)
        summary = summarize_wallet_causal_replay(results)
        reports.append(
            {
                "delay_seconds": delay,
                "config": asdict(config),
                "summary": asdict(summary),
                "missing_reasons": {
                    reason: sum(row.reason == reason for row in results)
                    for reason in sorted({row.reason for row in results if row.reason})
                },
            }
        )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "forward_action_count": len(actions),
                    "quote_count": len(quotes),
                    "reports": reports,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Causal Replay v1")
    print("Modo: RESEARCH / READ ONLY — nenhuma ordem é enviada.")
    print(
        f"Ações forward: {len(actions)} | quotes causais persistidos: {len(quotes)} | "
        f"quotes exigidos: {'proxy permitido' if args.allow_proxy_quotes else 'executáveis'}"
    )
    if not actions:
        print("Sem ações forward persistidas. Rode primeiro o Wallet Forward Watch em rede estável.")
        return 0
    if not quotes:
        print(
            "Sem quotes causais persistidos. O replay está pronto, mas não inventa preço: "
            "a próxima camada é coletar quotes com observed_at real."
        )

    print()
    for report in reports:
        summary = report["summary"]
        print(
            f"DELAY +{report['delay_seconds']}s | fills {summary['filled_count']}/"
            f"{summary['action_count']} ({summary['fill_coverage_pct']:.1f}%) | "
            f"lag fonte mediano {summary['median_source_lag_seconds']}s | "
            f"espera quote mediana {summary['median_quote_wait_seconds']}s | "
            f"p95 chain→quote {summary['p95_total_chain_to_quote_seconds']}s"
        )
        if report["missing_reasons"]:
            print("  faltantes: " + json.dumps(report["missing_reasons"], ensure_ascii=False))

    print()
    print(
        "Interpretação: fill coverage mede observabilidade causal sob as restrições declaradas. "
        "Não mede edge nem PnL. Candles/proxies só entram com --allow-proxy-quotes e continuam "
        "inadequados para validar execução live."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
