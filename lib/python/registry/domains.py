"""
Domain taxonomy for AI model capabilities.

Each domain represents a distinct AI task category. Models are ranked
per-domain, and resolution never crosses domain boundaries.
"""

from enum import Enum


class Domain(str, Enum):
    """AI task domains. Used as registry keys and domain boundaries."""

    CODE = "code"
    TEXT = "text"
    VISION = "vision"
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_EDIT = "image_edit"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_EDIT = "video_edit"
    MUSIC = "music"
    TEXT_TO_SPEECH = "text_to_speech"
    SEARCH = "search"
    DOCUMENT = "document"


# Which providers serve which domains.
# Used to enforce domain boundaries: resolve("music") can only return
# models from providers listed under Domain.MUSIC.
PROVIDER_DOMAINS: dict[str, list[Domain]] = {
    "anthropic": [Domain.CODE, Domain.TEXT, Domain.VISION, Domain.DOCUMENT],
    "google": [
        Domain.CODE,
        Domain.TEXT,
        Domain.VISION,
        Domain.DOCUMENT,
        Domain.TEXT_TO_IMAGE,
        Domain.TEXT_TO_VIDEO,
        Domain.IMAGE_TO_VIDEO,
        Domain.SEARCH,
    ],
    "openai": [
        Domain.CODE,
        Domain.TEXT,
        Domain.VISION,
        Domain.DOCUMENT,
        Domain.TEXT_TO_IMAGE,
        Domain.TEXT_TO_SPEECH,
        Domain.SEARCH,
    ],
    "suno": [Domain.MUSIC],
    "elevenlabs": [Domain.TEXT_TO_SPEECH, Domain.MUSIC],
    "runway": [Domain.TEXT_TO_VIDEO, Domain.IMAGE_TO_VIDEO, Domain.VIDEO_EDIT],
    "midjourney": [Domain.TEXT_TO_IMAGE, Domain.IMAGE_EDIT],
    "flux": [Domain.TEXT_TO_IMAGE],
}


def providers_for_domain(domain: Domain) -> list[str]:
    """Return all providers that serve a given domain."""
    return [p for p, domains in PROVIDER_DOMAINS.items() if domain in domains]
