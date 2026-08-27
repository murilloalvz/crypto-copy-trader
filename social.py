import argparse
import sys

from src.config import settings
from src.database import initialize_database
from src.social.service import (
    backfill_social_event_parsing,
    collect_social_events,
    latest_social_events,
)
from src.social.x_api import (
    XApiAuthenticationError,
    XApiConfigurationError,
    XApiError,
    XApiRateLimitError,
    XRecentSearchClient,
    normalize_usernames,
)


def _accounts(value: str | None) -> tuple[str, ...]:
    if value is None:
        return settings.social_tier_a_accounts
    return normalize_usernames(value.split(","))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coleta eventos de contas Tier A no X sem executar trades."
    )
    parser.add_argument(
        "--accounts",
        help="contas separadas por vírgula; por padrão usa SOCIAL_TIER_A_ACCOUNTS",
    )
    parser.add_argument("--lookback-minutes", type=int, default=None)
    parser.add_argument("--top", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        accounts = _accounts(args.accounts)
    except ValueError as exc:
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 2
    if not accounts:
        print(
            "Configuração necessária: defina SOCIAL_TIER_A_ACCOUNTS no .env.",
            file=sys.stderr,
        )
        return 2
    if args.lookback_minutes is not None and not 1 <= args.lookback_minutes <= 1_440:
        print("Erro: --lookback-minutes deve ficar entre 1 e 1440.", file=sys.stderr)
        return 2
    if not 1 <= args.top <= 100:
        print("Erro: --top deve ficar entre 1 e 100.", file=sys.stderr)
        return 2

    initialize_database()
    backfilled = backfill_social_event_parsing()
    print("Crypto Copy Trader — Social/Event Monitor · EVENT-2")
    print("Modo: READ ONLY — nenhum sinal, compra, venda ou assinatura é gerado.")
    print("Fonte: API oficial do X · contas Tier A: " + ", ".join(f"@{x}" for x in accounts))
    try:
        result = collect_social_events(
            XRecentSearchClient(),
            accounts,
            lookback_minutes=args.lookback_minutes,
        )
    except (XApiConfigurationError, XApiAuthenticationError) as exc:
        print(f"Configuração necessária: {exc}", file=sys.stderr)
        return 2
    except XApiRateLimitError as exc:
        print(f"Coleta adiada: {exc}", file=sys.stderr)
        return 1
    except XApiError as exc:
        print(f"Falha temporária na fonte social: {exc}", file=sys.stderr)
        return 1

    print(
        f"Eventos recebidos: {result.fetched_events} | novos: {result.inserted_events} | "
        f"duplicados ignorados: {result.duplicate_events}"
    )
    if backfilled:
        print(f"Eventos antigos classificados deterministicamente: {backfilled}")
    recent = latest_social_events(args.top)
    if not recent:
        print("Nenhum evento encontrado na janela consultada.")
    for event in recent:
        text = " ".join(event["text"].split())
        print(
            f"- @{event['author_username']} | {event['event_type']} | "
            f"latência {event['detection_latency_ms']}ms | "
            f"{text[:140]}"
        )
    print("Classificação é heurística e não autoriza sinal ou resolução de token.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
