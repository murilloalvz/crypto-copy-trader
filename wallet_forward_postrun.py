import argparse
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import evaluate_wallet_forward
import evaluate_wallet_quotes
import wallet_forward_checkpoint
import wallet_forward_exposure
import wallet_forward_integrity
import wallet_forward_readiness
import wallet_forward_wallet_profiles
import wallet_quote_completeness
import wallet_quote_provider_quality
from src.database import initialize_database
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run


AUDIT_STEPS = (
    ("FORWARD INTEGRITY", wallet_forward_integrity.main),
    ("FORWARD OBSERVATION EXPOSURE", wallet_forward_exposure.main),
    ("QUOTE COMPLETENESS", wallet_quote_completeness.main),
    ("UNIFIED FORWARD CHECKPOINT", wallet_forward_checkpoint.main),
    ("RUN-SCOPED WALLET LATENCY", evaluate_wallet_forward.main),
    ("RUN-SCOPED QUOTE ATTEMPTS", evaluate_wallet_quotes.main),
    ("JUPITER PROVIDER QUALITY", wallet_quote_provider_quality.main),
    ("CAUSAL REPLAY READINESS", wallet_forward_readiness.main),
    ("PER-WALLET TECHNICAL PROFILES", wallet_forward_wallet_profiles.main),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Executa em sequência as auditorias locais de uma Wallet Forward Run concluída. "
            "RESEARCH/READ ONLY; não faz requests de mercado nem envia ordens."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument(
        "--output",
        help="arquivo UTF-8 opcional para salvar o relatório consolidado",
    )
    return parser


def _render_step(title: str, main_fn, run_key: str) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = int(main_fn(["--run-key", run_key]) or 0)
    except Exception as exc:  # audit orchestrator must expose one broken step, not hide it
        code = 1
        stderr.write(f"{type(exc).__name__}: {exc}\n")
    body = stdout.getvalue().rstrip()
    errors = stderr.getvalue().rstrip()
    lines = ["=" * 88, title, "=" * 88]
    if body:
        lines.append(body)
    if errors:
        lines.extend(["", "STDERR", errors])
    lines.append(f"STEP EXIT CODE: {code}")
    return code, "\n".join(lines)


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
        print(
            f"Erro: run {run.run_key} está {run.status}. O post-run final exige COMPLETED "
            "para não congelar uma interpretação parcial."
        )
        return 2

    header = "\n".join(
        [
            "Crypto Copy Trader — Wallet Forward Post-Run Audit",
            "Modo: RESEARCH / READ ONLY — somente SQLite local; sem requests de mercado.",
            f"Run: {run.run_key}",
            f"Runtime: {run.runtime_version}",
            f"Quote mode: {run.quote_mode}",
            f"Cohort: {len(run.cohort)} wallets",
            f"Observation ids: ({run.baseline_observation_id}, {run.end_observation_id}]",
        ]
    )

    blocks = [header]
    failed_steps = 0
    for title, main_fn in AUDIT_STEPS:
        code, rendered = _render_step(title, main_fn, run.run_key)
        blocks.append(rendered)
        failed_steps += int(code != 0)

    footer = "\n".join(
        [
            "=" * 88,
            "POST-RUN AUDIT RESULT",
            "=" * 88,
            f"Steps: {len(AUDIT_STEPS)} | non-zero: {failed_steps}",
            (
                "AUDIT PIPELINE COMPLETED — interpretar causalidade/censoring/missingness/readiness antes de edge."
                if failed_steps == 0
                else "AUDIT PIPELINE INCOMPLETE — corrigir/entender steps non-zero antes de promoção."
            ),
        ]
    )
    blocks.append(footer)
    report = "\n\n".join(blocks) + "\n"
    print(report, end="")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Relatório salvo em: {output_path}")

    return 0 if failed_steps == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
