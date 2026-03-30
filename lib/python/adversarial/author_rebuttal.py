"""Author rebuttal step — calls Anthropic Claude to defend code.

Uses the Anthropic Messages API directly (no SDK dependency).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

from .prompts import AUTHOR_SYSTEM, build_author_prompt, parse_author_response

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_TIMEOUT = 120


def _call_anthropic(prompt: str, model: str, api_key: str) -> str:
    """Make a single Anthropic Messages API call and return text response."""
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "system": AUTHOR_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    last_exc: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            _ANTHROPIC_URL,
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 529) and attempt < 2:
                wait = (attempt + 1) * 30
                print(f"  Anthropic API {e.code}, retrying in {wait}s...",
                      file=sys.stderr)
                time.sleep(wait)
                last_exc = e
                continue
            raise
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected Anthropic response structure: {exc}") from exc
    raise last_exc  # type: ignore[misc]


def run_author_rebuttal(
    challenger_output: dict,
    file_data: list[dict],
    model: str,
    api_key: str,
) -> dict:
    """Call Claude to defend code against challenger's critique.

    Returns:
        Parsed author output dict with responses, counts, and unresolved list.
    """
    print("  Calling Claude author rebuttal...", file=sys.stderr)

    prompt = build_author_prompt(file_data, challenger_output)
    text = _call_anthropic(prompt, model, api_key)
    result = parse_author_response(text)

    print(f"  Author accepted {result.get('accepted_count', 0)}, "
          f"rebutted {result.get('rebutted_count', 0)}", file=sys.stderr)
    return result
