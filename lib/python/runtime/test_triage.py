"""Trajectory-aware test failure triage.

Tracks improvement across retries and adapts response based on momentum.
Uses GPT (OpenAI) as an independent helper model to diagnose minor failures
before adversarial review — separate from the builder (Claude) and
challenger (Gemini) to avoid shared blind spots.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = 120
_MAX_OUTPUT_CHARS = 4000

HELPER_SYSTEM = (
    "You are a test failure analyst. Given failing pytest output and context, "
    "determine the root cause. Respond with JSON only:\n"
    '{"recommendation": "fix_code" | "fix_tests" | "skip_tests", '
    '"reasoning": "brief explanation", '
    '"guidance": "specific instructions for the developer"}'
)


def evaluate_trajectory(history: list[int], total_tests: int) -> str:
    """Classify improvement trajectory from failure count history.

    Returns: 'eureka' | 'improving' | 'stagnating' | 'catastrophic' | 'almost_done'
    """
    if not history:
        return "improving"

    current = history[-1]
    failure_rate = current / max(total_tests, 1)

    if failure_rate <= 0.05:
        return "almost_done"

    if len(history) < 2:
        return "catastrophic" if failure_rate > 0.5 else "improving"

    previous = history[-2]
    improvement = previous - current
    improvement_pct = improvement / max(previous, 1)

    if improvement_pct > 0.6:
        return "eureka"
    if improvement <= 0:
        return "stagnating"
    if improvement_pct < 0.10:
        return "stagnating"

    return "improving"


def call_helper_model(test_output: str, repo_root: str) -> dict:
    """Ask GPT to diagnose test failures and recommend a fix strategy.

    Returns dict with 'recommendation', 'reasoning', 'guidance' keys.
    Falls back to generic guidance on API failure.
    """
    lib_path = __import__("os").path.join(repo_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from adversarial.credentials import load_credentials
    from adversarial.model_resolver import resolve_or_load

    creds = load_credentials(repo_root)
    api_key = creds.get("openai")
    if not api_key:
        return _fallback("No OpenAI API key available")

    models = resolve_or_load(creds, repo_root)
    model = models.openai

    truncated = test_output[-_MAX_OUTPUT_CHARS:] if len(test_output) > _MAX_OUTPUT_CHARS else test_output
    prompt = f"Failing pytest output:\n```\n{truncated}\n```\n\nDiagnose the failures and recommend a fix strategy."

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": HELPER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 2048,
    }).encode()

    for attempt in range(3):
        req = urllib.request.Request(
            _OPENAI_URL, data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            text = data["choices"][0]["message"]["content"]
            return _parse_helper_response(text)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 529) and attempt < 2:
                time.sleep((attempt + 1) * 30)
                continue
            print(f"  Helper model HTTP {e.code}", file=sys.stderr)
            return _fallback(f"HTTP {e.code}")
        except Exception as e:
            print(f"  Helper model error: {e}", file=sys.stderr)
            return _fallback(str(e))

    return _fallback("Max retries exceeded")


def _parse_helper_response(text: str) -> dict:
    """Extract JSON from helper model response."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"recommendation": "fix_code", "reasoning": text[:500],
                "guidance": "Review the failing tests and fix the underlying code issues."}


def _fallback(reason: str) -> dict:
    return {"recommendation": "fix_code", "reasoning": f"Helper unavailable: {reason}",
            "guidance": "Review the failing test output and fix the code to make tests pass."}


def triage_test_failures(
    test_passed: int,
    test_failed: int,
    test_output: str,
    failure_history: list[int],
    config,
    emit_fn: Callable,
) -> tuple[str, str, bool]:
    """Evaluate test failures and decide next action.

    Args:
        failure_history: mutable list — this function appends to it.

    Returns (action, guidance, reset_budget):
        action: 'retry' | 'waiting_for_human' | 'failed'
        guidance: feedback string for run_fix_session()
        reset_budget: True if trajectory is 'eureka' (caller resets attempt counter)
    """
    total = test_passed + test_failed
    failure_history.append(test_failed)

    trajectory = evaluate_trajectory(failure_history, total)
    emit_fn("test_triage", {
        "trajectory": trajectory,
        "test_passed": test_passed,
        "test_failed": test_failed,
        "failure_history": list(failure_history),
    })
    print(f"  Test triage: {trajectory} ({test_failed}/{total} failing, "
          f"history={failure_history})", file=sys.stderr)

    if trajectory == "catastrophic":
        catastrophic_count = sum(
            1 for i, f in enumerate(failure_history)
            if f / max(total, 1) > 0.5
        )
        if catastrophic_count >= 2:
            return ("waiting_for_human",
                    "Over 50% of tests have failed twice. This might indicate "
                    "an ambiguous spec. What do you want to ask the user?",
                    False)
        return ("retry",
                f"Over 50% of tests are failing ({test_failed}/{total}). "
                "Rethink your approach — the current implementation has fundamental issues.",
                False)

    if trajectory == "stagnating":
        stagnating_count = _count_stagnating(failure_history, total)
        if stagnating_count >= 2:
            return ("waiting_for_human",
                    f"Test failures have stagnated across {stagnating_count} attempts "
                    f"(history: {failure_history}). This might indicate an ambiguous "
                    "spec or a structural issue. What do you want to ask the user?",
                    False)
        helper = call_helper_model(test_output, config.repo_root)
        return ("retry", _build_guidance(helper, test_output, test_failed, total), False)

    if trajectory in ("eureka", "almost_done"):
        helper = call_helper_model(test_output, config.repo_root)
        return ("retry", _build_guidance(helper, test_output, test_failed, total),
                trajectory == "eureka")

    # "improving" — simple retry with test output, no helper needed
    return ("retry",
            f"Tests are improving but {test_failed}/{total} still failing. "
            f"Fix the remaining failures:\n\n{test_output[-2000:]}",
            False)


def _count_stagnating(history: list[int], total: int) -> int:
    """Count consecutive stagnating steps at the end of history."""
    count = 0
    for i in range(len(history) - 1, 0, -1):
        prev = history[i - 1]
        improvement = prev - history[i]
        improvement_pct = improvement / max(prev, 1)
        if improvement <= 0 or improvement_pct < 0.10:
            count += 1
        else:
            break
    return count


def _build_guidance(helper: dict, test_output: str,
                    failed: int, total: int) -> str:
    rec = helper.get("recommendation", "fix_code")
    reasoning = helper.get("reasoning", "")
    guidance = helper.get("guidance", "")

    if rec == "fix_tests":
        prefix = (f"{failed}/{total} tests failing. The helper model believes "
                  "the tests themselves are incorrect.")
    elif rec == "skip_tests":
        prefix = (f"{failed}/{total} tests failing. The helper model believes "
                  "these tests are not relevant.")
    else:
        prefix = (f"{failed}/{total} tests failing. The helper model believes "
                  "the code has a bug.")

    return (f"{prefix}\n\nAnalysis: {reasoning}\n\nGuidance: {guidance}\n\n"
            f"Failing test output:\n{test_output[-2000:]}")
