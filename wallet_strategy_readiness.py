import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database, rows
from src.wallet_strategy_lab import build_wallet_strategy_fingerprint
from src.wallet_strategy_readiness import (
    assess_wallet_strategy_readiness,
    summarize_wallet_strategy_readiness,
)


def _local_swaps(address: str) -> list[dict]:
    return rows(
        """SELECT block_time, status, kind, dex, token_mint, token_change
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
        ORDER BY block_time""",
        (address,),
    )


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


def _all_local_addresses(min_swaps: int) -> list[str]:
    result = rows(
        """SELECT wallet_address AS address, COUNT(*) AS swap_count
        FROM transactions
        WHERE kind='swap' AND status='success'
        GROUP BY wallet_address
        HAVING COUNT(*) >= ?
        ORDER BY COUNT(*) DESC, wallet_address""",
        (min_swaps,),
    )
    return [str(item["address"]) for item in result]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mostra por que cada fingerprint de wallet está ou não pronto para pesquisa "
            "cross-wallet e sugere o próximo passo de coleta. RESEARCH/READ ONLY."
        )
    )
    parser.add_argument("addresses", nargs="*", help="wallets a avaliar")
    parser.add_argument("--file", help="arquivo UTF-8 com uma wallet por linha")
    parser.add_argument(
        "--all-local",
        action="store_true",
        help="inclui wallets do SQLite com amostra mínima de swaps",
    )
    parser.add_argument(
        "--min-swaps",
        type=int,
        default=20,
        help="mínimo de swaps para --all-local (padrão: 20)",
    )
    parser.add_argument("--json", action="store_true", help="emite JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_swaps < 1:
        print("Erro: --min-swaps precisa ser >= 1.", file=sys.stderr)
        return 2

    initialize_database()
    try:
        addresses = list(args.addresses) + _load_file(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if args.all_local:
        addresses.extend(_all_local_addresses(args.min_swaps))
    addresses = list(dict.fromkeys(item.strip() for item in addresses if item.strip()))
    if not addresses:
        print("Erro: informe wallets, --file ou --all-local.", file=sys.stderr)
        return 2

    fingerprints = [
        build_wallet_strategy_fingerprint(address, _local_swaps(address))
        for address in addresses
    ]
    readiness = [assess_wallet_strategy_readiness(item) for item in fingerprints]
    summary = summarize_wallet_strategy_readiness(readiness)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "readiness": [asdict(item) for item in readiness],
                    "summary": asdict(summary),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Strategy Readiness v1")
    print("Modo: RESEARCH / READ ONLY — não mede PnL e não altera o bot.")
    print(
        f"Wallets: {summary.wallet_count} | evidência descritiva pronta: "
        f"{summary.evidence_ready_count}"
    )
    print()
    for fingerprint, item in zip(fingerprints, readiness):
        print(
            f"- {item.address[:12]}… | {item.stage} | "
            f"{fingerprint.swap_count} swaps / {fingerprint.token_count} tokens | "
            f"roundtrip {fingerprint.roundtrip_share_pct:.1f}% | "
            f"complete-like {fingerprint.complete_like_sizing_count}"
        )
        if item.blockers:
            print("  bloqueios: " + ", ".join(item.blockers))
        print("  próximos passos: " + ", ".join(item.next_actions))

    print()
    print("RESUMO DOS GARGALOS")
    print(json.dumps(summary.blockers, ensure_ascii=False))
    print("AÇÕES SUGERIDAS")
    print(json.dumps(summary.next_actions, ensure_ascii=False))
    print()
    print(
        "As ações acima são de coleta/pesquisa. FORWARD_WATCH_OBSERVABILITY mede latência "
        "causal mesmo quando o fingerprint ainda não está pronto; não promove a wallet a "
        "estratégia e não é recomendação de cópia."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
