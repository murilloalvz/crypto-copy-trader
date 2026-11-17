import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database, rows
from src.wallet_placebo_matching import rank_placebo_candidates
from src.wallet_strategy_compare import fingerprint_evidence_ready
from src.wallet_strategy_lab import build_wallet_strategy_fingerprint


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


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ordena candidatos placebo por semelhança comportamental pré-período. "
            "Não usa PnL/outcomes e não congela uma coorte automaticamente."
        )
    )
    parser.add_argument("target", help="wallet target")
    parser.add_argument("candidates", nargs="*", help="wallets candidatas a placebo")
    parser.add_argument("--file", help="arquivo UTF-8 com candidatas, uma por linha")
    parser.add_argument(
        "--all-local",
        action="store_true",
        help="inclui wallets locais com amostra mínima",
    )
    parser.add_argument("--min-swaps", type=int, default=20)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="omite candidatas que não passam o evidence-readiness descritivo",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_swaps < 1 or args.top < 1:
        print("Erro: --min-swaps e --top precisam ser >= 1.", file=sys.stderr)
        return 2

    initialize_database()
    try:
        candidates = list(args.candidates) + _load_file(args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if args.all_local:
        candidates.extend(_all_local_addresses(args.min_swaps))
    candidates = list(dict.fromkeys(item.strip() for item in candidates if item.strip()))
    candidates = [item for item in candidates if item != args.target]
    if not candidates:
        print("Erro: nenhuma candidata placebo disponível.", file=sys.stderr)
        return 2

    target = build_wallet_strategy_fingerprint(args.target, _local_swaps(args.target))
    candidate_fingerprints = [
        build_wallet_strategy_fingerprint(address, _local_swaps(address))
        for address in candidates
    ]
    ranked = rank_placebo_candidates(
        target,
        candidate_fingerprints,
        require_evidence_ready=args.require_ready,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_PREPERIOD_MATCHING_ONLY",
                    "target": asdict(target),
                    "target_evidence_ready": fingerprint_evidence_ready(target),
                    "diagnostics": [asdict(item) for item in ranked],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Placebo Matching v1")
    print("Modo: RESEARCH / PRE-PERIOD — sem PnL, outcome ou score de edge.")
    print(
        f"Target: {args.target} | swaps {target.swap_count} | tokens {target.token_count} | "
        f"evidence-ready {'SIM' if fingerprint_evidence_ready(target) else 'NAO'}"
    )
    print(f"Candidatas comparadas: {len(ranked)}")
    print()
    print("RANKING DIAGNOSTICO")
    for index, item in enumerate(ranked[: args.top], start=1):
        similarity = (
            "n/a"
            if item.bucket_similarity_pct is None
            else f"{item.bucket_similarity_pct:.1f}%"
        )
        dex = (
            "n/a"
            if item.dominant_dex_match is None
            else "mesmo"
            if item.dominant_dex_match
            else "diferente"
        )
        print(
            f"{index}. {item.candidate_address} | bucket {similarity} "
            f"({item.matching_dimensions}/{item.comparable_dimensions}) | "
            f"coverage {item.comparison_coverage_grade}"
        )
        print(
            f"   atividade {_ratio(item.active_day_rate_ratio)} | "
            f"tokens {_ratio(item.token_breadth_ratio)} | "
            f"holding {_ratio(item.first_exit_ratio)} | span {_ratio(item.observed_span_ratio)}"
        )
        print(
            f"   roundtrip diff {item.roundtrip_abs_diff_pct:.1f}pp | "
            f"multi-sell diff {item.multi_sell_abs_diff_pct:.1f}pp | DEX {dex}"
        )
        if item.warnings:
            print("   alertas: " + ", ".join(item.warnings))

    print()
    print("INTERPRETACAO")
    print(
        "A ordem e lexicografica e auditavel, nao um score ponderado. Evidence coverage vem "
        "antes da proximidade comportamental. Revise os diagnosticos antes de congelar placebos."
    )
    print(
        "Uma wallet parecida nao e automaticamente um bom placebo causal; matching final precisa "
        "ser congelado usando somente dados pre-periodo e depois testado prospectivamente."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
