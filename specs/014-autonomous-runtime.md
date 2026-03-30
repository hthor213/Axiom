# 014: Autonomous Runtime — Server-Driven Development Loop

**Status:** draft

## Goal

Run multi-day development sessions with zero human presence. A deterministic server process (Python on MacStudio or n8n workflow) orchestrates the build-test-review cycle, calls LLMs via API for intelligence, and pings the user on Telegram (~1/day) for critical decisions only. Neither the human nor the LLM is trusted for long-running memory or staying on task — the server owns state.

This is NOT an "LLM running continuously" (OpenClaw pattern). This is a **deterministic server** that uses LLMs as callable tools, exactly like it uses pytest or git.

Inspired by OpenClaw's three patterns (heartbeat loop, multi-agent routing, scheduler) but implemented as deterministic infrastructure, not LLM autonomy.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  SERVER (Python on MacStudio)                         │
│                                                       │
│  Deterministic. Never forgets. Never drifts.         │
│                                                       │
│  State: PostgreSQL (:5433)                           │
│  Schedule: n8n (:5678) / webhook from dashboard      │
│  Dashboard: spec:015 on spliffdonk.com               │
│                                                       │
│  The server IS the memory. Not the LLM.              │
│  The server IS the task list. Not the human.         │
└──┬──────────┬──────────┬──────────┬──────────────────┘
   │          │          │          │
   │     ┌────▼───┐ ┌────▼───┐ ┌───▼────┐
   │     │ Gemini │ │ Claude │ │  GPT   │  ← Review only
   │     │  API   │ │  API   │ │  API   │    (stateless)
   │     └────────┘ └────────┘ └────────┘
   │
   ├──── Claude Agent SDK ──────────────┐
   │     (full Claude Code: 1M context, │  ← Building
   │      tool use, file editing,       │    (stateful)
   │      MCP tools, session resume)    │
   └────────────────────────────────────┘
         │
    ┌────▼────────┐     ┌────────────────┐
    │  Telegram   │     │  Dashboard     │
    │  (pings)    │     │  (spliffdonk)  │
    └─────────────┘     └────────────────┘
```

### Three layers

| Layer | What | Trust Level |
|-------|------|-------------|
| **Server** (Python/n8n) | State, scheduling, sequencing, file I/O, git, test running | Full trust — deterministic |
| **LLM APIs** | Code generation, review, judgment, spec writing | Partial trust — verify output |
| **Human** (via Telegram) | Critical decisions, approvals, course corrections | Partial trust — async, ~1/day |

### The Loop (server-side, deterministic)

```python
while not terminated:
    # 1. Read state from DB/file (not LLM memory)
    task = get_next_task()          # From spec Done When items / CURRENT_TASKS.md

    # 2. Check if human decision needed
    if task.needs_approval:
        telegram_notify("Need your approval: {task}")
        wait_for_response(timeout=24h)  # Non-blocking — server sleeps
        if not approved: skip(task)

    # 3. Execute via Claude Agent SDK (full Claude Code)
    session = await build_with_agent_sdk(task)  # worktree, tools, MCP
    # SDK handles file editing, bash, context — not raw API

    # 4–6. Verify → adversarial review → fix loop
    for attempt in range(max_adversarial_attempts):  # default 3
        test_result = run_pytest()
        spec_check = run_harness_check(task.spec)

        if not test_result.passed:
            break  # tests must pass before adversarial review

        review = adversarial_pipeline(code)  # Gemini → Claude → GPT

        if review.verdict == "PASS":
            mark_complete(task)
            git_commit(task)
            break

        # FAIL: assemble consolidated feedback, send back to Claude
        feedback = assemble_feedback(review)  # all 3 models' notes
        session = await fix_with_agent_sdk(task, feedback)
        # Re-verify on next iteration

    # 7. Daily summary
    if time_for_daily_ping():
        telegram_notify(daily_summary())

    # 8. Check termination
    if all_tasks_done() or critical_failure():
        telegram_notify("Session complete: {summary}")
        break
```

### Decision Points (what gets Telegram pings)

| Decision | Frequency | Blocking? |
|----------|-----------|-----------|
| Daily progress summary | 1/day | No |
| Spec ambiguity (multiple valid approaches) | As needed | Yes — waits for response |
| Critical test failure (3+ consecutive) | As needed | Yes |
| Phase completion (milestone boundary) | Per phase | No — continues unless told to stop |
| New spec needed (discovered during work) | As needed | Yes — needs human intent |

### Implementation Options

**Option A: Pure Python server on MacStudio**
- An `hth-platform serve` command that runs the loop
- State in `.runtime-state.json` (like orchestrator) or PostgreSQL (existing on MacStudio:5433)
- Telegram for notifications (existing `platform_telegram.py`)
- Cron or systemd for restarts

**Option B: n8n workflow on MacStudio**
- n8n trigger → Python script → LLM APIs → Telegram
- n8n handles scheduling, retries, error handling
- Python scripts handle the actual logic (harness, adversarial, git)
- Visual workflow editor for non-code changes

**Option C: Hybrid** (recommended)
- n8n as the scheduler/heartbeat (runs on MacStudio, already deployed at :5678)
- Python modules as n8n "Execute Command" nodes
- n8n "Telegram" node for notifications (built-in)
- n8n "Wait" node for human approval (built-in — pauses workflow until webhook response)
- State in PostgreSQL (already on MacStudio:5433)

Option C leverages everything already deployed.

## What We Take From OpenClaw (Lean, No Compromises)

| OpenClaw Pattern | Our Implementation | Key Difference |
|-----------------|-------------------|----------------|
| Heartbeat loop (agent stays alive 24/7) | n8n cron trigger (every N minutes) | Server heartbeat, not LLM heartbeat |
| Multi-agent routing (builder → verifier) | Adversarial pipeline (already built) | Deterministic routing, not LLM-decided |
| Scheduler primitive | n8n scheduler + PostgreSQL state | Visual workflow, not code-only |
| Message-based communication | Telegram + webhook responses | Human-in-loop at decision points only |

## What We Do NOT Take From OpenClaw

- LLM-driven routing decisions (we use deterministic domain routing via registry)
- "Autonomous agents" running indefinitely (we have termination conditions per Arnar)
- Security model compromises (their maintainer said "too dangerous for casual users")
- Messaging app as primary interface (Telegram is for pings only, not control)

## Resolved: Two Modes, One Protocol

**Status: RESOLVED — via Claude Agent SDK + Dashboard (spec:015)**

### The Insight

Stateless API calls are insufficient for code generation. Claude Code / Codex / Gemini CLI have superior context windows, memory, agent steering, and tool use (file editing, bash, etc.) that we cannot replicate with raw API calls. The core coding work must run inside these agent environments, not around them.

But humans get ideas faster than patience for implementing them, and LLMs are trained to say "sure, great idea!" — creating a deaf-leading-the-blind situation. The system must prevent both failure modes: human scope creep and LLM drift.

### Solution: Hybrid Architecture

**Core principle**: We will never be as good as Claude Code / Codex / Gemini at managing multi-agent orchestration, context windows, and tool use. But we are much better at deterministic things: workflows, persistent memory, scheduling, and cross-model verification. So we split responsibilities:

| Python server owns | Claude Code owns |
|---------------------|-----------------|
| Task queue, scheduling | HOW to build (maestro, sub-agents, analyst) |
| Persistent state (PostgreSQL) | 1M context window, tool use |
| Termination conditions | Breaking specs into milestones |
| Adversarial review assembly | Delegating to specialized agents |
| Cross-model feedback loops | File editing, bash, code generation |

**Building = Claude Code with full capabilities (including maestro)**

The server gives Claude Code the full spec and all its Done When items — not atomic sub-tasks. Claude Code uses maestro to break the work into milestones, delegates to sub-agents, tracks progress, and course-corrects. The server's `max_turns` is the only guardrail during the build phase.

```bash
claude -p "Build spec 014: [full spec content + Done When items]. \
  Use maestro to plan milestones. Delegate to sub-agents as needed. \
  Run tests after each milestone." \
  --dangerously-skip-permissions --max-turns 30
```

**Review = Python server assembles cross-model feedback**

After Claude Code finishes, the server takes over:
1. Runs pytest (deterministic)
2. Runs `hth-platform harness check` (deterministic)
3. Sends diff to adversarial pipeline: Gemini critiques → Claude defends → GPT arbitrates
4. **Assembles a refined course of action** from all three models' feedback
5. Sends that back to Claude Code: "Fix these issues: [consolidated feedback]"
6. Claude Code fixes, server re-verifies — loop until pass or termination

This is the key insight: **the LLM does what LLMs are best at (intelligence, creativity, multi-step reasoning), the server does what deterministic code is best at (memory, scheduling, cross-model verification, termination).**

**Custom MCP tools = Bridge between harness and agent**
- Expose `hth-platform harness check` as an MCP tool that Claude calls mid-session
- The agent self-verifies against spec Done When criteria during the build, not just after
- Deterministic checks run inside the agent's session, keeping the harness in control

### Two Modes, Complementary

| Mode | Where | Tool | What |
|------|-------|------|------|
| **Interactive** | Laptop | Claude Code (direct) | Judgment-heavy: architecture, specs, creative decisions |
| **Autonomous** | MacStudio | Claude Agent SDK (server-managed) | Execution: build modules, run tests, adversarial review |

The daily rhythm:
1. **Check in**: Open dashboard (spec:015), review what the server built overnight
2. **Steer**: Approve/reject results, select next specs via checkboxes, click "Run"
3. **Walk away**: Server works through the queue — 2 hours or 2 days
4. **Telegram ping**: "Batch complete — 4 tasks done, 1 needs review" → back to step 1

### Mode Handoff Protocol

**Human → Server**: Dashboard "Run" button writes selected tasks to PostgreSQL queue, triggers n8n webhook. Each task gets its own git worktree and branch.

**Server → Human**: Server commits to feature branches, writes session summaries to DB. Dashboard shows results. Telegram sends "batch complete" ping. Developer's `/start` also reads the summaries via git pull.

**Parallel work**: Yes — human works on one spec interactively while server builds others in separate worktrees. Git isolation prevents conflicts.

### Git Worktree-per-Task Pattern

Each autonomous task runs in its own worktree:
```
/worktrees/spec-012-feature-a/  → Claude Agent SDK session
/worktrees/spec-013-feature-b/  → Claude Agent SDK session
```
- Git isolation: one agent cannot corrupt another's work
- Natural output: each task produces a PR for review
- Claude Code's `--worktree` flag supports this natively

## Prerequisites (Must Be Done First)

1. **`~/.claude/` synced to MacStudio** — Claude Code on MacStudio must have the same skills (start, checkpoint, refresh) and agents (maestro, analyst) as the laptop. Without these, "use maestro to plan" fails. Rsync `~/.claude/skills/` and `~/.claude/agents/` to MacStudio's `~/.claude/`.
2. **spec:003 (Validation Tiers)** — status: draft → active. The verifier needs deterministic tiers to run against.
3. **spec:004 (/review skill)** — The autonomous loop needs a review step that runs without a human.
4. **Wire model registry into adversarial pipeline** — Replace model_resolver.py with registry.

## Inputs
- CURRENT_TASKS.md / BACKLOG.md (task queue)
- Spec Done When items (success criteria)
- API keys (.env)
- MacStudio infrastructure (n8n, PostgreSQL, Docker)
- Telegram bot (existing)

## Outputs
- Built + tested + reviewed code (committed to git)
- Daily Telegram summaries
- `.runtime-state.json` or PostgreSQL state table
- Adversarial review reports per task

## Boundary

This spec owns the **orchestration engine**: task queue, scheduling, agent sessions, adversarial assembly, git operations, Telegram notifications, termination conditions.

Dashboard endpoints and frontend are defined in spec:015. This spec owns the runtime logic they call.

## Done When

### Runtime core
- [x] Claude Code CLI runs on MacStudio and builds at least one spec without human intervention
- [x] Git worktree per task (isolated branches) — `lib/python/runtime/worktree.py`
- [x] Custom MCP tool exposes `hth-platform harness check` — `lib/python/runtime/mcp_tools.py`
- [x] Adversarial review wired in server loop — `lib/python/runtime/server.py`
- [x] State persists in PostgreSQL — schema deployed on MacStudio :5433
- [x] Termination conditions enforced — max_turns, time_limit, failure_count in RuntimeConfig
- [x] Parallel task processing: multiple `process_queue()` loops claim tasks atomically via `claim_next_task()` with `FOR UPDATE SKIP LOCKED`

### Telegram notifications
- [x] Telegram "batch complete" notification — in server.py `_send_batch_complete()`
- [x] Telegram draft notifications send dashboard link instead of inline questions — replies noted as not captured
- [x] Draft Q&A via Telegram: after Claude refines a draft spec, server extracts "Questions for Human" section, saves context to `draft_reviews` table, sends questions via Telegram. Task enters `waiting_for_human` status.

### Draft review (autonomous)
- [x] Draft session resume: when user answers questions (via dashboard), server creates new Claude session with full context: original spec + refined spec + Q&A + Gemini feedback. Version increments (v0.1 -> v0.2).
- [x] Spec alignment check: after every build, Gemini classifies changes as A) direct from spec, B) aligned but implicit, C) outside spec. Category C items require mandatory Telegram approval before proceeding. Server-enforced via `NEEDS_HUMAN` verdict.

### Git operations
- [x] Git credentials on MacStudio: server can push to GitHub. MacStudio agents are effectively team members — the runtime manages the dev process (create branches, merge approved work, push to origin)
- [x] Approved work merges automatically: approve in dashboard → server runs `git merge` → pushes to origin. Conflicts route back to Review with resolution options

### Quality gates
- [x] Quality gates enforced: SKIP verdict = fail (unreviewed code doesn't ship), 0 tests ran = fail (untested code doesn't ship). Draft reviews exempt from test/adversarial requirements
