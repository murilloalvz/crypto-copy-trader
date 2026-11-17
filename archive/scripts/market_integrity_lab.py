import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.discovery.models import WaveTokenSnapshot
from src.market_integrity import build_market_integrity_features
from src.rejection_intelligence import ensure_rejection_schema


def _token_from_snapshot(raw: str, *, wrapped: bool) -> WaveTokenSnapshot:
    payload = json.loads(raw)
    token_payload = payload.get("token") if wrapped else payload
    if not isinstance(token_payload, dict):
        raise ValueError("snapshot does not contain a token object")
    return WaveTokenSnapshot(**token_payload)


def _load_records(signal_limit: int, rejection_limit: int) -> list[dict]:
    records: list[dict] = []
    if signal_limit:
        for item in rows(
            """SELECT id, detected_at, token_mint, snapshot_json
            FROM wave_signals ORDER BY detected_at DESC, id DESC LIMIT ?""",
            (signal_limit,),
        ):
            records.append(
                {
                    "source": "accepted_signal",
                    "source_id": int(item["id"]),
                    "observed_at": int(item["detected_at"]),
                    "token_mint": str(item["token_mint"]),
                    "token": _token_from_snapshot(str(item["snapshot_json"]), wrapped=True),
                }
            )
    if rejection_limit:
        ensure_rejection_schema()
        for item in rows(
            """SELECT id, detected_at, token_mint, snapshot_json
            FROM wave_rejection_decisions ORDER BY detected_at DESC, id DESC LIMIT ?""",
            (rejection_limit,),
        ):
            records.append(
                {
                    "source": "rejected_snapshot",
                    "source_id": int(item["id"]),
                    "observed_at": int(item["detected_at"]),
                    "token_mint": str(item["token_mint"]),
                    "token": _token_from_snapshot(str(item["snapshot_json"]), wrapped=False),
                }
            )
    return sorted(records, key=lambda item: (-item["observed_at"], item["source"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extrai features observacionais de integridade de mercado de snapshots causais "
            "já persistidos. Não detecta wash trading e não altera a Wave."
        )
    )
    parser.add_argument("--signals", type=int, default=10, help="últimos sinais aceitos")
    parser.add_argument("--rejections", type=int, default=10, help="últimas rejeições causais")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.signals < 0 or args.rejections < 0:
        raise SystemExit("Erro: limites precisam ser >= 0.")
    if args.signals == 0 and args.rejections == 0:
        raise SystemExit("Erro: peça ao menos sinais ou rejeições.")

    initialize_database()
    records = _load_records(args.signals, args.rejections)
    output = []
    for item in records:
        features = build_market_integrity_features(item["token"])
        output.append(
            {
                "source": item["source"],
                "source_id": item["source_id"],
                "observed_at": item["observed_at"],
                "features": asdict(features),
            }
        )

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print("Crypto Copy Trader — Market Integrity Lab v1")
    print("Modo: RESEARCH / READ ONLY — features agregadas, sem score de manipulação.")
    print(f"Snapshots analisados: {len(output)}")
    if not output:
        print("Nenhum snapshot causal compatível encontrado.")
        return 0

    for item in output:
        f = item["features"]
        print()
        print(
            f"{item['source']} #{item['source_id']} | {f['token_mint']} | "
            f"observed_at {item['observed_at']}"
        )
        print(
            f"- buy pressure {f['buy_pressure_pct'] if f['buy_pressure_pct'] is not None else 'n/a'} | "
            f"imbalance {f['trade_imbalance_pct'] if f['trade_imbalance_pct'] is not None else 'n/a'} | "
            f"volume acceleration {f['volume_acceleration'] if f['volume_acceleration'] is not None else 'n/a'}"
        )
        print(
            f"- top10/dev/insiders/snipers: {f['top10_pct']} / {f['dev_pct']} / "
            f"{f['insiders_pct']} / {f['snipers_pct']}"
        )
        print(
            "- flags dos gates já existentes: "
            + (", ".join(f["existing_gate_flags"]) if f["existing_gate_flags"] else "nenhum")
        )
        print(
            "- qualidade de dados: "
            + (", ".join(f["data_quality_flags"]) if f["data_quality_flags"] else "sem alerta agregado")
        )

    print()
    print(
        "Limite metodológico: estes snapshots não têm grafo de contrapartes nem sequência "
        "order-level; portanto não provam wash trading/self-trading."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
