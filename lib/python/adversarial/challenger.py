"""Challenger step — calls Google Gemini to adversarially review code.

Uses the Gemini REST API directly (no SDK dependency).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

from .prompts import (
    CHALLENGER_SYSTEM,
    CHALLENGER_COUNTER_SYSTEM,
    build_challenger_prompt,
    build_counter_rebuttal_prompt,
    parse_challenger_response,
    parse_counter_rebuttal_response,
)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_TIMEOUT = 120


def _call_gemini(
    prompt: str, model: str, api_key: str, system: str = CHALLENGER_SYSTEM
) -> str:
    """Make a single Gemini API call and return text response."""
    url = f"{_GEMINI_URL.format(model=model)}?key={api_key}"

    body = json.dumps({
        "systemInstruction": {
            "parts": [{"text": system}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        },
    }).encode()

    last_exc: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 529) and attempt < 2:
                wait = (attempt + 1) * 30
                print(f"  Gemini API {e.code}, retrying in {wait}s...",
                      file=sys.stderr)
                time.sleep(wait)
                last_exc = e
                continue
            raise
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Unexpected Gemini response structure: {exc}") from exc
    raise last_exc  # type: ignore[misc]


def run_challenger(
    file_data: list[dict],
    spec_context: str,
    model: str,
    api_key: str,
) -> dict:
    """Call Gemini to adversarially review code.

    Returns:
        Parsed challenger output dict with issues and summary.
    """
    print("  Calling Gemini challenger...", file=sys.stderr)

    prompt = build_challenger_prompt(file_data, spec_context)
    text = _call_gemini(prompt, model, api_key)
    result = parse_challenger_response(text)

    result.setdefault("issues", [])
    result.setdefault("summary", "")

    print(f"  Challenger found {len(result['issues'])} issues", file=sys.stderr)
    return result


def run_counter_rebuttal(
    challenger_output: dict,
    author_output: dict,
    model: str,
    api_key: str,
    round_num: int = 1,
) -> dict:
    """Call Gemini to respond to author's rebuttals.

    Returns:
        Parsed counter-rebuttal dict with concede/maintain verdicts.
    """
    print(f"  Calling Gemini counter-rebuttal (round {round_num + 1})...",
          file=sys.stderr)

    prompt = build_counter_rebuttal_prompt(challenger_output, author_output, round_num)
    text = _call_gemini(prompt, model, api_key, system=CHALLENGER_COUNTER_SYSTEM)
    result = parse_counter_rebuttal_response(text)

    print(f"  Challenger conceded {result.get('conceded_count', 0)}, "
          f"maintained {result.get('maintained_count', 0)}", file=sys.stderr)
    return result
