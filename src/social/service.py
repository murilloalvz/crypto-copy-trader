from dataclasses import dataclass
import json

from src.database import connection, rows
from src.social.models import SocialEvent
from src.social.parser import parse_social_event
from src.social.x_api import normalize_usernames


@dataclass(frozen=True)
class SocialCollectionResult:
    fetched_events: int
    inserted_events: int
    duplicate_events: int


def sync_tier_a_accounts(usernames: tuple[str, ...] | list[str]) -> dict[str, int]:
    accounts = normalize_usernames(usernames)
    with connection() as conn:
        conn.execute(
            """UPDATE social_accounts SET enabled=0, updated_at=CURRENT_TIMESTAMP
            WHERE source='x' AND tier='A'"""
        )
        conn.executemany(
            """INSERT INTO social_accounts(source, username, tier, enabled)
            VALUES ('x', ?, 'A', 1)
            ON CONFLICT(source, username) DO UPDATE SET
            tier='A', enabled=1, updated_at=CURRENT_TIMESTAMP""",
            [(item,) for item in accounts],
        )
        found = conn.execute(
            "SELECT id, username FROM social_accounts WHERE source='x' AND enabled=1"
        ).fetchall()
    return {str(item["username"]).lower(): int(item["id"]) for item in found}


def collect_social_events(
    client,
    usernames: tuple[str, ...] | list[str],
    *,
    lookback_minutes: int | None = None,
) -> SocialCollectionResult:
    account_ids = sync_tier_a_accounts(usernames)
    events: list[SocialEvent] = client.fetch(
        usernames, lookback_minutes=lookback_minutes
    )
    inserted = 0
    with connection() as conn:
        for event in events:
            account_id = account_ids.get(event.author_username.lower())
            parsed = parse_social_event(event.text, event.raw_json)
            cursor = conn.execute(
                """INSERT OR IGNORE INTO social_events
                (source, external_event_id, account_id, author_source_id,
                 author_username, published_at_ms, detected_at_ms,
                 detection_latency_ms, text, url, event_type, tickers_json,
                 urls_json, mint_candidates_json, hashtags_json, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.source,
                    event.external_event_id,
                    account_id,
                    event.author_source_id,
                    event.author_username,
                    event.published_at_ms,
                    event.detected_at_ms,
                    event.detection_latency_ms,
                    event.text,
                    event.url,
                    parsed.event_type.value,
                    json.dumps(parsed.tickers, separators=(",", ":")),
                    json.dumps(parsed.urls, separators=(",", ":")),
                    json.dumps(parsed.mint_candidates, separators=(",", ":")),
                    json.dumps(parsed.hashtags, separators=(",", ":")),
                    event.raw_json,
                ),
            )
            inserted += cursor.rowcount
            if account_id and event.author_source_id:
                conn.execute(
                    """UPDATE social_accounts SET source_account_id=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (event.author_source_id, account_id),
                )
    return SocialCollectionResult(
        fetched_events=len(events),
        inserted_events=inserted,
        duplicate_events=len(events) - inserted,
    )


def backfill_social_event_parsing() -> int:
    """Classify EVENT-1 rows without deleting or rewriting the original payload."""
    pending = rows(
        """SELECT id, text, raw_json FROM social_events
        WHERE event_type='UNKNOWN' AND tickers_json='[]'
        AND urls_json='[]' AND mint_candidates_json='[]' AND hashtags_json='[]'"""
    )
    updates = []
    for item in pending:
        parsed = parse_social_event(item["text"], item["raw_json"])
        updates.append(
            (
                parsed.event_type.value,
                json.dumps(parsed.tickers, separators=(",", ":")),
                json.dumps(parsed.urls, separators=(",", ":")),
                json.dumps(parsed.mint_candidates, separators=(",", ":")),
                json.dumps(parsed.hashtags, separators=(",", ":")),
                item["id"],
            )
        )
    if updates:
        with connection() as conn:
            conn.executemany(
                """UPDATE social_events SET event_type=?, tickers_json=?,
                urls_json=?, mint_candidates_json=?, hashtags_json=? WHERE id=?""",
                updates,
            )
    return len(updates)


def latest_social_events(limit: int = 10) -> list[dict]:
    return rows(
        """SELECT source, external_event_id, author_username, published_at_ms,
        detected_at_ms, detection_latency_ms, text, url, event_type,
        tickers_json, urls_json, mint_candidates_json, hashtags_json
        FROM social_events ORDER BY published_at_ms DESC, id DESC LIMIT ?""",
        (max(1, int(limit)),),
    )
