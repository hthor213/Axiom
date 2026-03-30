"""
Query provider model-listing APIs and resolve the current top-tier model for each.

Uses only stdlib (urllib.request, json, dataclasses). No SDK dependencies.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Fallback model IDs (used when an API call fails)
# ---------------------------------------------------------------------------
FALLBACK_ANTHROPIC = "claude-opus-4-6-20250414"
FALLBACK_GOOGLE = "gemini-3.1-pro-preview"
FALLBACK_OPENAI = "gpt-5.4"

CACHE_FILE = ".adversarial-models.json"
CACHE_MAX_AGE = timedelta(hours=24)
REQUEST_TIMEOUT = 10  # seconds


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class ResolvedModels:
    anthropic: str
    google: str
    openai: str
    resolved_at: str
    fallback_used: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _api_get(url: str, headers: dict = None) -> dict:
    """Perform a GET request and return parsed JSON. Raises on failure."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Anthropic resolver
# ---------------------------------------------------------------------------
_ANTHROPIC_TIER = {"opus": 0, "sonnet": 1, "haiku": 2}


def _resolve_anthropic(api_key: str) -> str:
    """Pick the top-tier Anthropic model from the listing API."""
    data = _api_get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    models = [m for m in data.get("data", []) if m.get("id", "").startswith("claude-")]
    if not models:
        raise ValueError("No claude- models returned by API")

    def sort_key(m):
        mid = m["id"].lower()
        tier = 99
        for name, rank in _ANTHROPIC_TIER.items():
            if name in mid:
                tier = rank
                break
        # Negate created_at for descending sort (latest first)
        created = m.get("created_at", "")
        return (tier, created)

    models.sort(key=sort_key, reverse=False)
    # Within same tier, pick the latest created
    # Group by tier, then pick max created_at within best tier
    best_tier = sort_key(models[0])[0]
    same_tier = [m for m in models if sort_key(m)[0] == best_tier]
    same_tier.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return same_tier[0]["id"]


# ---------------------------------------------------------------------------
# Google resolver
# ---------------------------------------------------------------------------
_GOOGLE_TIER = {"ultra": 0, "pro": 1, "flash": 2, "nano": 3}


def _resolve_google(api_key: str) -> str:
    """Pick the top-tier Google Gemini model from the listing API."""
    data = _api_get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
    )

    # Exclude non-text models (image, audio, tts, computer-use, lite, native-audio)
    _GOOGLE_EXCLUDE = {"image", "audio", "tts", "lite", "computer-use", "native-audio"}

    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if not (name.startswith("models/gemini-") and "generateContent" in methods):
            continue
        name_lower = name.lower()
        if any(excl in name_lower for excl in _GOOGLE_EXCLUDE):
            continue
        models.append(m)

    if not models:
        raise ValueError("No gemini- generateContent models returned by API")

    def sort_key(m):
        name = m["name"].lower()
        tier = 99
        for label, rank in _GOOGLE_TIER.items():
            if label in name:
                tier = rank
                break
        # Extract version number (e.g. "2.5" from "gemini-2.5-pro")
        version = 0.0
        parts = name.replace("models/gemini-", "").split("-")
        for p in parts:
            try:
                version = float(p)
                break
            except ValueError:
                continue
        token_limit = m.get("inputTokenLimit", 0)
        return (tier, -version, -token_limit)

    models.sort(key=sort_key)
    # Strip "models/" prefix for API calls
    return models[0]["name"].removeprefix("models/")


# ---------------------------------------------------------------------------
# OpenAI resolver
# ---------------------------------------------------------------------------
_OPENAI_EXCLUDE = {"mini", "turbo", "nano", "audio", "realtime", "tts", "transcribe", "search", "codex"}


def _resolve_openai(api_key: str) -> str:
    """Pick the top-tier OpenAI model from the listing API."""
    data = _api_get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not (mid.startswith("gpt-") or mid.startswith("o")):
            continue
        mid_lower = mid.lower()
        if any(ex in mid_lower for ex in _OPENAI_EXCLUDE):
            continue
        models.append(m)

    if not models:
        raise ValueError("No flagship OpenAI models returned by API")

    models.sort(key=lambda m: m.get("created", 0), reverse=True)
    return models[0]["id"]


# ---------------------------------------------------------------------------
# Top-level resolver
# ---------------------------------------------------------------------------
def resolve_models(credentials: dict) -> ResolvedModels:
    """Query all three provider APIs and return resolved top-tier models."""
    fallback_used: dict = {}
    results: dict = {}

    resolvers = {
        "anthropic": (_resolve_anthropic, FALLBACK_ANTHROPIC),
        "google": (_resolve_google, FALLBACK_GOOGLE),
        "openai": (_resolve_openai, FALLBACK_OPENAI),
    }

    for provider, (resolver_fn, fallback) in resolvers.items():
        api_key = credentials.get(provider)
        if not api_key:
            results[provider] = fallback
            fallback_used[provider] = "no API key provided"
            continue
        try:
            results[provider] = resolver_fn(api_key)
        except Exception as e:
            results[provider] = fallback
            fallback_used[provider] = str(e)

    return ResolvedModels(
        anthropic=results["anthropic"],
        google=results["google"],
        openai=results["openai"],
        resolved_at=datetime.now(timezone.utc).isoformat(),
        fallback_used=fallback_used,
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def load_cached_models(project_root: str) -> Optional[ResolvedModels]:
    """Load from .adversarial-models.json if it exists and is recent (< 24h)."""
    cache_path = Path(project_root) / CACHE_FILE
    if not cache_path.exists():
        return None
    try:
        with open(cache_path) as f:
            data = json.load(f)
        resolved_at = datetime.fromisoformat(data["resolved_at"])
        if datetime.now(timezone.utc) - resolved_at > CACHE_MAX_AGE:
            return None
        return ResolvedModels(**data)
    except Exception:
        return None


def save_cached_models(models: ResolvedModels, project_root: str) -> None:
    """Cache resolved models to .adversarial-models.json."""
    cache_path = Path(project_root) / CACHE_FILE
    with open(cache_path, "w") as f:
        json.dump(asdict(models), f, indent=2)
        f.write("\n")


def resolve_or_load(credentials: dict, project_root: str) -> ResolvedModels:
    """Use cache if fresh, otherwise resolve and cache."""
    cached = load_cached_models(project_root)
    if cached is not None:
        return cached
    models = resolve_models(credentials)
    save_cached_models(models, project_root)
    return models


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------
def run_pipeline(credentials: dict, project_root: str = None) -> ResolvedModels:
    """Resolve models (with caching if project_root provided).

    This is the main entry point for the adversarial evaluation pipeline's
    model resolution step.
    """
    if project_root:
        return resolve_or_load(credentials, project_root)
    return resolve_models(credentials)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Determine platform root (parent of lib/)
    _this_dir = Path(__file__).resolve().parent
    _platform_root = _this_dir.parent.parent.parent

    sys.path.insert(0, str(_this_dir.parent))
    from adversarial.credentials import load_credentials

    print("Loading credentials...")
    creds = load_credentials(platform_root=str(_platform_root))
    available = [p for p, k in creds.items() if k]
    missing = [p for p, k in creds.items() if not k]
    print(f"  Available: {', '.join(available) or 'none'}")
    if missing:
        print(f"  Missing:   {', '.join(missing)}")

    print("\nResolving models...")
    resolved = resolve_models(creds)

    print(f"\n  Anthropic: {resolved.anthropic}")
    print(f"  Google:    {resolved.google}")
    print(f"  OpenAI:    {resolved.openai}")
    print(f"  Resolved:  {resolved.resolved_at}")
    if resolved.fallback_used:
        print(f"  Fallbacks: {resolved.fallback_used}")
