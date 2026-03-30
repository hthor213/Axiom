# 017: Runtime Infrastructure Review & Hardening

**Status:** draft

## Goal

Apply the same validation rigor to the foundation that we require of everything built on top of it.

The autonomous runtime (server, dashboard, adversarial pipeline) is the infrastructure that validates all autonomous output. It dispatches Claude Code sessions, runs 3-model adversarial reviews, enforces quality gates, and presents results for human approval. If this foundation has bugs, every result it produces is suspect.

Over 60 commits, 24 have been bug fixes — a 40% fix rate. Bugs cascade: a missing method crashed every run (`8b5eb02`), a watchdog that only watched stdout killed legitimate sessions during API overload (`68fe0e5`), failed sessions produced false "passed" results (`400a25f`). The dashboard showed `Tests: 0 passed, 0 failed` while Telegram reported `0 done, 1 failed` — the system disagreed with itself about what happened.

The adversarial pipeline (Gemini → Claude → GPT) reviews what agents build. But who reviews the pipeline? This spec is the answer: a systematic code review, refactor, and hardening of the runtime infrastructure. No new features — just making what exists trustworthy.

**This is also a reference artifact.** Future sessions (human or LLM) should see that the platform's validation infrastructure was itself validated with equal thoroughness. We built a system that prevents LLMs from shipping bad code — and then we subjected that system to the same standard. The foundation earned its authority.

## The Problem

### Five Interacting State Layers

The runtime manages five entity types with independent status fields that interact across boundaries:

```
Task:      queued → running → passed | failed | waiting_for_human
           failed → queued (re-queue)
           passed → rejected (via result rejection) → queued (re-queue)
           waiting_for_human → queued (via draft resume)

Run:       running → completed | stopped | failed

Session:   running → completed | failed | killed

Result:    created (approved=null) → approved=true | approved=false

Draft:     pending_answers → answered → resumed → approved | rejected
```

None of these transitions are enforced in code. `update_task_status` (`db.py:268`) accepts any string — you could set a "passed" task back to "running" without error. The state machine exists only in the developers' heads, which is exactly the kind of thing this platform was built to prevent.

### Bug Taxonomy (24 fixes in 60 commits)

| Category | Count | Examples |
|----------|-------|---------|
| **Process management** | 5 | Missing `get_session()` crashed every run; watchdog false kills on API overload; failed sessions producing false "passed" |
| **State management** | 5 | Rejected tasks blocking re-queue; runtime not triggered after re-queue; stale "live" badges |
| **Display** | 6 | Wrong agent counters; hidden checkboxes; template literal rendering as `${s.live}` |
| **Data flow** | 7 | Diff showing entire repo (base_commit lost); WebSocket async/sync threading; webhooks created but never sent |
| **Integration** | 6 | Missing env vars on MacStudio; PATH issues; `platform` CLI name caused fork bomb (2,066 processes, load avg 338) |
| **Adversarial pipeline** | 3 | No retry backoff; rate limiting from rapid API calls |

### Testing Gaps

- **466 tests exist**, but all agent calls are mocked — no test exercises real data flow
- No integration test runs queue → worktree → agent → adversarial → result
- No failure mode testing (timeout, consecutive failures, git conflicts, missing env)
- No dashboard → server contract verification
- "First e2e test working" is a human assertion, not an automated test
- The watchdog logic evolved over 3 consecutive commits as edge cases were discovered in production

### Root Pattern

Most bugs occur at **integration boundaries** — where data transitions between state layers. Unit tests mock these boundaries, so the boundaries are exactly what's untested. The server module (`server.py`, 1,300 lines) handles five distinct responsibilities in one file, making it hard to test any one responsibility in isolation.

## Approach: Three Pillars

### Pillar 1: Code Review + Refactor

`server.py` currently handles:
1. **Queue orchestration** — main loop, consecutive failure tracking, run lifecycle
2. **Process management** — Popen, watchdog, stdout/stderr monitoring, kill/cleanup
3. **Verification pipeline** — test → harness → adversarial → feedback → retry loop
4. **State transitions** — task/session/result status updates scattered throughout
5. **Prompt building** — agent prompt construction, draft context assembly

Split into focused, independently testable modules:

| New module | Responsibility | Extracted from |
|------------|---------------|----------------|
| `process_manager.py` | Agent subprocess lifecycle: launch, watchdog, monitor stdout/stderr, kill, drain output | `_run_agent_session` + `_run_fix_session` (lines 407-604) |
| `pipeline.py` | Verification pipeline: test → harness check → adversarial review → feedback assembly → retry loop | `_process_task` verification logic (lines 289-405) + `_run_adversarial` + `_run_tests` + `_assemble_adversarial_feedback` |
| `state.py` | State machine definitions + transition validation | New — extracted from implicit transitions in `db.py` and `server.py` |
| `server.py` | Orchestrator only: claim task, delegate to modules, save result, emit events | Remains, but shrinks to ~300 lines |

Each module gets a clear interface. `server.py` composes them. Tests can exercise each module independently AND through integration.

### Pillar 2: State Machine Enforcement

Add `VALID_TRANSITIONS` to `state.py` and wire into `db.py`:

```python
TASK_TRANSITIONS = {
    "queued": {"running"},
    "running": {"passed", "failed", "waiting_for_human"},
    "passed": {"rejected"},
    "failed": {"queued"},  # re-queue
    "rejected": {"queued"},  # re-queue after rejection
    "waiting_for_human": {"queued", "passed", "failed"},
}

def validate_transition(entity: str, current: str, target: str) -> None:
    """Raises ValueError if transition is not allowed."""
```

`update_task_status`, `update_session`, `finish_run` all validate before executing. Invalid transitions raise `ValueError` with the entity, current state, target state, and a hint about what went wrong. This catches an entire class of bugs at the source.

### Pillar 3: Integration Tests with Fake Agents

Create `tests/integration/` with a test infrastructure that exercises real data flow:

**Fake agent**: A shell script (`fake_agent.sh`) that simulates Claude CLI behavior without calling any LLM:
- `--succeed`: Creates files, writes to stdout, exits 0
- `--fail`: Exits 1 with stderr
- `--hang`: Never produces output (triggers startup watchdog)
- `--slow`: Produces output but runs past time limit
- `--stderr-only`: Writes only to stderr (tests watchdog doesn't false-kill)

**What's real vs. fake**:
- Real: SQLite database, git worktrees, subprocess management, state transitions, file I/O
- Fake: Claude CLI (shell script), adversarial API calls (patched to return controlled verdicts)

**Test categories**:

1. **Flow tests** — full queue → worktree → agent → result lifecycle
2. **State machine tests** — valid and invalid transitions for all 5 entity types
3. **Failure mode tests** — timeout, consecutive failures, missing CLI, git conflicts, stale worktrees, missing env vars
4. **Contract tests** — dashboard API response shapes match frontend expectations
5. **Error propagation tests** — failures at each layer boundary propagate correctly

## Non-Goals

- Rewriting the runtime architecture (this is hardening, not redesign)
- Calling real LLM APIs in tests (too slow, expensive, flaky)
- Performance optimization
- New features
- Dashboard frontend changes (this spec covers the backend infrastructure)

## Done When

- [ ] A task status transition that violates the defined state machine raises `ValueError` — setting a "passed" task to "running" is rejected, while "passed" → "rejected" succeeds
- [ ] An integration test completes the full queue → worktree → fake agent → verification → result flow using SQLite and a shell-script agent, finishing in under 10 seconds
- [ ] A failed agent session never produces a task with status "passed" — verified by a test that kills the fake agent mid-run and asserts `task.status == "failed"` and `result.adversarial_verdict == "SKIP"`
- [ ] The startup watchdog does not kill an agent that produces only stderr output — verified by a test running `fake_agent.sh --stderr-only` that completes normally
- [ ] Missing API credentials cause the adversarial pipeline to return `("SKIP", {"error": ...})` instead of raising an unhandled exception — verified by test with empty environment
- [ ] A rejected result followed by re-queue creates a new task in "queued" status for the same spec/item — verified by an integration test that rejects, re-queues, and confirms the new task claims successfully
- [ ] Dashboard contract tests verify that `/results`, `/agents`, `/specs`, and `/queue` response shapes include all fields the frontend JavaScript destructures (`spec_number`, `adversarial_verdict`, `diff_summary`, `approved`, `has_pending_review`)
- [ ] Zero tests passed + zero tests failed is not treated as "tests passed" for non-draft tasks — verified by test that asserts `task.status == "failed"` when test counts are both zero
- [ ] Worktree cleanup runs even when `_process_task` raises an unhandled exception — verified by test that forces an exception mid-task and confirms the worktree directory no longer exists
- [ ] All 6 failure modes (missing env, missing CLI, git conflict, stale worktree, concurrent claim, malformed adversarial report) have dedicated tests that verify correct error handling rather than crashes
- [ ] `server.py` is split into focused modules each ≤200 lines (soft cap), none exceeding 350 lines (hard cap) — the main `RuntimeServer.process_queue` orchestrates via composition, not by containing all logic inline
- [ ] Refactored code follows project coding standards: type hints, docstrings on public methods, dataclasses for structured data, no bare `except`, explicit error messages with context, 200/350 line caps enforced
- [ ] Python coding standards enforced (200-line soft cap, 350-line hard cap, 50-line function max).   
  Standing gate — re-verify at every checkpoint, commit, push, and deploy. New code must comply. Existing
   files above threshold: flag and propose a split plan if none exists. 
