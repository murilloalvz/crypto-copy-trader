import argparse

from src.database import initialize_database, rows
from src.wallet_exit_sizing import analyze_exit_sizing, summarize_exit_sizing
from wallet_entry_context import _short


def _local_swaps(address: str) -> list[dict]:
    return rows(
        """SELECT token_mint, block_time, token_change, dex
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
          AND token_mint IS NOT NULL AND token_change IS NOT NULL AND block_time IS NOT NULL
        ORDER BY block_time""",
        (address,),
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Estima quanto da posição observada a wallet vende na primeira saída e quanto "
            "deixa como runner. Usa apenas swaps locais; não chama provider externo."
        )
    )
    parser.add_argument("address", help="endereço público Solana já sincronizado no SQLite")
    args = parser.parse_args()

    initialize_database()
    observations = analyze_exit_sizing(_local_swaps(args.address))
    summary = summarize_exit_sizing(observations)

    print("Crypto Copy Trader — Wallet Exit Sizing v1")
    print("Modo: RESEARCH / READ ONLY — nenhuma estratégia é alterada.")
    print(f"Wallet: {args.address}")
    print()
    print("RESUMO")
    print(
        f"Ciclos com quantidade observável: {summary.token_count} | "
        f"multi-sell: {summary.multi_sell_token_count} ({summary.multi_sell_share_pct:.1f}%)"
    )
    print(
        f"Fração mediana vendida na 1ª saída: {_pct(summary.median_first_sell_fraction_pct)} | "
        f"total vendido no ciclo: {_pct(summary.median_total_sold_fraction_pct)}"
    )
    print(
        f"1ª venda <50% da posição observada: {summary.first_sell_below_50_share_pct:.1f}% | "
        f"runner mediano após 1ª venda nos multi-sell: "
        f"{_pct(summary.median_runner_after_first_sell_pct)}"
    )
    print(f"Anomalias de quantidade (>105%): {summary.quantity_anomaly_share_pct:.1f}%")

    print()
    print("AMOSTRA POR TOKEN")
    for item in observations:
        print(
            f"- {_short(item.token_mint)} | sells {item.sell_count} | "
            f"1ª venda {item.first_sell_fraction_pct:.1f}% | "
            f"total ciclo {item.total_sold_fraction_pct:.1f}% | "
            f"runner proxy {item.observed_runner_after_first_sell_pct:.1f}% | "
            f"anomalia {'sim' if item.quantity_anomaly else 'não'}"
        )

    print()
    print("LIMITAÇÕES")
    print("- Quantidades vêm apenas de token_change dos swaps observados localmente.")
    print("- Transferências fora de swaps, estoque prévio, taxa/reflexão do token ou backfill incompleto podem distorcer as frações.")
    print("- Runner é 100% menos a primeira venda observada; não prova intenção da wallet.")
    print("- Este relatório não calcula PnL e não autoriza alterar wave_v3/exit_engine_v1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
