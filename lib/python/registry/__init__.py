"""
Model Registry — Task-aware model resolution across all AI domains.

Provides leaderboard-backed resolution that ensures the right model is
used for each task. Domain boundaries are enforced: resolve("music")
will never return a text model.

Quick start:
    from registry import ModelRegistry, Domain

    r = ModelRegistry(".")
    r.refresh(credentials)
    print(r.resolve("code"))    # -> best available code model
    print(r.resolve("music"))   # -> music model or None

Module-level convenience:
    from registry import resolve, refresh, best, Domain

    refresh(credentials)
    print(resolve("code"))
    print(best(Domain.MUSIC))
"""

from .domains import Domain, PROVIDER_DOMAINS, providers_for_domain
from .leaderboard import RankedModel, normalize_provider, match_model_id
from .registry import (
    ModelRegistry,
    RegistryEntry,
    resolve,
    refresh,
    best,
)

__all__ = [
    "ModelRegistry",
    "RegistryEntry",
    "Domain",
    "PROVIDER_DOMAINS",
    "RankedModel",
    "resolve",
    "refresh",
    "best",
    "normalize_provider",
    "match_model_id",
    "providers_for_domain",
]
