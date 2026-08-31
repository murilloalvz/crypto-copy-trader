import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.database import add_wallet, initialize_database, rows
from src.services import sync_wallet
from src.solana import SolanaRPCError
from src.wallet_strategy_lab import (
    build_wallet_strategy_fingerprint,
    summarize_wallet_strategy_lab,
)


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


def _load_addresses(positional: list[str], file_path: str | None) -> list[str]:
    addresses = [item.strip() for item in positional if item.strip()]
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"arquivo de wallets não encontrado: {path}")
        for raw in path.read_text(encoding="utf-8").splitlines():
            value = raw.strip()
            if value and not value.startswith("#"):
                addresses.append(value)
    return list(dict.fromkeys(addresses))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara fingerprints comportamentais de múltiplas wallets usando RPC/SQLite. "
            "Não usa Solana Tracker Data API e não altera a estratégia do bot."
        )
    )
    parser.add_argument("addresses", nargs="*", help="endereços públicos Solana")
    parser.add_argument(
        "--file",
        help="arquivo UTF-8 com uma wallet por linha; linhas iniciadas por # são ignoradas",
    )
    parser.add_argument(
        "--sync-onchain",
        action="store_true",
        help="sincroniza RPC antes da análise; sem esta opção usa somente o SQLite atual",
    )
    parser.add_argument("--pages", type=int, default=3, help="páginas RPC por wallet (padrão: 3)")
    parser.add_argument("--json", action="store_true", help="emite resultado JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.pages <= 20:
        print("Erro: --pages precisa ficar entre 1 e 20.", file=sys.stderr)
        return 2

    try:
        addresses = _load_addresses(args.addresses, args.file)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    if not addresses:
        print(
            "Erro: informe ao menos uma wallet como argumento ou via --file.",
            file=sys.stderr,
        )
        return 2

    initialize_database()
    fingerprints = []
    sync_notes: list[dict] = []

    for index, address in enumerate(addresses, start=1):
        add_wallet(address, "Wallet Strategy Lab")
        note = {"address": address, "sync": "existing_only"}
        if args.sync_onchain:
            note["sync"] = "ok"
            note["pages"] = []
            for page in range(1, args.pages + 1):
                try:
                    result = sync_wallet(address, backfill=page > 1)
                except (SolanaRPCError, ValueError) as exc:
                    note["sync"] = "partial" if page > 1 else "failed"
                    note["error"] = str(exc)
                    if not args.json:
                        print(
                            f"[rpc] {address[:8]}… página {page} falhou: {exc}",
                            file=sys.stderr,
                        )
                    break
                note["pages"].append(result)
                if not args.json:
                    print(
                        f"[rpc] {index}/{len(addresses)} {address[:8]}… página {page}: "
                        f"encontrados {result['found']} | novos {result['inserted']} | "
                        f"conhecidos {result['skipped']} | falhas {result['failed']} | "
                        f"endpoint {result['rpc_endpoint']}"
                    )
                if result["found"] == 0:
                    break

        swaps = _local_swaps(address)
        fingerprints.append(build_wallet_strategy_fingerprint(address, swaps))
        sync_notes.append(note)

    summary = summarize_wallet_strategy_lab(fingerprints)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "uses_solana_tracker_data_api": False,
                    "fingerprints": [asdict(item) for item in fingerprints],
                    "summary": asdict(summary),
                    "sync": sync_notes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print()
    print("Crypto Copy Trader — Wallet Strategy Lab v1")
    print("Modo: RESEARCH / READ ONLY — sem ordens e sem Solana Tracker Data API.")
    print(f"Wallets analisadas: {summary.wallet_count}")

    for item in fingerprints:
        print()
        print(f"WALLET {item.address}")
        print(
            f"Amostra: {item.swap_count} swaps | {item.token_count} tokens | "
            f"{item.observed_span_days:.1f}d | grau {item.sample_grade}"
        )
        print(
            f"Fingerprint: {item.signature} | intensidade mediana: "
            f"{item.frequency_rate_per_day:.1f} swaps/dia ({item.frequency_basis})"
        )
        print(f"Média calendário observada: {item.swaps_per_day:.1f} swaps/dia")
        print(
            f"Primeira saída mediana: {_duration(item.median_first_exit_seconds)} | "
            f"roundtrip observado: {item.roundtrip_share_pct:.1f}%"
        )
        print(
            f"Scale-in: {item.scale_in_share_pct:.1f}% | múltiplas vendas: "
            f"{item.multi_sell_share_pct:.1f}% | reentrada: {item.reentry_share_pct:.1f}%"
        )
        print(
            "Sizing complete-like: "
            f"{item.complete_like_sizing_count} | multi-sell complete-like: "
            f"{item.complete_multi_sell_count}"
        )
        if item.median_complete_multi_first_sell_fraction_pct is not None:
            print(
                "Primeira tranche/runner mediano nos multi-sell complete-like: "
                f"{item.median_complete_multi_first_sell_fraction_pct:.1f}% / "
                f"{item.median_complete_multi_runner_pct:.1f}%"
            )
        if item.dominant_dex:
            print(
                f"DEX dominante: {item.dominant_dex} "
                f"({item.dominant_dex_share_pct:.1f}% dos swaps observados)"
            )
        if item.flags:
            print("Alertas: " + ", ".join(item.flags))

    print()
    print("COMPARAÇÃO ENTRE WALLETS")
    print("Holding: " + json.dumps(summary.holding_buckets, ensure_ascii=False))
    print("Saída: " + json.dumps(summary.exit_buckets, ensure_ascii=False))
    print("Reentrada: " + json.dumps(summary.reentry_buckets, ensure_ascii=False))
    print("Frequência: " + json.dumps(summary.frequency_buckets, ensure_ascii=False))
    print("Assinaturas: " + json.dumps(summary.signatures, ensure_ascii=False))

    print()
    print("LIMITAÇÃO IMPORTANTE")
    print(
        "Os fingerprints descrevem a amostra on-chain local. Eles não medem PnL, não provam "
        "intenção da wallet e não são regras de trading. O bucket de frequência usa a mediana "
        "dos gaps entre swaps quando disponível para reduzir sensibilidade a backfill parcial; "
        "a média calendário continua exibida separadamente."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
