# 012: Model Registry — Task-Aware Model Resolution

**Status:** draft

## Goal

Build a deterministic model registry that knows which AI model is best for every task domain — coding, vision, music, video, image generation, etc. — and routes tasks to the right model. No edge cases where "create music" goes to ChatGPT when Suno exists. No hardcoded model IDs. Rankings sourced from canonical leaderboards (arena.ai, Artificial Analysis), refreshed every 3-4 weeks, cross-referenced against what's available with our API keys.

Replaces the current adversarial model_resolver.py (which only handles 3 coding models) with a comprehensive registry across all AI domains.

## Architecture

### Domain taxonomy

Every AI task maps to a domain. The registry knows the best model per domain.

| Domain | Examples | Leaderboard Source |
|--------|----------|-------------------|
| `code` | Write code, review code, generate tests | arena.ai/text (coding sub-cat) |
| `text` | General reasoning, analysis, planning | arena.ai/text (overall) |
| `vision` | Describe image, analyze screenshot | arena.ai/vision |
| `text_to_image` | Generate image from prompt | arena.ai/text-to-image |
| `image_edit` | Modify existing image | arena.ai/image-edit |
| `text_to_video` | Generate video from prompt | arena.ai/text-to-video |
| `image_to_video` | Animate image | arena.ai/image-to-video |
| `video_edit` | Edit existing video | arena.ai/video-edit |
| `music` | Generate music, compose | Artificial Analysis music arena |
| `text_to_speech` | Voice synthesis | Artificial Analysis TTS |
| `search` | Web search, RAG | arena.ai/search |
| `document` | PDF analysis, OCR | arena.ai/document |

### Registry file: `.model-registry.json`

```json
{
  "fetched_at": "2026-03-24T...",
  "domains": {
    "code": {
      "ranked": [
        {"model": "claude-opus-4-6", "provider": "anthropic", "score": 1463, "source": "arena.ai"},
        {"model": "gemini-3.1-pro-preview", "provider": "google", "score": 1450, "source": "arena.ai"},
        {"model": "gpt-5.4", "provider": "openai", "score": 1445, "source": "arena.ai"}
      ],
      "best_available": "claude-opus-4-6"
    },
    "music": {
      "ranked": [
        {"model": "v4.5", "provider": "suno", "score": 1113, "source": "artificialanalysis.ai"},
        {"model": "eleven-music", "provider": "elevenlabs", "score": 1062, "source": "artificialanalysis.ai"}
      ],
      "best_available": null
    }
  },
  "available_keys": ["anthropic", "google", "openai"]
}
```

`best_available` = highest-ranked model where we have an API key. `null` if we have no keys for any provider in that domain (the registry still knows what's best — we just can't call it).

### Resolution flow

```python
registry.resolve("code")           # -> "claude-opus-4-6" (best we can call)
registry.resolve("music")          # -> None (no Suno key) + warning
registry.resolve("text_to_image")  # -> best available image model
registry.best("music")             # -> "suno/v4.5" (best globally, even if no key)
```

### Refresh cycle

`hth-platform models refresh` fetches all leaderboards, cross-references with provider APIs, writes `.model-registry.json`. Run every 3-4 weeks or on-demand.

## Inputs
- Arena.ai leaderboard data (HuggingFace dataset API, CSV releases)
- Artificial Analysis API (text-to-image, video, music — free key required)
- Provider model listing APIs (Anthropic, Google, OpenAI)
- `.env` API keys (determines what's "available")

## Outputs
- `lib/python/registry/` — Python module for model resolution
- `.model-registry.json` — Cached registry (gitignored)
- `hth-platform models` CLI commands (resolve, refresh, show, best)

## Key Decisions
- **Leaderboard-first**: Global ranking is truth. Provider APIs only tell us what's available.
- **Domain taxonomy is code, not config**: Adding a new domain = add to the enum + add a fetch function. Not fragile string matching.
- **No routing to wrong domain**: `resolve("music")` NEVER returns a text model. Returns None + warning if no music model available.
- **Reuse golf project patterns**: T1-T5 escalation for scraping, circuit breaker, rate limiter, verification gates.

## Edge Cases
- Leaderboard source down → use cached registry (warn if stale)
- New domain appears on arena.ai → add to taxonomy manually (deliberate, not auto-discovered)
- Model available on leaderboard but we don't have a key → tracked as "ranked but unavailable"
- Provider renames model → cross-reference by organization + fuzzy match on name

## Done When
- [x] `lib/python/registry/` module exists with domain taxonomy and resolution
- [ ] `hth-platform models refresh` fetches from arena.ai + Artificial Analysis — method exists in ModelRegistry.refresh(), CLI command not yet wired
- [ ] `hth-platform models show` prints registry with per-domain best — no CLI command file yet
- [ ] `hth-platform models best code` returns best available code model — no CLI command file yet
- [x] `.model-registry.json` written with all domains populated
- [x] `registry.resolve("music")` returns Suno (if key exists) or None (not GPT)
- [ ] Adversarial pipeline uses registry instead of model_resolver.py — still using model_resolver.py
- [x] Registry refresh tested with live API calls to all sources — code exists, needs dedicated test suite
