"""
Fetch available model IDs from each provider's listing API.

Uses only stdlib (urllib). Each function returns a list of model ID strings
that are currently available with the given API key, or an empty list on failure.
"""

import json
import urllib.request
import urllib.error

REQUEST_TIMEOUT = 10  # seconds


def _api_get(url: str, headers: dict | None = None) -> dict:
    """Perform a GET request and return parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    return json.loads(resp.read().decode("utf-8"))


def fetch_anthropic_models(api_key: str) -> list[str]:
    """Fetch all available model IDs from the Anthropic API.

    Args:
        api_key: Anthropic API key.

    Returns:
        List of model ID strings (e.g. ["claude-opus-4-6-20250414", ...]).
        Empty list on failure.
    """
    try:
        data = _api_get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        return [m["id"] for m in data.get("data", []) if m.get("id", "").startswith("claude-")]
    except Exception:
        return []


def fetch_google_models(api_key: str) -> list[str]:
    """Fetch all available Gemini model IDs from the Google API.

    Args:
        api_key: Google API key.

    Returns:
        List of model ID strings (e.g. ["gemini-2.5-pro", ...]).
        Empty list on failure.
    """
    try:
        data = _api_get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
        )
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            if name.startswith("models/gemini-"):
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    models.append(name.removeprefix("models/"))
        return models
    except Exception:
        return []


def fetch_openai_models(api_key: str) -> list[str]:
    """Fetch all available model IDs from the OpenAI API.

    Args:
        api_key: OpenAI API key.

    Returns:
        List of model ID strings (e.g. ["gpt-4o", "o1-preview", ...]).
        Empty list on failure.
    """
    try:
        data = _api_get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def fetch_all_provider_models(credentials: dict) -> dict[str, list[str]]:
    """Fetch model listings from all providers with available keys.

    Args:
        credentials: Dict mapping provider name to API key (or None).

    Returns:
        Dict mapping provider name to list of available model IDs.
    """
    fetchers = {
        "anthropic": fetch_anthropic_models,
        "google": fetch_google_models,
        "openai": fetch_openai_models,
    }

    result: dict[str, list[str]] = {}
    for provider, fetcher in fetchers.items():
        key = credentials.get(provider)
        if key:
            result[provider] = fetcher(key)
        else:
            result[provider] = []

    return result
