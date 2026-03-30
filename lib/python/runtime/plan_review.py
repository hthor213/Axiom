"""GPT mentor review of build plans.

Calls GPT to review a Claude-generated build plan before execution.
The mentor is additive ("you should also consider X"), not adversarial.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


GPT_PLAN_MENTOR_SYSTEM = """\
You are reviewing a build plan for a software development task.
Your role is mentor — help the builder see what they're missing.

Be constructive and additive:
- Check if the plan covers all acceptance criteria
- Flag missing steps or incorrect assumptions
- Suggest concrete additions ("you should also handle X")
- Point out if the plan misses existing code it should reuse
- NOT hostile — you're improving the plan, not attacking it
- NOT destructive — don't say "this approach is wrong", say "also consider Y"

Keep your feedback structured and brief. Use numbered points.
If the plan is solid, say so in one line and move on."""


def review_plan(plan_text: str, spec_content: str,
                done_when_items: list[str],
                repo_root: str) -> str:
    """Send the plan to GPT mentor for review. Returns feedback text.

    Falls back gracefully if API key is missing or call fails.
    """
    criteria = "\n".join(f"- {item}" for item in done_when_items)
    prompt = (
        f"## Build Plan\n{plan_text}\n\n"
        f"## Spec\n{spec_content[:3000]}\n\n"
        f"## Acceptance Criteria\n{criteria}\n\n"
        f"Does this plan cover all criteria? What's missing?"
    )

    try:
        return _call_gpt(prompt, GPT_PLAN_MENTOR_SYSTEM, repo_root)
    except Exception as e:
        return f"Mentor review unavailable: {e}"


def _call_gpt(prompt: str, system: str, repo_root: str) -> str:
    """Call GPT via OpenAI API. Resolves model from registry."""
    lib_path = os.path.join(repo_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from adversarial.credentials import load_credentials
    from adversarial.model_resolver import resolve_or_load

    creds = load_credentials(repo_root)
    api_key = creds.get("openai")
    if not api_key:
        raise RuntimeError("No OpenAI API key")

    models = resolve_or_load(creds, repo_root)

    body = json.dumps({
        "model": models.openai,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]
