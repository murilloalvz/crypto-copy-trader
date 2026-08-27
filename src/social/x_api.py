import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.config import settings
from src.social.models import SocialEvent


X_RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,30}$")


class XApiError(RuntimeError):
    pass


class XApiConfigurationError(XApiError):
    pass


class XApiAuthenticationError(XApiError):
    pass


class XApiRateLimitError(XApiError):
    pass


def normalize_usernames(usernames: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = []
    seen = set()
    for username in usernames:
        value = username.strip().lstrip("@")
        key = value.lower()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError(f"conta do X inválida: {username}")
        if key not in seen:
            seen.add(key)
            normalized.append(value)
    return tuple(normalized)


def build_accounts_query(usernames: tuple[str, ...]) -> str:
    if not usernames:
        raise ValueError("ao menos uma conta do X é necessária")
    query = "(" + " OR ".join(f"from:{item}" for item in usernames) + ") -is:retweet"
    if len(query) > 512:
        raise ValueError("lista de contas excede o limite de consulta do X")
    return query


def _timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000)


class XRecentSearchClient:
    """Small Tier-A poller backed only by the official X API v2."""

    def __init__(
        self,
        bearer_token: str | None = None,
        *,
        timeout_seconds: int | None = None,
        now: Callable[[], float] = time.time,
        opener=urlopen,
    ):
        self.bearer_token = (
            settings.x_bearer_token if bearer_token is None else bearer_token
        ).strip()
        self.timeout_seconds = max(
            1,
            settings.social_timeout_seconds
            if timeout_seconds is None
            else int(timeout_seconds),
        )
        self._now = now
        self._opener = opener

    def fetch(
        self,
        usernames: tuple[str, ...] | list[str],
        *,
        lookback_minutes: int | None = None,
    ) -> list[SocialEvent]:
        if not self.bearer_token:
            raise XApiConfigurationError("X_BEARER_TOKEN não configurado")
        accounts = normalize_usernames(usernames)
        lookback = max(
            1,
            settings.social_lookback_minutes
            if lookback_minutes is None
            else int(lookback_minutes),
        )
        detected_at_ms = int(self._now() * 1_000)
        start_time = datetime.fromtimestamp(
            detected_at_ms / 1_000, timezone.utc
        ) - timedelta(minutes=lookback)
        params = {
            "query": build_accounts_query(accounts),
            "max_results": 100,
            "start_time": start_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "tweet.fields": "author_id,created_at",
            "expansions": "author_id",
            "user.fields": "id,username",
        }
        request = Request(
            f"{X_RECENT_SEARCH_URL}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "crypto-copy-trader/0.4",
            },
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise XApiAuthenticationError("credencial do X recusada") from exc
            if exc.code == 429:
                raise XApiRateLimitError("limite da API do X atingido") from exc
            raise XApiError(f"API do X respondeu HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise XApiError(f"API do X indisponível: {exc}") from exc

        users = {
            str(item.get("id")): str(item.get("username") or "")
            for item in (payload.get("includes", {}).get("users") or [])
            if isinstance(item, dict) and item.get("id")
        }
        events = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id") or "")
            author_id = str(item.get("author_id") or "") or None
            created_at = item.get("created_at")
            if not event_id or not author_id or not created_at:
                continue
            username = users.get(author_id, "")
            if not username:
                continue
            events.append(
                SocialEvent(
                    source="x",
                    external_event_id=event_id,
                    author_source_id=author_id,
                    author_username=username,
                    published_at_ms=_timestamp_ms(str(created_at)),
                    detected_at_ms=detected_at_ms,
                    text=str(item.get("text") or ""),
                    url=f"https://x.com/{username}/status/{event_id}",
                    raw_json=json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                )
            )
        return sorted(events, key=lambda item: (item.published_at_ms, item.external_event_id))
