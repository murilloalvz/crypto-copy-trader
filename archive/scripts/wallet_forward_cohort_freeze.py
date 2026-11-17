import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from src.config import settings
from src.database import add_wallet, initialize_database, rows
from src.services import sync_wallet
from src.solana import SolanaRPCError
from src.wallet_forward_cohort_selection import (
    PROTOCOL_VERSION,
    build_wallet_forward_acquisition_profile,
    select_wallet_forward_cohort,
)


def _load_addresses(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"arquivo de wallets não encontrado: {path}")
    addresses = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    addresses = list(dict.fromkeys(addresses))
    if not addresses:
        raise ValueError("arquivo de wallets está vazio")
    return addresses


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _local_swaps(address: str, cutoff_at: int) -> list[dict]:
    return rows(
        """SELECT block_time, status, kind, dex, token_mint, token_change
        FROM transactions
        WHERE wallet_address=?
          AND kind='swap'
          AND status='success'
          AND block_time IS NOT NULL
          AND block_time<=?
        ORDER BY block_time""",
        (address, cutoff_at),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Congela uma coorte Wallet Forward usando somente evidência pré-T0 de RPC/SQLite. "
            "Não usa PnL, retorno ou resultados forward futuros."
        )
    )
    parser.add_argument(
        "--protocol-version",
        default=PROTOCOL_VERSION,
        help="identificador auditável do protocolo de aquisição",
    )
    parser.add_argument("--file", required=True, help="universo candidato, uma wallet por linha")
    parser.add_argument(
        "--sync-onchain",
        action="store_true",
        help="faz refresh RPC uniforme antes do cutoff pré-T0",
    )
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--max-wallets", type=int, default=5)
    parser.add_argument("--min-wallets", type=int, default=3)
    parser.add_argument(
        "--output-wallets",
        default="wallets/forward-cohort-v1.txt",
        help="arquivo congelado da coorte selecionada",
    )
    parser.add_argument(
        "--output-json",
        default="wallet-forward-acquisition-v1.json",
        help="evidência auditável da seleção",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.protocol_version.strip():
        print("Erro: --protocol-version não pode ser vazio.", file=sys.stderr)
        return 2
    if not 1 <= args.pages <= 20:
        print("Erro: --pages precisa ficar entre 1 e 20.", file=sys.stderr)
        return 2
    if args.max_wallets < 1:
        print("Erro: --max-wallets precisa ser >= 1.", file=sys.stderr)
        return 2
    if not 1 <= args.min_wallets <= args.max_wallets:
        print("Erro: --min-wallets precisa ficar entre 1 e --max-wallets.", file=sys.stderr)
        return 2

    candidate_path = Path(args.file)
    try:
        addresses = _load_addresses(candidate_path)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    initialize_database()
    sync_notes: list[dict] = []
    sync_status_by_address: dict[str, str] = {}

    for index, address in enumerate(addresses, start=1):
        add_wallet(address, args.protocol_version)
        note = {"address": address, "sync": "existing_only", "pages": []}
        if args.sync_onchain:
            note["sync"] = "ok"
            for page in range(1, args.pages + 1):
                try:
                    result = sync_wallet(address, backfill=page > 1)
                except (SolanaRPCError, ValueError) as exc:
                    note["sync"] = "failed" if page == 1 else "partial"
                    note["error"] = str(exc)
                    print(
                        f"[rpc] {address[:10]}… página {page} falhou: {exc}",
                        file=sys.stderr,
                    )
                    break
                note["pages"].append(result)
                print(
                    f"[rpc] {index}/{len(addresses)} {address[:10]}… página {page}: "
                    f"encontrados {result['found']} | novos {result['inserted']} | "
                    f"falhas {result['failed']} | endpoint {result['rpc_endpoint']}"
                )
                if result["found"] == 0:
                    break
        sync_status_by_address[address] = str(note["sync"])
        sync_notes.append(note)

    cutoff_at = int(time.time())
    profiles = []
    for address in addresses:
        extra_reasons: tuple[str, ...] = ()
        if args.sync_onchain and sync_status_by_address[address] != "ok":
            extra_reasons = (f"pre_t0_sync_{sync_status_by_address[address]}",)
        profile = build_wallet_forward_acquisition_profile(
            address,
            _local_swaps(address, cutoff_at),
            cutoff_at=cutoff_at,
            extra_exclusion_reasons=extra_reasons,
        )
        profiles.append(profile)

    selected = select_wallet_forward_cohort(profiles, max_wallets=args.max_wallets)
    selected_addresses = [item.address for item in selected]

    payload = {
        "mode": "RESEARCH_READ_ONLY",
        "protocol_version": args.protocol_version,
        "cutoff_at": cutoff_at,
        "git_head": _git_head(),
        "database_path": str(settings.database_path),
        "candidate_file": str(candidate_path),
        "candidate_count": len(addresses),
        "min_wallets": args.min_wallets,
        "max_wallets": args.max_wallets,
        "sync_onchain": bool(args.sync_onchain),
        "pages": args.pages if args.sync_onchain else 0,
        "selected_addresses": selected_addresses,
        "selected_count": len(selected_addresses),
        "profiles": [asdict(item) for item in profiles],
        "sync": sync_notes,
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("Crypto Copy Trader — Wallet Forward Cohort Freeze")
    print("Modo: RESEARCH / READ ONLY — seleção exclusivamente pré-T0.")
    print(f"Protocolo: {args.protocol_version}")
    print(
        f"Candidatas: {len(addresses)} | elegíveis: {sum(item.eligible for item in profiles)} | "
        f"selecionadas: {len(selected_addresses)} | cutoff_at={cutoff_at}"
    )
    for item in sorted(profiles, key=lambda row: (not row.eligible, row.address)):
        status = "ELIGIBLE" if item.eligible else "EXCLUDED"
        reasons = ",".join(item.exclusion_reasons) if item.exclusion_reasons else "-"
        age_h = (
            f"{item.latest_swap_age_seconds / 3600:.1f}h"
            if item.latest_swap_age_seconds is not None
            else "n/a"
        )
        print(
            f"- {status} {item.address[:10]}… | swaps={item.swap_count} | "
            f"active7d={item.active_days_7d} | swaps72h={item.swaps_72h} | "
            f"latest={age_h} | rate={item.frequency_rate_per_day:.1f}/d | "
            f"roundtrip={item.roundtrip_share_pct:.1f}% | complete={item.complete_like_sizing_count} | "
            f"reasons={reasons}"
        )

    if len(selected_addresses) < args.min_wallets:
        print()
        print(
            f"BLOQUEADO: somente {len(selected_addresses)} wallet(s) elegíveis; "
            f"o protocolo exige ao menos {args.min_wallets}."
        )
        print(f"Evidência salva em {output_json}; nenhuma coorte executável foi congelada.")
        return 3

    output_wallets = Path(args.output_wallets)
    output_wallets.parent.mkdir(parents=True, exist_ok=True)
    output_wallets.write_text(
        f"# {args.protocol_version} — frozen pre-T0 cohort\n"
        f"# cutoff_at={cutoff_at}\n"
        f"# git_head={payload['git_head']}\n"
        f"# database_path={payload['database_path']}\n"
        + "\n".join(selected_addresses)
        + "\n",
        encoding="utf-8",
    )

    print()
    print("COORTE CONGELADA")
    for address in selected_addresses:
        print(address)
    print(f"Wallet file: {output_wallets}")
    print(f"Audit JSON: {output_json}")
    print(
        "Não altere este arquivo com base em atividade observada depois deste cutoff. "
        "O próximo T0 deve ocorrer somente depois deste freeze."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
