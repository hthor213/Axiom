"""
Fetch model rankings from canonical leaderboard sources.

Source 1: HuggingFace dataset (arena.ai text + vision overall).
Source 2: Artificial Analysis API (media domains — requires API key).

Uses only stdlib (urllib, json). All network calls have a 10s timeout.
"""

import json
import os
import re
import urllib.request
import urllib.error
from dataclasses import dataclass

from .domains import Domain

REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class RankedModel:
    """A model entry from a leaderboard source."""

    name: str        # Display name from leaderboard
    provider: str    # Normalized provider key
    score: float     # ELO or quality score
    domain: Domain
    source: str      # "arena.ai" or "artificialanalysis.ai"
    rank: int = 0


# ---------------------------------------------------------------------------
# Provider normalization
# ---------------------------------------------------------------------------
_PROVIDER_MAP: dict[str, str] = {
    # Canonical mappings from leaderboard org names to our provider keys
    "anthropic": "anthropic",
    "google": "google",
    "google deepmind": "google",
    "google/deepmind": "google",
    "deepmind": "google",
    "openai": "openai",
    "meta": "meta",
    "meta ai": "meta",
    "mistral": "mistral",
    "mistral ai": "mistral",
    "cohere": "cohere",
    "amazon": "amazon",
    "aws": "amazon",
    "microsoft": "microsoft",
    "alibaba": "alibaba",
    "qwen": "alibaba",
    "qwen team": "alibaba",
    "alibaba cloud": "alibaba",
    "bytedance": "bytedance",
    "deepseek": "deepseek",
    "deepseek ai": "deepseek",
    "xai": "xai",
    "x.ai": "xai",
    "nvidia": "nvidia",
    "suno": "suno",
    "elevenlabs": "elevenlabs",
    "runway": "runway",
    "midjourney": "midjourney",
    "flux": "flux",
    "black forest labs": "flux",
    "stability": "stability",
    "stability ai": "stability",
    "ideogram": "ideogram",
    "recraft": "recraft",
    "minimax": "minimax",
    "luma": "luma",
    "luma ai": "luma",
    "kling": "kling",
    "kuaishou": "kling",
    "pika": "pika",
    "veo": "google",
    "imagen": "google",
}


def normalize_provider(org_name: str) -> str:
    """Map a leaderboard organization name to our normalized provider key.

    Args:
        org_name: Organization name as it appears on the leaderboard.

    Returns:
        Normalized provider key (e.g., "anthropic", "google", "openai").
        Falls back to lowercased org_name if no mapping exists.
    """
    if not org_name:
        return "unknown"
    key = org_name.strip().lower()
    return _PROVIDER_MAP.get(key, key)


# ---------------------------------------------------------------------------
# Fuzzy model ID matching
# ---------------------------------------------------------------------------

# Common display-name-to-model-ID fragments for matching
_MODEL_ALIASES: dict[str, list[str]] = {
    # Anthropic
    "claude opus 4": ["claude-opus-4"],
    "claude 4 opus": ["claude-opus-4"],
    "claude sonnet 4": ["claude-sonnet-4"],
    "claude 4 sonnet": ["claude-sonnet-4"],
    "claude 3.5 sonnet": ["claude-3-5-sonnet"],
    "claude 3.5 haiku": ["claude-3-5-haiku"],
    "claude 3 opus": ["claude-3-opus"],
    "claude 3 sonnet": ["claude-3-sonnet"],
    "claude 3 haiku": ["claude-3-haiku"],
    # Google
    "gemini 2.5 pro": ["gemini-2.5-pro"],
    "gemini 2.5 flash": ["gemini-2.5-flash"],
    "gemini 2.0 pro": ["gemini-2.0-pro"],
    "gemini 2.0 flash": ["gemini-2.0-flash"],
    "gemini 1.5 pro": ["gemini-1.5-pro"],
    "gemini 1.5 flash": ["gemini-1.5-flash"],
    "gemini pro": ["gemini-pro"],
    "gemini ultra": ["gemini-ultra"],
    "gemini 3.1 pro": ["gemini-3.1-pro"],
    "gemini 3.0 pro": ["gemini-3.0-pro"],
    "gemini 3 pro": ["gemini-3.0-pro", "gemini-3-pro"],
    # OpenAI
    "gpt-4o": ["gpt-4o"],
    "gpt-4o mini": ["gpt-4o-mini"],
    "gpt-4 turbo": ["gpt-4-turbo"],
    "gpt-4": ["gpt-4"],
    "gpt-5": ["gpt-5"],
    "gpt-5.4": ["gpt-5.4"],
    "o1": ["o1"],
    "o1 mini": ["o1-mini"],
    "o1 preview": ["o1-preview"],
    "o3": ["o3"],
    "o3 mini": ["o3-mini"],
    "o4 mini": ["o4-mini"],
    # DeepSeek
    "deepseek v3": ["deepseek-v3", "deepseek-chat"],
    "deepseek r1": ["deepseek-r1", "deepseek-reasoner"],
    "deepseek coder": ["deepseek-coder"],
}


def _normalize_name(name: str) -> str:
    """Normalize a model display name for matching: lowercase, strip special chars."""
    s = name.lower().strip()
    # Remove common suffixes/prefixes that vary between leaderboard and API
    for remove in ["(", ")", "[", "]", " - ", " api", " latest", " preview"]:
        s = s.replace(remove, " ")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def match_model_id(leaderboard_name: str, available_models: list[str]) -> str | None:
    """Fuzzy-match a leaderboard display name to an actual API model ID.

    Strategy (in order):
    1. Exact match (leaderboard name is already a model ID).
    2. Alias table lookup.
    3. Token-based fuzzy matching — extract version numbers and tier names,
       find the best-matching available model.

    Args:
        leaderboard_name: Display name from the leaderboard (e.g., "Claude 3.5 Sonnet").
        available_models: List of actual API model IDs.

    Returns:
        Best matching model ID, or None if no reasonable match found.
    """
    if not available_models:
        return None

    name = leaderboard_name.strip()
    name_lower = name.lower()

    # 1. Exact match — leaderboard name is already an API model ID
    if name in available_models or name_lower in [m.lower() for m in available_models]:
        for m in available_models:
            if m.lower() == name_lower:
                return m

    # 2. Alias table lookup
    norm = _normalize_name(name)
    for alias_key, alias_ids in _MODEL_ALIASES.items():
        if alias_key in norm:
            for aid in alias_ids:
                # Find best match among available models that contain the alias fragment
                matches = [m for m in available_models if aid in m.lower()]
                if matches:
                    # Prefer the shortest match (most specific) or latest by name
                    matches.sort(key=lambda m: (len(m), m), reverse=True)
                    return matches[0]

    # 3. Token-based fuzzy matching
    # Extract meaningful tokens from the leaderboard name
    name_tokens = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", name_lower))
    # Remove generic tokens
    name_tokens -= {"the", "a", "an", "model", "version", "v", "by"}

    best_match: str | None = None
    best_score = 0

    for model_id in available_models:
        model_lower = model_id.lower()
        model_tokens = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", model_lower))

        # Score = number of matching tokens
        overlap = name_tokens & model_tokens
        score = len(overlap)

        # Bonus for version number match
        name_versions = set(re.findall(r"\d+\.\d+", name_lower))
        model_versions = set(re.findall(r"\d+\.\d+", model_lower))
        if name_versions and name_versions & model_versions:
            score += 3

        # Bonus for tier match (opus, sonnet, pro, flash, etc.)
        tiers = {"opus", "sonnet", "haiku", "pro", "flash", "ultra", "mini", "nano"}
        name_tiers = name_tokens & tiers
        model_tiers = model_tokens & tiers
        if name_tiers and name_tiers == model_tiers:
            score += 5
        elif name_tiers and model_tiers and name_tiers != model_tiers:
            score -= 10  # Penalize tier mismatch heavily

        # Bonus for provider name match
        providers = {"claude", "gemini", "gpt", "deepseek", "llama", "mistral", "command"}
        name_providers = name_tokens & providers
        model_providers = model_tokens & providers
        if name_providers and name_providers == model_providers:
            score += 5
        elif name_providers and model_providers and name_providers != model_providers:
            score -= 10  # Wrong provider

        if score > best_score:
            best_score = score
            best_match = model_id

    # Only return if we have a reasonable confidence
    if best_score >= 3:
        return best_match

    return None


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _api_get(url: str, headers: dict | None = None) -> dict | list:
    """Perform a GET request and return parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Source 1: HuggingFace dataset (arena.ai text + vision overall)
# ---------------------------------------------------------------------------
_HF_ARENA_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=mathewhe/chatbot-arena-elo"
    "&config=default&split=train&offset=0&length=300"
)


def fetch_arena_rankings() -> list[RankedModel]:
    """Fetch text/vision rankings from the HuggingFace chatbot-arena-elo dataset.

    Returns:
        List of RankedModel entries for Domain.TEXT (and Domain.VISION
        if vision scores are present), sorted by score descending.
        Returns empty list on failure.
    """
    try:
        data = _api_get(_HF_ARENA_URL)
    except Exception:
        return []

    rows = data.get("rows", [])
    results: list[RankedModel] = []

    for i, entry in enumerate(rows):
        row = entry.get("row", {})
        model_name = row.get("Model", "")
        score_raw = row.get("Arena Score")
        org = row.get("Organization", "")

        if not model_name or score_raw is None:
            continue

        try:
            score = float(score_raw)
        except (ValueError, TypeError):
            continue

        provider = normalize_provider(org)

        # Arena text dataset — assign to both CODE and TEXT domains
        for domain in (Domain.TEXT, Domain.CODE):
            results.append(
                RankedModel(
                    name=model_name,
                    provider=provider,
                    score=score,
                    domain=domain,
                    source="arena.ai",
                    rank=i + 1,
                )
            )

    # Sort by score descending and re-rank
    for domain in (Domain.TEXT, Domain.CODE):
        domain_models = [r for r in results if r.domain == domain]
        domain_models.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(domain_models):
            r.rank = i + 1

    return results


# ---------------------------------------------------------------------------
# Source 2: Artificial Analysis API (media domains)
# ---------------------------------------------------------------------------
_AA_BASE = "https://artificialanalysis.ai/api/v2/data"

_AA_ENDPOINTS: dict[Domain, str] = {
    Domain.TEXT_TO_IMAGE: f"{_AA_BASE}/media/text-to-image",
    Domain.TEXT_TO_VIDEO: f"{_AA_BASE}/media/text-to-video",
    Domain.IMAGE_TO_VIDEO: f"{_AA_BASE}/media/image-to-video",
    Domain.IMAGE_EDIT: f"{_AA_BASE}/media/image-editing",
    Domain.TEXT_TO_SPEECH: f"{_AA_BASE}/media/text-to-speech",
}


def _parse_aa_response(data: list | dict, domain: Domain) -> list[RankedModel]:
    """Parse an Artificial Analysis API response into RankedModel entries."""
    results: list[RankedModel] = []

    # The API may return a list directly or a dict with a "data" key
    items = data if isinstance(data, list) else data.get("data", data.get("models", []))
    if not isinstance(items, list):
        return results

    for item in items:
        if not isinstance(item, dict):
            continue

        # Try various field names for model name
        name = (
            item.get("model_name")
            or item.get("name")
            or item.get("model")
            or ""
        )
        if not name:
            continue

        # Try various field names for score
        score_raw = (
            item.get("arena_score")
            or item.get("elo_score")
            or item.get("quality_score")
            or item.get("score")
            or item.get("arena_elo")
        )
        if score_raw is None:
            continue

        try:
            score = float(score_raw)
        except (ValueError, TypeError):
            continue

        org = (
            item.get("provider")
            or item.get("organization")
            or item.get("creator")
            or ""
        )
        provider = normalize_provider(org)

        results.append(
            RankedModel(
                name=name,
                provider=provider,
                score=score,
                domain=domain,
                source="artificialanalysis.ai",
            )
        )

    # Sort by score descending and assign ranks
    results.sort(key=lambda r: r.score, reverse=True)
    for i, r in enumerate(results):
        r.rank = i + 1

    return results


def fetch_aa_rankings(api_key: str) -> list[RankedModel]:
    """Fetch media domain rankings from the Artificial Analysis API.

    Args:
        api_key: Artificial Analysis API key.

    Returns:
        List of RankedModel entries across all media domains.
        Returns empty list if no key provided or on total failure.
    """
    if not api_key:
        return []

    headers = {"x-api-key": api_key}
    all_results: list[RankedModel] = []

    for domain, url in _AA_ENDPOINTS.items():
        try:
            data = _api_get(url, headers=headers)
            models = _parse_aa_response(data, domain)
            all_results.extend(models)
        except Exception:
            # Skip this domain on failure, continue with others
            continue

    return all_results


# ---------------------------------------------------------------------------
# Combined fetch
# ---------------------------------------------------------------------------
def fetch_all_rankings(aa_api_key: str | None = None) -> list[RankedModel]:
    """Fetch rankings from all available sources.

    Args:
        aa_api_key: Optional Artificial Analysis API key. If None,
                    media domains are skipped gracefully.

    Returns:
        Combined list of RankedModel entries from all sources.
    """
    results = fetch_arena_rankings()

    if aa_api_key:
        results.extend(fetch_aa_rankings(aa_api_key))

    return results
