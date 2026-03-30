# AI Model Registry — Data Sources

## Arena.ai Leaderboard Categories (11 domains)

| Domain | Arena Tab | Programmatic Source | Auth |
|--------|-----------|-------------------|------|
| Text (overall + 27 sub-cats) | arena.ai/leaderboard/text | HuggingFace dataset, CSV, JSON | None |
| Code / WebDev | arena.ai/leaderboard/code | Raw battle data only | None |
| Vision | arena.ai/leaderboard/vision | HuggingFace dataset, CSV | None |
| Document (PDF) | arena.ai/leaderboard/document | No known endpoint (new Mar 2026) | — |
| Text-to-Image | arena.ai/leaderboard/text-to-image | Artificial Analysis API | Free key |
| Image Edit | arena.ai/leaderboard/image-edit | Artificial Analysis API | Free key |
| Search | arena.ai/leaderboard/search | Raw battle data only | None |
| Text-to-Video | arena.ai/leaderboard/text-to-video | Artificial Analysis API | Free key |
| Image-to-Video | arena.ai/leaderboard/image-to-video | Artificial Analysis API | Free key |
| Video Edit | arena.ai/leaderboard/video-edit | No known endpoint | — |
| Music | artificialanalysis.ai/music/arena | Artificial Analysis API (undocumented) | Free key |

## Data Sources (ranked by reliability)

### Source A: HuggingFace Dataset (text overall, daily, no auth)
```
GET https://datasets-server.huggingface.co/rows?dataset=mathewhe/chatbot-arena-elo&config=default&split=train&offset=0&length=300
```
Fields: Model, Arena Score, Rank, Organization, Votes

### Source B: fboulnois CSV (text + vision + image, periodic releases)
```
GET https://github.com/fboulnois/llm-leaderboard-csv/releases/download/YYYY.MM.DD/lmarena_text.csv
GET .../lmarena_vision.csv
GET .../lmarena_image.csv
```

### Source C: Artificial Analysis API (media domains, free key required)
```
GET https://artificialanalysis.ai/api/v2/data/llms/models
GET .../media/text-to-image?include_categories=true
GET .../media/image-editing
GET .../media/text-to-video?include_categories=true
GET .../media/image-to-video?include_categories=true
GET .../media/text-to-speech
Header: x-api-key: YOUR_KEY
```
Rate limit: 1,000 req/day (free tier). Attribution required.

### Source D: Provider model listing APIs (what's available to us)
```
Anthropic: GET https://api.anthropic.com/v1/models
Google:    GET https://generativelanguage.googleapis.com/v1beta/models?key=KEY
OpenAI:    GET https://api.openai.com/v1/models
```

## Resolution Strategy

1. Fetch leaderboard rankings (Source A/B/C) → "what's best globally"
2. Fetch provider model listings (Source D) → "what's available to us"
3. Cross-reference: pick highest-ranked model that we can actually call
4. Store in registry with domain, rank, score, provider, model_id, fetched_at
5. Re-fetch every 3-4 weeks via cron or manual `hth-platform models refresh`

## Golf Trip Planner Patterns to Reuse

From `/path/to/your-project`:
- **T1-T5 scraping escalation** (requests → playwright → humanization) for leaderboard sites without APIs
- **Circuit breaker** per-endpoint failure isolation
- **Rate limiter** per-source daily tracking
- **Intent logging** audit trail for which leaderboard version each score came from
- **Blob storage** raw API responses + parsed metrics
- **Verification gates** ensure all required fields present before marking record complete
