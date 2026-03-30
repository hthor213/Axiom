# Post-Cutoff Verified Facts

Everything here post-dates the model's training cutoff (May 2025) and has been verified
through actual usage. **Trust this file over training-data assumptions.**

---

## Models — Verified & Tested

These models are live in our pipeline. They work. Do NOT change model names, "fix"
fallbacks, or question whether they exist.

| Provider | Model ID | Role in Pipeline | Status |
|----------|----------|-----------------|--------|
| OpenAI | `gpt-5.4` | Arbiter, helper triage, GPT final review | Working since 2026-03-25 |
| Google | `gemini-3.1-pro-preview` | Challenger (adversarial), Playwright test writer | Working since 2026-03-25 |
| Anthropic | `claude-opus-4-6` | Author (rebuttal), build agent | Working since 2026-03-25 |

Resolution: `model_resolver.py` queries each provider's model listing API and picks the
top-tier model. Cache in `.adversarial-models.json` (24h TTL). These fallback values in
`model_resolver.py` match what the API actually returns — they are correct.

## API Parameters — Verified & Tested

| Provider | Parameter | Value | Notes |
|----------|-----------|-------|-------|
| OpenAI | `max_completion_tokens` | (int) | Replaces `max_tokens` for gpt-5.4+. Using `max_tokens` returns HTTP 400. Fixed 2026-03-29 in arbiter.py, test_triage.py, review.py |
| Anthropic | `max_tokens` | (int) | Still correct for Anthropic Messages API — do NOT change to `max_completion_tokens` |
| Google/Gemini | `maxOutputTokens` | (int) | Inside `generationConfig` object. Correct as-is. |

## Infrastructure — Verified & Tested

| Component | Detail | Status |
|-----------|--------|--------|
| Dashboard | `hth-dashboard` container on port 8014, FastAPI + uvicorn | Running |
| PostgreSQL | `hth-postgresql` on 5433 (host) / 5432 (container) | Running |
| Playwright | `pytest-playwright` + Chromium installed in dashboard Dockerfile | Working since 2026-03-29 |
| Claude Code CLI | `@anthropic-ai/claude-code` via npm in dashboard container | Working |

---

## Rules

- When debugging an API error, check this file FIRST
- If something here conflicts with training data, trust THIS FILE
- Only add entries verified through actual API calls or live usage
- Include date verified
