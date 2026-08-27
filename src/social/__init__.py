"""Read-only social/event intelligence primitives."""

from src.social.models import SocialEvent
from src.social.service import SocialCollectionResult, collect_social_events

__all__ = ["SocialCollectionResult", "SocialEvent", "collect_social_events"]
