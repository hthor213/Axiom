"""Arbiter step — calls OpenAI GPT to resolve disputed issues.

Uses the OpenAI Chat Completions API directly (no SDK dependency).
Only invoked when the author rebuts some challenger issues.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

from .prompts import ARBITER_SYSTEM, build_arbiter_prompt, parse_arbiter_response

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = 120


def _call_openai(prompt: str, model: str, api_key: str) -> str:
    """Make a single OpenAI Chat Completions API call and return text response."""
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": ARBITER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 4096,
    }).encode()

    last_exc: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            _OPENAI_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 529) and attempt < 2:
                wait = (attempt + 1) * 30
                print(f"  OpenAI API {e.code}, retrying in {wait}s...",
                      file=sys.stderr)
                time.sleep(wait)
                last_exc = e
                continue
            raise
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected OpenAI response structure: {exc}") from exc
    raise last_exc  # type: ignore[misc]


def run_arbiter(
    challenger_output: dict,
    author_output: dict,
    model: str,
    api_key: str,
) -> dict:
    """Call GPT to arbitrate disputed issues.

    Returns:
        Parsed arbiter output dict with rulings and summary.
    """
    print("  Calling GPT arbiter...", file=sys.stderr)

    prompt = build_arbiter_prompt(challenger_output, author_output)
    text = _call_openai(prompt, model, api_key)
    result = parse_arbiter_response(text)

    result.setdefault("rulings", [])
    result.setdefault("summary", "")

    challenger_wins = sum(1 for r in result["rulings"] if r.get("side") == "challenger")
    author_wins = sum(1 for r in result["rulings"] if r.get("side") == "author")
    print(f"  Arbiter: challenger wins {challenger_wins}, author wins {author_wins}",
          file=sys.stderr)

    return result
