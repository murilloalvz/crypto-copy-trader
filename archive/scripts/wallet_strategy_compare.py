import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database, rows
from src.wallet_strategy_compare import (
    build_pairwise_strategy_comparisons,
    fingerprint_evidence_ready,
    summarize_recurring_strategy_patterns,
)
from src.wallet_strategy_lab import build_wallet_strategy_fingerprint


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "indisponível"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3_600:
        return f"{seconds / 60:.1f}min"
    if seconds < 86_400:
        return f"{seconds / 3_600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


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
            "Compara fingerprints comportamentais já presentes no SQLite e procura padrões "
            "recorrentes entre wallets. Não mede lucratividade e não altera o bot."
        )
    )
    parser.add_argument("addresses", nargs="*", help="wallets a comparar")
    parser.add_argument("--file", help="arquivo UTF-8 com uma wallet por linha")
    parser.add_argument(
        "--all-local",
        action="store_true",
        help="inclui automaticamente wallets locais com amostra mínima de swaps",
    )
    parser.add_argument(
        "--min-swaps",
        type=int,
        default=20,
        help="mínimo de swaps para --all-local (padrão: 20)",
    )
    parser.add_argument(
        "--top-pairs",
        type=int,
        default=10,
        help="máximo de pares exibidos no modo texto (padrão: 10)",
    )
    parser.add_argument("--json", action="store_true", help="emite JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_swaps < 1:
        print("Erro: --min-swaps precisa ser >= 1.", file=sys.stderr)
        return 2
    if args.top_pairs < 1:
        print("Erro: --top-pairs precisa ser >= 1.", file=sys.stderr)
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

    if len(addresses) < 2:
        print(
            "Erro: são necessárias ao menos duas wallets para comparação.",
            file=sys.stderr,
        )
        return 2

    fingerprints = [
        build_wallet_strategy_fingerprint(address, _local_swaps(address))
        for address in addresses
    ]
    comparisons = build_pairwise_strategy_comparisons(fingerprints)
    patterns = summarize_recurring_strategy_patterns(fingerprints)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "fingerprints": [asdict(item) for item in fingerprints],
                    "comparisons": [asdict(item) for item in comparisons],
                    "patterns": [asdict(item) for item in patterns],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ready = sum(fingerprint_evidence_ready(item) for item in fingerprints)
    print("Crypto Copy Trader — Wallet Strategy Comparison v1")
    print("Modo: RESEARCH / READ ONLY — comparação descritiva, não score de lucro.")
    print(f"Wallets: {len(fingerprints)} | evidência pronta para comparação: {ready}")
    print()
    print("PADRÕES RECORRENTES")
    for pattern in patterns:
        print(
            f"- {pattern.signature}: {pattern.wallet_count} wallet(s) | "
            f"prontas {pattern.evidence_ready_count} | {pattern.support_grade} | "
            f"1ª saída mediana {_duration(pattern.median_first_exit_seconds)}"
        )
        print(
            f"  scale-in {pattern.median_scale_in_share_pct:.1f}% | "
            f"multi-sell {pattern.median_multi_sell_share_pct:.1f}% | "
            f"reentrada {pattern.median_reentry_share_pct:.1f}%"
        )

    print()
    print("PARES MAIS PARECIDOS")
    for item in comparisons[: args.top_pairs]:
        similarity = (
            f"{item.similarity_pct:.1f}%"
            if item.similarity_pct is not None
            else "incomparável"
        )
        print(
            f"- {item.left_address[:10]}… × {item.right_address[:10]}…: "
            f"{similarity} | dimensões {item.matching_dimensions}/{item.comparable_dimensions}"
        )
        if item.differing:
            print("  diferenças: " + ", ".join(item.differing))
        if item.warnings:
            print("  alertas: " + ", ".join(item.warnings))

    print()
    print("INTERPRETAÇÃO")
    print(
        "Recorrência de fingerprint serve para formular hipóteses de estratégia. Não prova edge, "
        "não prova intenção da wallet e não autoriza copiar posições. O próximo estágio para um "
        "padrão recorrente é contexto de entrada/saída, replay causal, stress de execução e shadow."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
