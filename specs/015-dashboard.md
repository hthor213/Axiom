# 015: Dashboard — Human Control Plane

**Status:** draft

## Goal

A web dashboard on spliffdonk.com that serves as the human interface for the autonomous runtime (spec:014). The developer checks in, reviews what agents built, selects next work from specs, clicks "Run," and walks away for hours or days. Telegram pings when there's something to review. The dashboard replaces most interactive Claude Code sessions for routine execution work.

This is the "Mode 1 for non-judgment work" — you don't need a 1M context window to tick checkboxes and review diffs.

check out kiro.dev 

## Architecture

```
┌─────────────────────────────────────────┐
│  spliffdonk.com/dashboard (Frontend)    │
│  Vanilla JS SPA served by FastAPI       │
│  Behind Apache reverse proxy            │
│                                         │
│  Views: Live | Results | Queue | History│
└──────────────┬──────────────────────────┘
               │ HTTPS (Apache on MacStudio)
┌──────────────▼──────────────────────────┐
│  MacStudio API (FastAPI :8014)          │
│  Apache: /dashboard → :8014            │
│  (same pattern as /golf → :8002)       │
│                                         │
│  Endpoints:                             │
│  GET  /agents       — running sessions  │
│  GET  /results      — completed tasks   │
│  GET  /specs        — spec list + status│
│  POST /queue        — enqueue tasks     │
│  POST /run          — trigger execution │
│  GET  /history      — past runs         │
│  WS   /live         — streaming progress│
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│  PostgreSQL (:5433) — state             │
│  n8n (:5678) — webhook trigger          │
│  Claude Agent SDK — worker sessions     │
│  Telegram — "batch complete" pings      │
└─────────────────────────────────────────┘
```

## Dashboard Views

### Live View
- Pipeline flow diagram matching the architecture in `docs/workflow.md`: nodes for Server, Claude, Gemini (Playwright), Gemini (Adversary), GPT (Mentor/Arbiter), with directional arrows showing the flow
- Nodes light up (blink/pulse) when active — e.g. Claude blinks while building, Gemini blinks while writing Playwright tests or reviewing
- Arrows animate when data flows between nodes — e.g. "Server → Claude" lights up when prompt is sent
- Red line between nodes on communication failure; X overlay on a node if it rejects/fails
- Current task context shown (spec number, done-when item, elapsed time)
- Kill button per agent (triggers max_turns override)
- No internal tool-call detail — the view shows which role is active, not what's happening inside each one

### Results View
- Completed tasks with adversarial review verdicts (PASS/FAIL)
- Change summary from adversarial report shown above diff
- Git diffs per task (collapsible, collapsed by default, shows insertion/deletion counts)
- File list extracted from diff summary
- Test results summary
- "Approve & Merge" / "Reject & Re-queue" buttons with clear tooltips

### Queue View
- Specs listed with checkbox, title, one-line goal description, and progress badge (X/Y done)
- Collapsible "View details" expands to show all Done When items
- Result badges show latest verdict + run count + "review pending" (amber) — clickable to Results
- "Run Selected" button with optional global instructions textarea
- User instructions flow through to Claude prompt as "Additional Instructions from Human"

### History View
- Past runs: when, what was built, pass/fail rates
- Time-to-complete trends
- Cost per run

## The 2-Day Cycle

```
Day 0: Developer opens Queue view
       → Checks 6 spec items
       → Clicks "Run"
       → Closes laptop

Day 0-2: MacStudio works through queue
         → Claude Agent SDK builds each task in a worktree
         → Tests run, adversarial review runs
         → Results written to PostgreSQL
         → Telegram: "4/6 done, 2 in review"

Day 2: Telegram: "Batch complete"
       → Developer opens Results view
       → Reviews diffs, reads adversarial notes
       → Approves 3, rejects 1, 2 need judgment
       → Opens Claude Code on laptop for the 2 judgment tasks
       → Queues 4 more items
       → Clicks "Run"
       → Closes laptop
```

## Auth

Google Sign-In (same pattern as golf project). Frontend loads GSI, user clicks "Sign in with Google", backend verifies token and issues a 7-day JWT. Only `your-email@example.com` is allowed (`ALLOWED_EMAIL` env var). Reuses the same `GOOGLE_CLIENT_ID` as the golf project. If this ever needs multi-user, that's a different spec.

## Inputs
- Spec files (read from git on MacStudio)
- Agent session state (from spec:014 runtime)
- PostgreSQL task/result tables
- Git branches and diffs (from worktrees)

## Outputs
- Web UI on spliffdonk.com
- FastAPI backend on MacStudio
- PostgreSQL schema for tasks, results, history
- WebSocket stream for live agent monitoring

## Boundary

This spec owns the **human interface**: frontend views, API endpoints, auth, WebSocket, user interactions.

Runtime behavior (scheduling, git operations, Telegram notifications, adversarial assembly) is defined in spec:014. This spec owns the UI and API endpoints that trigger runtime actions.

## Prerequisites
- spec:014 (Autonomous Runtime) — the dashboard is the UI for spec:014's runtime
- MacStudio infrastructure (PostgreSQL, n8n) — already deployed
- spliffdonk.com Apache config — `/dashboard` proxy to `:8014`

## Done When

### Core views and API
- [x] FastAPI backend serves /agents, /results, /specs, /queue, /run, /history endpoints
- [x] Vanilla JS frontend deployed on spliffdonk.com/dashboard with Live, Results, Queue, History views
- [x] Google Sign-In auth protects all endpoints (your-email@example.com only)
- [x] Live view streams agent progress via WebSocket
- [x] Drafts view: dashboard shows pending draft reviews with questions, answer form, version history
- [x] `POST /drafts/{id}/answer`: submit answers triggers re-queue with full context

### Queue view
- [x] Queue view shows specs with checkboxes, "Run" button triggers processing
- [x] Queue shows spec goal description + progress badge, not truncated Done When list
- [x] Run Selected accepts optional user instructions textarea — passed through to agent prompt
- [x] Queue deduplication: same spec+item cannot be queued twice via `has_active_task()` check
- [x] Per-spec result badges: Queue view shows pass/fail indicators for specs with completed results
- [x] Result badges show latest verdict + history count + "review pending" (amber) — clickable to Results view

### Results view
- [x] Results view shows diffs, adversarial verdicts, and approve/reject buttons
- [x] Results view shows spec number + title, not internal task IDs
- [x] Results view shows change summary from adversarial report with collapsible diff (collapsed by default)
- [x] Approve/reject buttons clarified: "Approve & Merge" / "Reject & Re-queue" with tooltips; drafts use "Approve as Final"
- [ ] Results view shows full spec content for draft reviews — collapsible "View spec" section with the spec file from the worktree branch

### Runtime integration
- [x] Parallel run support: `/run` endpoint supports concurrent runs (no 409 block), `_active_runs` dict replaces single `_run_task`
- [x] Live view: agent sessions populate correctly — `session_started` event + 10s polling ensures agents list stays current
- [x] Telegram sends "batch complete" with spec names, repo name, and link to Results view
- [ ] Full cycle works: select specs → run → wait → review results → select more
- [ ] Dashboard "Run" triggers queue processing end-to-end (moved from spec:014)
