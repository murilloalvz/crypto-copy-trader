import argparse
import json

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect audited market replay conflicts for one run")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("limit must be positive")

    ensure_market_observation_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, event_key, event_type, source_provider,
                stored_observed_at, incoming_observed_at,
                stored_identity_json, incoming_identity_json,
                canonical_action, created_at
            FROM market_replay_conflicts
            WHERE acquisition_run_key=?
            ORDER BY id
            LIMIT ?""",
            (args.run_key, args.limit),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM market_replay_conflicts WHERE acquisition_run_key=?",
            (args.run_key,),
        ).fetchone()

    print(f"run_key={args.run_key} total_conflicts={int(total['count'])}")
    for row in rows:
        print(
            json.dumps(
                {
                    "id": int(row["id"]),
                    "event_key": str(row["event_key"]),
                    "event_type": str(row["event_type"]),
                    "source_provider": str(row["source_provider"]),
                    "stored_observed_at": int(row["stored_observed_at"]),
                    "incoming_observed_at": int(row["incoming_observed_at"]),
                    "canonical_action": str(row["canonical_action"]),
                    "stored_identity": json.loads(str(row["stored_identity_json"])),
                    "incoming_identity": json.loads(str(row["incoming_identity_json"])),
                    "created_at": str(row["created_at"]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
