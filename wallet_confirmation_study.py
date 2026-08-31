import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from src.database import initialize_database
from src.wallet_confirmation_placebo import ConfirmationPolicy, WalletCohort
from src.wallet_confirmation_study import (
    ConfirmationStudySpec,
    activate_confirmation_study,
    close_confirmation_study,
    load_confirmation_study,
    register_confirmation_study,
)
from src.wallet_confirmation_wave_study import (
    evaluate_wave_confirmation_study,
    materialize_wave_confirmation_events,
)


def _cohort(payload: dict) -> WalletCohort:
    return WalletCohort(
        name=str(payload["name"]),
        addresses=tuple(str(item) for item in payload["addresses"]),
        role=str(payload["role"]),
    )


def _spec(payload: dict) -> ConfirmationStudySpec:
    return ConfirmationStudySpec(
        study_key=str(payload["study_key"]),
        frozen_at=int(payload["frozen_at"]),
        preperiod_cutoff=int(payload["preperiod_cutoff"]),
        starts_at=int(payload["starts_at"]),
        ends_at=(None if payload.get("ends_at") is None else int(payload["ends_at"])),
        target=_cohort(payload["target"]),
        placebos=tuple(_cohort(item) for item in payload["placebos"]),
        policy=ConfirmationPolicy(**payload["policy"]),
        horizons_minutes=tuple(int(item) for item in payload["horizons_minutes"]),
        context_scope=str(payload.get("context_scope") or "wave_opportunity_v1"),
        matching_method_version=str(
            payload.get("matching_method_version")
            or "wallet_placebo_matching_v1_preperiod"
        ),
        wave_strategy_version=str(
            payload.get("wave_strategy_version") or "wave_v3_volume_integrity"
        ),
        notes=str(payload.get("notes") or ""),
    )


def _load_spec_file(path_value: str) -> ConfirmationStudySpec:
    path = Path(path_value)
    if not path.exists():
        raise ValueError(f"manifest não encontrado: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest deve conter um objeto JSON")
    return _spec(payload)


def _now(value: int | None) -> int:
    return int(time.time()) if value is None else int(value)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pré-registra e audita estudos prospectivos Wallet Confirmation + placebo. "
            "RESEARCH/READ ONLY: não cria sinais nem ordens."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="congela um manifest JSON")
    register.add_argument("manifest")

    show = sub.add_parser("show", help="mostra o spec imutável")
    show.add_argument("study_key")
    show.add_argument("--json", action="store_true")

    activate = sub.add_parser("activate", help="ativa após starts_at")
    activate.add_argument("study_key")
    activate.add_argument("--now", type=int)

    materialize = sub.add_parser(
        "materialize",
        help="congela confirmações das oportunidades Wave já elegíveis",
    )
    materialize.add_argument("study_key")
    materialize.add_argument("--as-of", type=int)

    evaluate = sub.add_parser("evaluate", help="avalia confirmações target x placebos")
    evaluate.add_argument("study_key")
    evaluate.add_argument("--json", action="store_true")

    close = sub.add_parser("close", help="fecha um estudo ACTIVE")
    close.add_argument("study_key")
    close.add_argument("--now", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    try:
        if args.command == "register":
            result = register_confirmation_study(_load_spec_file(args.manifest))
            print(
                f"Study {result.study_key}: {result.status} | "
                f"{'criada' if result.created else 'já existia com spec idêntico'}"
            )
            return 0

        if args.command == "show":
            stored = load_confirmation_study(args.study_key)
            if stored is None:
                raise ValueError("study_key desconhecida")
            if args.json:
                print(json.dumps(asdict(stored), ensure_ascii=False, indent=2))
            else:
                print("Crypto Copy Trader — Wallet Confirmation Study")
                print(f"study_key: {stored.spec.study_key}")
                print(f"status: {stored.status}")
                print(
                    f"preperiod_cutoff/frozen/start/end: {stored.spec.preperiod_cutoff} / "
                    f"{stored.spec.frozen_at} / {stored.spec.starts_at} / {stored.spec.ends_at}"
                )
                print(
                    f"target: {stored.spec.target.name} ({len(stored.spec.target.addresses)} wallets) | "
                    f"placebos: {len(stored.spec.placebos)}"
                )
                print(
                    f"policy: {stored.spec.policy.min_unique_buy_wallets}+ wallets em "
                    f"{stored.spec.policy.window_seconds}s | horizontes {stored.spec.horizons_minutes}"
                )
                print(f"wave: {stored.spec.wave_strategy_version}")
            return 0

        if args.command == "activate":
            changed = activate_confirmation_study(
                args.study_key,
                now=_now(args.now),
            )
            print("ACTIVE" if changed else "já estava ACTIVE")
            return 0

        if args.command == "materialize":
            summary = materialize_wave_confirmation_events(
                args.study_key,
                as_of=_now(args.as_of),
            )
            print("Crypto Copy Trader — Wallet Confirmation Materialization")
            print(f"study_key: {summary.study_key}")
            print(f"oportunidades Wave: {summary.opportunity_count}")
            print(
                f"eventos esperados: {summary.expected_event_count} | "
                f"novos: {summary.newly_materialized_event_count} | "
                f"já congelados: {summary.existing_event_count}"
            )
            return 0

        if args.command == "evaluate":
            report = evaluate_wave_confirmation_study(args.study_key)
            if args.json:
                print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
                return 0
            print("Crypto Copy Trader — Wallet Confirmation + Placebo")
            print("Modo: RESEARCH / READ ONLY — comparação descritiva, não edge provado.")
            print(f"study_key: {report.study_key} | oportunidades: {report.opportunity_count}")
            print("\nCONFIRMAÇÕES")
            for item in report.cohort_rates:
                print(
                    f"- {item.cohort_name} ({item.cohort_role}): "
                    f"{item.confirmed_count}/{item.opportunity_count} "
                    f"({item.confirmation_rate_pct:.1f}%)"
                )
            print("\nOUTCOMES TARGET x PLACEBOS")
            for item in report.comparisons:
                print(
                    f"- {item.target.horizon_minutes}m | {item.interpretation_label} | "
                    f"target n={item.target.completed_count}/{item.target.confirmed_event_count} | "
                    f"Δ média vs mediana placebos {_fmt(item.target_minus_median_placebo_mean_return_pct)}pp | "
                    f"Δ mediana {_fmt(item.target_minus_median_placebo_median_return_pct)}pp"
                )
            return 0

        if args.command == "close":
            changed = close_confirmation_study(args.study_key, now=_now(args.now))
            print("CLOSED" if changed else "já estava CLOSED")
            return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
