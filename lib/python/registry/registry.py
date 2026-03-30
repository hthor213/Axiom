"""
Model registry — task-aware model resolution across all AI domains.

Maintains a cached registry of leaderboard rankings cross-referenced
with available API keys, ensuring domain-safe resolution (e.g.,
resolve("music") never returns a text model).
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .domains import Domain, PROVIDER_DOMAINS, providers_for_domain
from .leaderboard import (
    RankedModel,
    fetch_all_rankings,
    match_model_id,
)
from .provider_models import fetch_all_provider_models

CACHE_FILE = ".model-registry.json"
CACHE_MAX_AGE = timedelta(days=28)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class RegistryEntry:
    """Per-domain registry entry with ranked models and best available."""

    domain: str
    ranked: list[RankedModel] = field(default_factory=list)
    best_available: str | None = None


# ---------------------------------------------------------------------------
# Main registry class
# ---------------------------------------------------------------------------
class ModelRegistry:
    """Task-aware model registry with leaderboard-backed resolution.

    The registry knows which AI model is best for every task domain and
    routes tasks to the right model. Domain boundaries are enforced:
    resolve("music") will NEVER return a text model.

    Usage:
        registry = ModelRegistry("/path/to/project")
        registry.refresh(credentials)
        model_id = registry.resolve("code")  # -> "claude-opus-4-6-20250414"
    """

    def __init__(self, root: str):
        """Initialize a registry rooted at the given directory.

        Args:
            root: Project root directory where .model-registry.json is stored.
        """
        self.root = root
        self.entries: dict[str, RegistryEntry] = {}
        self.available_keys: list[str] = []
        self.fetched_at: str = ""

    def refresh(self, credentials: dict) -> None:
        """Fetch leaderboards and provider model lists, cross-reference, update registry.

        Args:
            credentials: Dict mapping provider name to API key (or None).
                         Expected keys: "anthropic", "google", "openai", plus
                         optional "suno", "elevenlabs", "runway", etc.
        """
        # Determine which providers we have keys for
        self.available_keys = [p for p, k in credentials.items() if k]

        # Fetch leaderboard rankings from all sources
        aa_key = (
            credentials.get("artificial_analysis")
            or os.environ.get("ARTIFICIAL_ANALYSIS_KEY")
        )
        all_ranked = fetch_all_rankings(aa_api_key=aa_key)

        # Fetch available model IDs from provider APIs
        provider_models = fetch_all_provider_models(credentials)

        # Build a flat list of all available model IDs across providers
        all_available: dict[str, list[str]] = {}
        for provider, models in provider_models.items():
            if models:
                all_available[provider] = models

        # Group rankings by domain
        domain_rankings: dict[str, list[RankedModel]] = {}
        for rm in all_ranked:
            domain_key = rm.domain.value if isinstance(rm.domain, Domain) else rm.domain
            domain_rankings.setdefault(domain_key, []).append(rm)

        # Build registry entries for each domain
        self.entries = {}
        for domain in Domain:
            d = domain.value
            ranked = domain_rankings.get(d, [])
            # Sort by score descending
            ranked.sort(key=lambda r: r.score, reverse=True)

            # Find best available model: iterate ranked models, check if
            # their provider has a key AND the model ID is available
            best_available = self._find_best_available(
                ranked, domain, all_available
            )

            self.entries[d] = RegistryEntry(
                domain=d,
                ranked=ranked,
                best_available=best_available,
            )

        self.fetched_at = datetime.now(timezone.utc).isoformat()
        self.save()

    def _find_best_available(
        self,
        ranked: list[RankedModel],
        domain: Domain,
        all_available: dict[str, list[str]],
    ) -> str | None:
        """Find the highest-ranked model we can actually call for a domain.

        Enforces domain boundaries: only considers providers that serve
        this domain according to PROVIDER_DOMAINS.

        Args:
            ranked: Models sorted by score descending.
            domain: The target domain.
            all_available: Dict of provider -> list of available model IDs.

        Returns:
            Model ID string, or None if no usable model found.
        """
        valid_providers = set(providers_for_domain(domain))

        for rm in ranked:
            provider = rm.provider
            # Enforce domain boundary
            if provider not in valid_providers:
                continue
            # Check if we have a key for this provider
            if provider not in self.available_keys:
                continue
            # Check if the provider's models are listed
            provider_model_list = all_available.get(provider, [])
            if not provider_model_list:
                # Provider has key but no model listing API (e.g., suno, runway)
                # Trust the leaderboard name as the model ID
                return rm.name
            # Try to match leaderboard name to an actual model ID
            model_id = match_model_id(rm.name, provider_model_list)
            if model_id:
                return model_id

        return None

    def resolve(self, domain: str | Domain, provider: str | None = None) -> str | None:
        """Get the best available model for a domain, optionally filtered by provider.

        CRITICAL: This respects domain boundaries. resolve("music") will
        NEVER return a text model. If no provider for the requested domain
        has an API key, returns None.

        Args:
            domain: Domain string or Domain enum value.
            provider: Optional provider filter (e.g., "google", "anthropic", "openai").
                      When specified, returns the best model from that specific provider.
                      Used by the adversarial pipeline to get distinct models per provider.

        Returns:
            Model ID string, or None if no model available for this domain.
        """
        d = domain.value if isinstance(domain, Domain) else domain
        entry = self.entries.get(d)
        if entry is None:
            return None
        if provider is None:
            return entry.best_available
        # Filter by provider — return best available from that specific provider
        from .leaderboard import match_model_id
        from .provider_models import fetch_anthropic_models, fetch_google_models, fetch_openai_models
        # We need the available models for this provider to match IDs
        # Use the name as fallback if no model list available
        for model in entry.ranked:
            if model.provider == provider:
                return model.name  # Leaderboard name (caller can match to API ID)
        return None

    def best(self, domain: str | Domain) -> RankedModel | None:
        """Get the globally best model for a domain, regardless of key availability.

        Args:
            domain: Domain string or Domain enum value.

        Returns:
            Top-ranked RankedModel, or None if no rankings for this domain.
        """
        d = domain.value if isinstance(domain, Domain) else domain
        entry = self.entries.get(d)
        if entry is None or not entry.ranked:
            return None
        return entry.ranked[0]

    def save(self) -> None:
        """Write the registry to .model-registry.json in the root directory."""
        cache_path = Path(self.root) / CACHE_FILE
        data = {
            "fetched_at": self.fetched_at,
            "available_keys": self.available_keys,
            "domains": {},
        }
        for d, entry in self.entries.items():
            data["domains"][d] = {
                "ranked": [
                    {
                        "model": rm.name,
                        "provider": rm.provider,
                        "score": rm.score,
                        "source": rm.source,
                        "rank": rm.rank,
                    }
                    for rm in entry.ranked
                ],
                "best_available": entry.best_available,
            }
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    @classmethod
    def load(cls, root: str) -> "ModelRegistry":
        """Load a registry from .model-registry.json.

        Args:
            root: Project root directory.

        Returns:
            Loaded ModelRegistry, or an empty registry if the cache
            file is missing or corrupt.
        """
        registry = cls(root)
        cache_path = Path(root) / CACHE_FILE
        if not cache_path.exists():
            return registry

        try:
            with open(cache_path) as f:
                data = json.load(f)

            registry.fetched_at = data.get("fetched_at", "")
            registry.available_keys = data.get("available_keys", [])

            for d, entry_data in data.get("domains", {}).items():
                ranked = []
                for rm_data in entry_data.get("ranked", []):
                    # Map domain string to Domain enum
                    try:
                        domain_enum = Domain(d)
                    except ValueError:
                        domain_enum = d  # type: ignore

                    ranked.append(
                        RankedModel(
                            name=rm_data.get("model", ""),
                            provider=rm_data.get("provider", ""),
                            score=rm_data.get("score", 0),
                            domain=domain_enum,
                            source=rm_data.get("source", ""),
                            rank=rm_data.get("rank", 0),
                        )
                    )

                registry.entries[d] = RegistryEntry(
                    domain=d,
                    ranked=ranked,
                    best_available=entry_data.get("best_available"),
                )

        except Exception:
            # Return empty registry on any parse error
            return cls(root)

        return registry

    def is_stale(self) -> bool:
        """Check if the registry is stale (older than 28 days or empty).

        Returns:
            True if the registry should be refreshed.
        """
        if not self.fetched_at:
            return True
        try:
            fetched = datetime.fromisoformat(self.fetched_at)
            return datetime.now(timezone.utc) - fetched > CACHE_MAX_AGE
        except (ValueError, TypeError):
            return True

    def resolve_or_refresh(
        self, domain: str | Domain, credentials: dict
    ) -> str | None:
        """Load cached registry, refresh if stale, then resolve.

        Convenience method that handles the full lifecycle: load from
        cache, check staleness, refresh if needed, then resolve.

        Args:
            domain: Domain string or Domain enum value.
            credentials: Dict mapping provider name to API key.

        Returns:
            Model ID string, or None if no model available.
        """
        # If we have no entries, try loading from cache
        if not self.entries:
            loaded = self.load(self.root)
            self.entries = loaded.entries
            self.available_keys = loaded.available_keys
            self.fetched_at = loaded.fetched_at

        # Refresh if stale or empty
        if self.is_stale():
            self.refresh(credentials)

        return self.resolve(domain)

    def summary(self) -> str:
        """Return a human-readable summary of the registry.

        Returns:
            Multi-line string showing per-domain best available model.
        """
        lines = [
            f"Model Registry (fetched: {self.fetched_at or 'never'})",
            f"Available keys: {', '.join(self.available_keys) or 'none'}",
            "",
        ]
        for domain in Domain:
            d = domain.value
            entry = self.entries.get(d)
            if entry is None:
                lines.append(f"  {d:20s} — no data")
                continue
            best = entry.best_available or "(none available)"
            total = len(entry.ranked)
            top_name = entry.ranked[0].name if entry.ranked else "—"
            lines.append(
                f"  {d:20s} best={best:40s} top_ranked={top_name} ({total} models)"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------
_default_registry: ModelRegistry | None = None


def _get_default_registry() -> ModelRegistry:
    """Get or create the default module-level registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelRegistry(".")
    return _default_registry


def resolve(domain: str | Domain) -> str | None:
    """Resolve the best available model for a domain using the default registry.

    Args:
        domain: Domain string or Domain enum value.

    Returns:
        Model ID string, or None.
    """
    return _get_default_registry().resolve(domain)


def refresh(credentials: dict) -> None:
    """Refresh the default registry with new leaderboard data.

    Args:
        credentials: Dict mapping provider name to API key.
    """
    _get_default_registry().refresh(credentials)


def best(domain: str | Domain) -> RankedModel | None:
    """Get the globally best model for a domain using the default registry.

    Args:
        domain: Domain string or Domain enum value.

    Returns:
        Top-ranked RankedModel, or None.
    """
    return _get_default_registry().best(domain)
