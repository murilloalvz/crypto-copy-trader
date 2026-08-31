import argparse
import json
import time
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WaveOpportunityEvidence, build_opportunity_context
from src.social_event_store import load_social_events
from src.wallet_forward_observations import load_wallet_forward_observations


def _latest_wave(token_mint: str, as_of: int) -> WaveOpportunityEvidence | None:
    result = rows(
        """SELECT id, token_mint, detected_at, wave_score, strategy_version
        FROM wave_signals
        WHERE token_mint=? AND detected_at<=?
        ORDER BY detected_at DESC, id DESC LIMIT 1""",
        (token_mint, as_of),
    )
    if not result:
        return None
    item = result[0]
    return WaveOpportunityEvidence(
        signal_id=int(item["id"]),
        token_mint=str(item["token_mint"]),
        detected_at=int(item["detected_at"]),
        wave_score=float(item["wave_score"]),
        strategy_version=str(item["strategy_version"]),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspeciona o contexto causal disponível para um token a partir de Wave, "
            "observações forward de wallets e snapshots sociais já persistidos."
        )
    )
    parser.add_argument("token_mint", help="mint Solana do token")
    parser.add_argument(
        "--as-of",
        type=int,
        help="timestamp Unix do contexto; padrão: agora",
    )
    parser.add_argument(
        "--no-social",
        action="store_true",
        help="não carrega o canal social",
    )
    parser.add_argument("--json", action="store_true", help="emite JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of = int(time.time()) if args.as_of is None else args.as_of
    if as_of < 0:
        raise SystemExit("Erro: --as-of precisa ser não negativo.")

    initialize_database()
    wave = _latest_wave(args.token_mint, as_of)
    wallet_observations = load_wallet_forward_observations(
        token_mint=args.token_mint,
        as_of=as_of,
    )
    social_events = (
        []
        if args.no_social
        else load_social_events(token_mint=args.token_mint, as_of=as_of)
    )
    context = build_opportunity_context(
        token_mint=args.token_mint,
        as_of=as_of,
        wave=wave,
        wallet_observations=wallet_observations,
        social_events=social_events,
        include_social=not args.no_social,
    )

    if args.json:
        print(json.dumps(asdict(context), ensure_ascii=False, indent=2))
        return 0

    print("Crypto Copy Trader — Opportunity Context v1")
    print("Modo: RESEARCH / READ ONLY — nenhuma decisão de trade é produzida.")
    print(f"Token: {context.token_mint}")
    print(f"as_of: {context.as_of}")
    print(
        "Canais disponíveis: "
        + (", ".join(context.available_channels) if context.available_channels else "nenhum")
    )
    print()

    print("WAVE")
    if context.wave is None:
        print("- nenhuma evidência Wave disponível até as_of")
    else:
        print(
            f"- signal_id {context.wave.signal_id} | score {context.wave.wave_score:.1f} | "
            f"{context.wave.strategy_version} | detected_at {context.wave.detected_at}"
        )

    print()
    print("WALLETS FORWARD")
    print(
        f"- ações observadas {context.wallets.observed_action_count} | "
        f"buys {context.wallets.buy_action_count} | sells {context.wallets.sell_action_count}"
    )
    print(
        f"- wallets únicas comprando {context.wallets.unique_buy_wallet_count} | "
        f"vendendo {context.wallets.unique_sell_wallet_count}"
    )

    print()
    print("SOCIAL")
    if context.social is None:
        print("- canal desativado")
    else:
        acceleration = (
            f"{context.social.event_rate_acceleration_ratio:.2f}x"
            if context.social.event_rate_acceleration_ratio is not None
            else "indisponível"
        )
        print(
            f"- eventos recentes {context.social.current_event_count} | autores únicos "
            f"{context.social.current_unique_author_count} | aceleração {acceleration}"
        )
        print(
            f"- diversidade {context.social.current_author_diversity_pct:.1f}% | "
            f"originais {context.social.current_original_share_pct:.1f}% | "
            f"engagement {context.social.current_total_engagement}"
        )

    print()
    print(
        "Este relatório só mostra evidências que já eram observáveis em as_of. Não existe score "
        "combinado nem regra de compra nesta camada."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
