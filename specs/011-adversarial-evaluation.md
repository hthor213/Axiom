# 011: Adversarial Multi-Model Evaluation

**Status:** draft

## Goal

Build a deterministic Python-driven adversarial evaluation pipeline where multiple frontier models challenge each other's work. Inspired by Arnar Hrafnkelsson's insight: "An Adversary agent generates complex scenarios designed to break a target model's logic... This creates a high-velocity feedback loop where the models are effectively hardening one another."

Critical constraint: **model selection must be dynamic** — a Python script queries each provider's API to discover the current top-tier model. No hardcoded model IDs. When Anthropic ships Claude 5 or OpenAI ships GPT-6, the system picks them up automatically.

## Architecture

### Three roles, three providers

| Role | Purpose | Provider |
|------|---------|----------|
| **Author** | Wrote the code being reviewed. Defends design decisions. | Anthropic (top model) |
| **Challenger** | Adversarial reviewer. Generates unit tests, functional tests, finds flaws, writes critique. | Google (top model) |
| **Arbiter** | Tie-breaker when Author and Challenger disagree. Final ruling. | OpenAI (top model) |

### Deterministic flow (Python, not LLM memory)

```
1. model_resolver.py   → Query APIs, resolve current top model per provider
2. challenger.py       → Hostile review: find flaws, no praise allowed
3. author_rebuttal.py  → Author accepts or rebuts each issue
4. challenger.py       → Counter-rebuttal: concede valid rebuttals or maintain
   ↕ Steps 3-4 repeat up to 3 rounds (debate narrows each round)
5. arbiter.py          → Only issues still disputed after 3 rounds reach GPT
6. report.py           → Deterministic summary with debate history and resolutions
```

Each step is a Python script with structured JSON I/O. The pipeline runner (`adversarial.py`) orchestrates sequentially — no LLM decides what runs next. The challenger prompt is deliberately hostile (no compliments, must find issues) to prevent sycophantic pass-through reviews.

### Model resolver (`lib/python/adversarial/model_resolver.py`)

Queries each provider API to find the latest top-tier model:
- **Anthropic**: `GET /v1/models` → filter for highest-capability Claude model
- **Google**: `genai.list_models()` → filter for latest Gemini Pro/Ultra
- **OpenAI**: `GET /v1/models` → filter for latest GPT flagship

Returns a `ResolvedModels` dataclass with the three model IDs + timestamps. Cached for the session (re-resolve on `hth-platform adversarial resolve`).

### Credential loading

Follows existing vault pattern — reads from env vars first, falls back to vault:
- `ANTHROPIC_API_KEY` or `vault.anthropic[orchestrator-primary].key`
- `OPENAI_API_KEY` or `vault.openai[orchestrator-primary].key`
- `GOOGLE_API_KEY` or `vault.google.api_keys.general.key`

## Inputs
- Changed files (from git diff or explicit file list)
- Active spec's Done When criteria (context for what "correct" means)
- Vault credentials for three providers

## Outputs
- Generated test files (unit + functional) written to project
- Adversarial report (JSON + human-readable markdown)
- Pass/fail verdict per file reviewed
- Disagreement log when Author and Arbiter are invoked

## Key Decisions
- **Dynamic model resolution over hardcoded IDs** — the script discovers models at runtime
- **Three distinct providers** — prevents echo-chamber bias from same-family models
- **Deterministic orchestration** — Python script controls flow, not LLM chain-of-thought
- **Structured JSON between steps** — each step reads JSON in, writes JSON out
- **Challenger generates real tests** — not just prose critique, actual runnable test code

## Edge Cases
- Provider API down → skip that role, log warning, continue with available models
- Model resolver finds no suitable model → fall back to known-good model ID from config
- Author agrees with all Challenger points → skip debate + Arbiter, fast path
- Challenger concedes all rebuttals in round 1 → skip remaining rounds + Arbiter
- Issues still disputed after 3 rounds → escalate to Arbiter
- Generated tests don't compile → flag in report, don't count as passing

## Done When
- [x] `lib/python/adversarial/model_resolver.py` exists and queries all three provider APIs
- [x] `python -m adversarial.model_resolver` prints current top model per provider
- [x] `lib/python/adversarial/adversarial.py` runs the full pipeline on a file
- [x] Pipeline produces JSON report with: models used, tests generated, issues found, verdicts
- [x] Generated tests are written to project and runnable
- [x] `hth-platform adversarial run [files]` CLI command exists
- [x] `hth-platform adversarial resolve` shows current resolved models
- [x] Credentials loaded via env vars with vault fallback (no hardcoded keys)
- [x] Vision spec (-> spec:000) updated with adversarial evaluation as Tier 4
