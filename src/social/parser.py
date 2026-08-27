import json
import re
from dataclasses import dataclass
from enum import Enum


class SocialEventType(str, Enum):
    GENERAL_POST = "GENERAL_POST"
    TOKEN_MENTION = "TOKEN_MENTION"
    PROJECT_ANNOUNCEMENT = "PROJECT_ANNOUNCEMENT"
    LAUNCH = "LAUNCH"
    LISTING = "LISTING"
    PARTNERSHIP = "PARTNERSHIP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParsedSocialEvent:
    event_type: SocialEventType
    tickers: tuple[str, ...]
    urls: tuple[str, ...]
    mint_candidates: tuple[str, ...]
    hashtags: tuple[str, ...]


TICKER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9]{1,9})(?![A-Za-z0-9_])")
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
MINT_PATTERN = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])"
)
HASHTAG_PATTERN = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{1,49})")

CLASSIFICATION_RULES = (
    (
        SocialEventType.LISTING,
        re.compile(r"\b(listing|listed|will list|now listed|trading pair)\b", re.IGNORECASE),
    ),
    (
        SocialEventType.LAUNCH,
        re.compile(
            r"\b(launch|launching|launched|token is live|mint is live|now live)\b",
            re.IGNORECASE,
        ),
    ),
    (
        SocialEventType.PARTNERSHIP,
        re.compile(
            r"\b(partnership|partnered|partnering|collaboration|collaborating)\b",
            re.IGNORECASE,
        ),
    ),
    (
        SocialEventType.PROJECT_ANNOUNCEMENT,
        re.compile(
            r"\b(announce|announcing|announcement|introducing|unveil|unveiling)\b",
            re.IGNORECASE,
        ),
    ),
)


def _unique(values, *, transform=lambda item: item) -> tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        normalized = transform(value)
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def _payload_urls(raw_json: str | None) -> tuple[str, ...]:
    try:
        payload = json.loads(raw_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return ()
    entities = payload.get("entities") if isinstance(payload, dict) else None
    url_items = entities.get("urls") if isinstance(entities, dict) else None
    if not isinstance(url_items, list):
        return ()
    values = []
    for item in url_items:
        if not isinstance(item, dict):
            continue
        value = item.get("unwound_url") or item.get("expanded_url") or item.get("url")
        if value:
            values.append(str(value))
    return tuple(values)


def parse_social_event(text: str | None, raw_json: str | None = None) -> ParsedSocialEvent:
    value = text or ""
    tickers = _unique(TICKER_PATTERN.findall(value), transform=str.upper)
    urls = _unique(
        [item.rstrip(".,;:!?]}\'") for item in URL_PATTERN.findall(value)]
        + list(_payload_urls(raw_json))
    )
    mint_candidates = _unique(MINT_PATTERN.findall(value))
    hashtags = _unique(HASHTAG_PATTERN.findall(value), transform=str.lower)

    event_type = SocialEventType.UNKNOWN
    if value.strip():
        event_type = SocialEventType.GENERAL_POST
        if tickers or mint_candidates:
            event_type = SocialEventType.TOKEN_MENTION
        for candidate, pattern in CLASSIFICATION_RULES:
            if pattern.search(value):
                event_type = candidate
                break

    return ParsedSocialEvent(
        event_type=event_type,
        tickers=tickers,
        urls=urls,
        mint_candidates=mint_candidates,
        hashtags=hashtags,
    )
