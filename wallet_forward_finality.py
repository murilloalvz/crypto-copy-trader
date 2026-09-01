import argparse
import sys

from src.database import connection, initialize_database
from src.solana import SolanaRPCError
from src.wallet_forward_finality import summarize_wallet_forward_finality
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_rpc import WalletForwardSolanaClient
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run


BATCH_SIZE = 256


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verifica no Solana RPC se as assinaturas de uma Wallet Forward Run chegaram a "
            "finalized. READ ONLY; faz requests RPC, não envia transações."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    return parser


def _load_scoped_signatures(run) -> tuple[int, int, list[str]]:
    if run.end_observation_id is None:
        raise ValueError("run precisa ter end_observation_id para auditoria de finality")
    ensure_wallet_forward_observation_schema()
    cohort = tuple(run.cohort)
    placeholders = ",".join("?" for _ in cohort)
    params = (
        run.baseline_observation_id,
        run.end_observation_id,
        *cohort,
    )
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT signature
            FROM wallet_forward_observations
            WHERE id>? AND id<=?
              AND wallet_address IN ({placeholders})
            ORDER BY id""",
            params,
        ).fetchall()
    observation_count = len(rows)
    missing_signature_rows = sum(
        row["signature"] is None or not str(row["signature"]).strip() for row in rows
    )
    signatures = list(
        dict.fromkeys(
            str(row["signature"]).strip()
            for row in rows
            if row["signature"] is not None and str(row["signature"]).strip()
        )
    )
    return observation_count, missing_signature_rows, signatures


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=True)
    )
    if run is None:
        print("Nenhuma Wallet Forward Run COMPLETED encontrada.")
        return 0
    if run.status != "COMPLETED":
        print(f"Erro: run {run.run_key} está {run.status}; use uma run COMPLETED.", file=sys.stderr)
        return 2

    try:
        observation_count, missing_signature_rows, signatures = _load_scoped_signatures(run)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    print("Crypto Copy Trader — Wallet Forward Finality Audit v1")
    print("Modo: READ ONLY — consulta getSignatureStatuses; nenhuma ordem é enviada.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | observações {observation_count} | "
        f"assinaturas únicas {len(signatures)} | linhas sem assinatura {missing_signature_rows}"
    )
    if not signatures:
        print("Sem assinaturas forward para verificar.")
        return 0

    client = WalletForwardSolanaClient(commitment="finalized")
    statuses: list[dict | None] = []
    try:
        for start in range(0, len(signatures), BATCH_SIZE):
            statuses.extend(client.signature_statuses(signatures[start : start + BATCH_SIZE]))
    except (SolanaRPCError, RuntimeError, ValueError) as exc:
        print(f"Erro RPC durante auditoria de finality: {exc}", file=sys.stderr)
        return 1

    summary = summarize_wallet_forward_finality(statuses)
    print(
        f"Finalized {summary.finalized_success_count + summary.finalized_error_count}/"
        f"{summary.signature_count} ({summary.finalized_share_pct:.1f}%) | "
        f"finalized success {summary.finalized_success_count} | "
        f"finalized com erro {summary.finalized_error_count}"
    )
    print(
        f"Ainda confirmed {summary.confirmed_count} | processed {summary.processed_count} | "
        f"missing {summary.missing_count} | status desconhecido {summary.unknown_status_count}"
    )
    print()
    print("INTERPRETAÇÃO")
    print("- confirmed permite observar antes; finalized verifica depois se a assinatura persistiu no ledger.")
    print("- Assinatura ainda confirmed logo após a run não prova reorg; pode apenas não ter finalizado ainda.")
    print("- missing/finalized com erro permanecem visíveis e bloqueiam tratar a amostra como totalmente finalizada.")
    print("- Finality limpa valida permanência on-chain, não edge, fill nosso ou copyability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
