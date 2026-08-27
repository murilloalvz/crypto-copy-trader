from dataclasses import dataclass


@dataclass(frozen=True)
class SocialEvent:
    """One normalized external event; it never authorizes a market action."""

    source: str
    external_event_id: str
    author_source_id: str | None
    author_username: str
    published_at_ms: int
    detected_at_ms: int
    text: str
    url: str | None
    raw_json: str

    @property
    def detection_latency_ms(self) -> int:
        return max(0, self.detected_at_ms - self.published_at_ms)
