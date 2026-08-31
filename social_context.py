import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.social_intelligence import SocialEvent, build_social_context


def _load_events(path: Path) -> list[SocialEvent]:
    if not path.exists():
        raise ValueError(f"arquivo não encontrado: {path}")
    events = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            payload = json.loads(value)
            events.append(SocialEvent(**payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"linha {line_number} inválida: {exc}") from exc
    return events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Constrói contexto social causal a partir de eventos JSONL já observados. "
            "Não consulta X nem executa ordens."
        )
    )
    parser.add_argument("events_file", help="arquivo JSONL com snapshots de eventos sociais")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--token-mint")
    identity.add_argument("--symbol")
    parser.add_argument("--as-of", type=int, required=True, help="timestamp Unix causal da decisão")
    parser.add_argument(
        "--windows",
        default="300,900,3600",
        help="janelas em segundos separadas por vírgula (padrão: 300,900,3600)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        windows = tuple(int(item.strip()) for item in args.windows.split(",") if item.strip())
        events = _load_events(Path(args.events_file))
        context = build_social_context(
            events,
            as_of=args.as_of,
            token_mint=args.token_mint,
            symbol=args.symbol,
            windows=windows,
        )
    except (ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            asdict(context),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
