# Autonomous Runtime — How It Works

A human-readable walkthrough of the system, from clicking "Run" to reviewing results.

## The Actors

| Who | What | Where |
|-----|------|-------|
| **You** | Pick tasks, review results | spliffdonk.com/dashboard (browser) |
| **Dashboard API** | Manages queue, serves UI | FastAPI on MacStudio :8014 |
| **Runtime Server** | Runs the build loop | Python on MacStudio (triggered by dashboard) |
| **Claude Code CLI** | Writes code, edits files | Subprocess per task, in its own git worktree |
| **Adversarial Pipeline** | Reviews code (3 models) | Stateless API calls: Gemini → Claude → GPT |
| **PostgreSQL** | Stores tasks, runs, results | MacStudio :5433 |
| **Telegram** | Pings you when done | Bot → your phone |

## The Flow

```
You (browser)              Dashboard API           Runtime Server          Claude CLI            Adversarial
    │                           │                       │                      │                    │
    ├── Select specs ──────────►│                       │                      │                    │
    ├── Click "Run" ──────────►│                       │                      │                    │
    │                           ├── Write tasks to DB   │                      │                    │
    │                           ├── Start runtime ─────►│                      │                    │
    │                           │                       ├── Read next task     │                    │
    │                           │                       ├── Create worktree    │                    │
    │                           │                       ├── Run claude -p ────►│                    │
    │                           │   (WebSocket events)  │   "Build X per      │                    │
    │   ◄── Live view updates ──┤◄── progress ─────────┤    spec Y"          │                    │
    │                           │                       │                      ├── Edit files       │
    │                           │                       │                      ├── Run bash         │
    │                           │                       │                      ├── Read/Write       │
    │                           │                       │◄── done ────────────┤                    │
    │                           │                       ├── Run pytest         │                    │
    │                           │                       ├── Run harness check  │                    │
    │                           │                       ├── Send diff ────────────────────────────►│
    │                           │                       │                      │   Gemini reviews   │
    │                           │                       │                      │   Claude defends   │
    │                           │                       │                      │   GPT arbitrates   │
    │                           │                       │◄───────────────────────── verdict ───────┤
    │                           │                       │                      │                    │
    │                           │                       ├─ PASS? ──► commit    │                    │
    │                           │                       │                      │                    │
    │                           │                       ├─ FAIL? ──► assemble  │                    │
    │                           │                       │   consolidated       │                    │
    │                           │                       │   feedback from      │                    │
    │                           │                       │   all 3 models       │                    │
    │                           │                       │                      │                    │
    │                           │                       ├── Run claude -p ────►│                    │
    │                           │                       │   "Fix these issues" │                    │
    │                           │                       │◄── done ────────────┤                    │
    │                           │                       ├── Re-run pytest      │                    │
    │                           │                       ├── Re-run harness     │                    │
    │                           │                       │   check              │                    │
    │                           │                       └── Loop back to ──────────────────────────►│
    │                           │                       │   "Send diff"        │   (re-review)      │
    │                           │                       │   (max 3 attempts)   │                    │
    │                           │                       │                      │                    │
    │                           │                       ├── Commit to branch   │                    │
    │                           │                       ├── Cleanup worktree   │                    │
    │                           │                       ├── Next task...       │                    │
    │                           │                       │   (repeat)           │                    │
    │                           │                       ├── Queue empty        │                    │
    │   ◄── Telegram ping ─────┤◄── batch complete ───┤                      │                    │
    │                           │                       │                      │                    │
    ├── Open Results view ─────►│                       │                      │                    │
    │   ◄── diffs, verdicts ───┤                       │                      │                    │
    ├── Approve / Reject ──────►│                       │                      │                    │
    │                           ├── Update DB           │                      │                    │
```

## Step by Step

### 1. You select tasks (Dashboard → Queue view)

- Open `spliffdonk.com/dashboard`
- Log in with Google (your-email@example.com)
- Queue view shows all specs with their Done When items
- Check the specs you want built
- Click **Run Selected**

What happens: unchecked Done When items from selected specs are written to the `tasks` table in PostgreSQL, each with status `queued`.

### 2. Runtime server starts processing

The dashboard's `/run` endpoint starts the `RuntimeServer.process_queue()` loop in a background thread.

For each task:

**a) Create git worktree**
```
/tmp/hth-worktrees/task-42/ → branch auto/spec-014-task-42
```
Isolated copy of the repo. Claude works here without touching main.

**b) Run Claude Code CLI (with full capabilities)**
```bash
claude -p "Build spec 014: [full spec content + all Done When items]. \
  Use maestro to plan milestones. Delegate to sub-agents as needed. \
  Run tests after each milestone." \
  --output-format stream-json \
  --dangerously-skip-permissions \
  --max-turns 30 \
  --model opus
```

**Key design decision**: The server gives Claude Code the **full spec**, not atomic sub-tasks. Claude Code uses its own orchestration (maestro for planning, analyst for research, sub-agents for parallel work). We don't try to replicate what Claude Code already does well — we let it use its full capabilities.

What Claude Code does inside the session:
- Uses maestro to break the spec into milestones
- Delegates to sub-agents (analyst for codebase research, etc.)
- Edits files, runs bash, reads code — full tool use
- Runs tests after each milestone
- The `--max-turns 30` is the server's kill switch

**c) Server verifies (deterministic)**
```bash
cd /tmp/hth-worktrees/task-42/ && python -m pytest tests/ -q
```
Plus `run_harness_check(spec_path)` to verify Done When items.

**d) Adversarial review (3-model feedback assembly)**

The server sends the diff to three models — no tool use, just judgment:
1. **Gemini** (Challenger): Reviews the diff, finds flaws
2. **Claude** (Author): Defends or accepts critique
3. **GPT** (Arbiter): Breaks ties

If verdict is FAIL, the server **assembles a refined course of action** from all three models' feedback and sends it back to Claude Code:
```bash
claude -p "Adversarial review found these issues: [consolidated feedback]. \
  Fix them in the existing worktree." \
  --output-format stream-json \
  --dangerously-skip-permissions \
  --max-turns 15
```
This loop repeats until PASS or termination.

**e) Save results**
- Diff, test results, adversarial verdict → `results` table
- Commit code to the task branch
- Cleanup the worktree

### 3. Termination conditions

The loop stops when ANY of these hit:
- **Queue empty** — all tasks processed
- **3 consecutive failures** — something is systematically wrong, needs human
- **Total runtime > 6 hours** — cost/safety guard
- **Manual stop** — you click Kill in the Live view

### 4. You get notified

Telegram message: "Batch complete — 4 tasks done, 1 failed. Review at spliffdonk.com/dashboard"

### 5. You review results (Dashboard → Results view)

Each result shows:
- Git diff (what changed)
- Test results (passed/failed counts)
- Adversarial verdict (PASS/FAIL + notes from all 3 models)
- **Approve** or **Reject** buttons

Approved results can be merged to main. Rejected results go back to the queue.

## Harness Check — What It Actually Does

`hth-platform harness check` is the deterministic verification step. It reads the "Done When" checklist from a spec's markdown and tries to verify each item automatically — no LLM involved.

### The flow

```
hth-platform harness check [--spec 014]
    │
    ├── Find specs/ directory
    ├── If --spec given: check that spec only
    │   Otherwise: check all specs with Status: active
    │
    For each spec:
    │
    ├── Parse the ## Done When section
    │   Extract checklist items: - [x] or - [ ] lines
    │
    For each Done When item:
    │
    ├── Classify the item into one of 5 check types:
    │
    │   file_exists    "`path/to/file` exists"
    │                  → os.path.exists(path)
    │
    │   grep           "`file` mentions X" / "`file` contains Y"
    │                  → read file, case-insensitive substring search
    │
    │   spec_status    "spec:NNN status is done"
    │                  → parse the referenced spec's Status field
    │
    │   command        "`pytest tests/harness/` runs successfully"
    │                  → subprocess.run() with 30s timeout, exit code 0 = pass
    │                  → only safe prefixes allowed (python, pytest, git status, etc.)
    │                  → curl, rm, sudo → blocked, reclassified as judgment
    │
    │   judgment       anything else (default fallback)
    │                  → not automatable, flagged for human/LLM review
    │
    ├── Execute the check
    ├── Record: PASS (True), FAIL (False), or JUDGMENT (None)
    │
    Summary:
    ├── [PASS]     file_exists, grep, command checks that succeeded
    ├── [FAIL]     checks that failed (with error detail)
    ├── [JUDGMENT] items that need human review (ignored for exit code)
    │
    Exit code 0 if all automatable checks passed
    Exit code 1 if any automatable check failed
```

### Why this matters in the runtime loop

The runtime server runs harness check twice per task:

1. **After Claude Code finishes** — did it actually satisfy the spec's Done When items?
2. **After adversarial retry** — did the fixes hold up?

If harness check fails, the task fails regardless of what the adversarial review says. The spec is the source of truth, and the check is mechanical — no model can talk its way past `os.path.exists()`.

### Design principles

- **Deterministic only**: judgment items are flagged, never fail the check
- **Conservative**: ambiguous items default to judgment rather than false positives
- **Safe execution**: dangerous commands (curl, rm, sudo) are blocked at classification time
- **Cross-spec references**: `spec:NNN` syntax resolves to actual file paths
- **Case-insensitive**: grep checks use case-insensitive matching to reduce brittleness

## PostgreSQL Size Estimate (1 Year)

The database stores tasks, runs, agent sessions, results, and draft reviews across 5 tables. Here's the expected growth assuming 1 run/day with ~10 tasks per run.

### Per-task data volume

| Table | Rows/task | Avg row size | Notes |
|-------|-----------|-------------|-------|
| tasks | 1 | 300 B | spec number, title, done_when_item, user_instructions |
| agent_sessions | 1 | 200 B | metadata + last_output (truncated to 500 chars) |
| results | 1 | **30 KB** | diff_summary (1-50 KB) + adversarial_report JSONB (2-10 KB) |
| draft_reviews | 0.3 | 8 KB | original_spec + refined_spec + questions/answers (optional) |

Results dominate — the git diff and adversarial report JSONB are the big fields.

### 1-year projection (365 runs × 10 tasks)

| Table | Rows | Size |
|-------|------|------|
| tasks | 3,650 | 1 MB |
| runs | 365 | 70 KB |
| agent_sessions | 3,650 | 0.5 MB |
| **results** | **3,650** | **~110 MB** |
| draft_reviews | ~1,000 | 11 MB |
| Indexes | — | ~5 MB |
| **Total** | | **~130 MB** |

If you scale to 2-5 runs/day (parallel runs), multiply accordingly: 260-650 MB/year.

### Bottom line

At current usage (1 run/day), the database stays well under 200 MB for a full year. PostgreSQL won't break a sweat — no partitioning, archival, or tuning needed. If parallel runs ramp up significantly, consider partitioning the `results` table by year after it crosses 1 GB.

## Configuration

| Setting | Default | Where |
|---------|---------|-------|
| Max turns per task | 30 | Dashboard Run button / RuntimeConfig |
| Time limit per task | 60 min | RuntimeConfig |
| Max consecutive failures | 3 | RuntimeConfig |
| Max total runtime | 6 hours | RuntimeConfig |
| Base branch | main | RuntimeConfig |
| Worktree directory | /tmp/hth-worktrees | RuntimeConfig |

## Environment Variables (MacStudio .env)

| Var | Purpose |
|-----|---------|
| `GOOGLE_CLIENT_ID` | Google Sign-In (reused from golf project) |
| `JWT_SECRET_KEY` | Dashboard auth tokens |
| `DATABASE_URL` | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Claude Code CLI + adversarial review |
| `GOOGLE_API_KEY` | Gemini adversarial review |
| `OPENAI_API_KEY` | GPT adversarial review |
| `TELEGRAM_BOT_TOKEN` | Batch complete notifications |
| `TELEGRAM_CHAT_ID` | Your Telegram chat |

## Key Files

| File | Purpose |
|------|---------|
| `lib/python/runtime/server.py` | The main loop — `process_queue()` |
| `lib/python/runtime/db.py` | Task/Run/Result storage (PostgreSQL + SQLite) |
| `lib/python/runtime/worktree.py` | Git worktree create/cleanup/diff/commit |
| `lib/python/runtime/mcp_tools.py` | MCP tool for mid-session harness checks |
| `lib/python/runtime/schema.py` | PostgreSQL DDL (5 tables) |
| `dashboard/api/app.py` | FastAPI backend (8 endpoints + WebSocket) |
| `dashboard/api/auth.py` | Google OAuth + JWT auth |
| `dashboard/frontend/index.html` | SPA with 4 views |
| `specs/014-autonomous-runtime.md` | Spec for the runtime |
| `specs/015-dashboard.md` | Spec for the dashboard |
