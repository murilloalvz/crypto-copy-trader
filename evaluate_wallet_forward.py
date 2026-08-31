import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_metrics import (
    summarize_forward_wallet_latency,
    summarize_forward_wallet_latency_by_address,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema


def _load_observations(address: str | None = None) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    query = """SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations"""
    params: tuple = ()
    if address:
        query += " WHERE wallet_address=?"
        params = (address,)
    query += " ORDER BY observed_at, id"
    result = rows(query, params)
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


def _duration(value: float | None) -> str:
    return "indisponível" if value is None else f"{value:.1f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Avalia latência chain_time→observed_at das observações forward de wallets. "
            "Não calcula PnL e não executa ordens."
        )
    )
    parser.add_argument("--address", help="limita a uma wallet")
    parser.add_argument("--json", action="store_true", help="emite JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    observations = _load_observations(args.address)
    overall = summarize_forward_wallet_latency(observations)
    by_wallet = summarize_forward_wallet_latency_by_address(observations)

    if args.json:
        print(
            json.dumps(
                {
                    "overall": asdict(overall),
                    "by_wallet": {
                        address: asdict(summary) for address, summary in by_wallet.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Forward Wallet Latency Evaluation v1")
    print("Modo: RESEARCH / READ ONLY — mede observabilidade, não edge.")
    print(
        f"Observações: {overall.observation_count} | wallets {overall.wallet_count} | "
        f"tokens {overall.token_count} | buys/sells {overall.buy_count}/{overall.sell_count}"
    )
    print(
        f"Lag min/p50/p95/max: {_duration(overall.min_lag_seconds)} / "
        f"{_duration(overall.median_lag_seconds)} / {_duration(overall.p95_lag_seconds)} / "
        f"{_duration(overall.max_lag_seconds)}"
    )
    print(
        "Cobertura por atraso: "
        f"<=15s {overall.within_15s_share_pct:.1f}% | "
        f"<=30s {overall.within_30s_share_pct:.1f}% | "
        f"<=60s {overall.within_60s_share_pct:.1f}% | "
        f"<=120s {overall.within_120s_share_pct:.1f}%"
    )

    if by_wallet:
        print()
        print("POR WALLET")
        for address, summary in by_wallet.items():
            print(
                f"- {address[:12]}… n={summary.observation_count} | "
                f"p50 {_duration(summary.median_lag_seconds)} | "
                f"p95 {_duration(summary.p95_lag_seconds)} | "
                f"<=60s {summary.within_60s_share_pct:.1f}%"
            )

    print()
    print(
        "O lag mede quando nosso polling tomou conhecimento do swap. Para avaliar copyability, "
        "ainda precisamos cruzar esse atraso com preço executável, liquidez, slippage e retorno futuro."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
