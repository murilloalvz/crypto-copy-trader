import argparse
import json
import sys
from pathlib import Path

from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation, validate_causal_quote
from src.database import initialize_database


def _parse_quote(payload: dict, *, fallback_key: str) -> tuple[str, CausalQuoteObservation]:
    quote_key = str(payload.get("quote_key") or fallback_key).strip()
    executable = payload["executable"]
    if not isinstance(executable, bool):
        raise ValueError("executable precisa ser boolean JSON (true/false)")
    quote = CausalQuoteObservation(
        token_mint=str(payload["token_mint"]).strip(),
        side=str(payload["side"]).strip(),
        market_time=int(payload["market_time"]),
        observed_at=int(payload["observed_at"]),
        price_usd=float(payload["price_usd"]),
        source=str(payload["source"]).strip(),
        executable=executable,
        resolution_seconds=int(payload.get("resolution_seconds", 1)),
        liquidity_usd=(
            float(payload["liquidity_usd"])
            if payload.get("liquidity_usd") is not None
            else None
        ),
        input_mint=(str(payload["input_mint"]).strip() if payload.get("input_mint") else None),
        output_mint=(str(payload["output_mint"]).strip() if payload.get("output_mint") else None),
        input_amount_raw=(
            str(payload["input_amount_raw"]) if payload.get("input_amount_raw") is not None else None
        ),
        output_amount_raw=(
            str(payload["output_amount_raw"]) if payload.get("output_amount_raw") is not None else None
        ),
        route_id=(str(payload["route_id"]).strip() if payload.get("route_id") else None),
    )
    validate_causal_quote(quote)
    return quote_key, quote


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Importa snapshots de quote causais em JSONL. Não consulta providers e não envia ordens."
        )
    )
    parser.add_argument("path", help="arquivo JSONL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="valida todos os registros sem persistir",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"Erro: arquivo não encontrado: {path}", file=sys.stderr)
        return 2

    initialize_database()
    parsed: list[tuple[str, CausalQuoteObservation]] = []
    try:
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"linha {line_number}: objeto JSON esperado")
            parsed.append(
                _parse_quote(payload, fallback_key=f"{path.name}:{line_number}")
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Erro ao validar JSONL: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"OK: {len(parsed)} quote(s) válidos; nada persistido.")
        return 0

    inserted = 0
    for quote_key, quote in parsed:
        inserted += int(record_causal_quote(quote, quote_key=quote_key))
    print(
        f"Quotes válidos: {len(parsed)} | novos persistidos: {inserted} | "
        f"duplicados ignorados: {len(parsed) - inserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
