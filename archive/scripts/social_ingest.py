import argparse
import json
import sys
from pathlib import Path

from src.database import initialize_database
from src.social_event_store import record_social_event_snapshot
from src.social_intelligence import SocialEvent


def load_jsonl(path: Path) -> list[SocialEvent]:
    if not path.exists():
        raise ValueError(f"arquivo não encontrado: {path}")
    events: list[SocialEvent] = []
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
            "Importa snapshots sociais JSONL já observados para o SQLite causal. "
            "Não consulta X e não executa ordens."
        )
    )
    parser.add_argument("events_file", help="arquivo JSONL de SocialEvent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="valida o arquivo sem persistir registros",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        events = load_jsonl(Path(args.events_file))
    except (ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"JSONL válido: {len(events)} snapshot(s). Nada foi persistido.")
        return 0

    initialize_database()
    inserted = duplicates = 0
    for event in events:
        try:
            created = record_social_event_snapshot(event)
        except ValueError as exc:
            print(f"Erro ao persistir evento {event.event_id}: {exc}", file=sys.stderr)
            return 2
        if created:
            inserted += 1
        else:
            duplicates += 1

    identities = {
        (event.token_mint or "", (event.symbol or "").upper()) for event in events
    }
    print("Crypto Copy Trader — Social Snapshot Ingest v1")
    print("Modo: RESEARCH / READ ONLY — nenhuma ordem e nenhuma consulta externa.")
    print(
        f"Snapshots lidos: {len(events)} | inseridos: {inserted} | "
        f"duplicados: {duplicates} | identidades observadas: {len(identities)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
