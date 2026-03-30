# 005: /ship — Review, Commit, Push, Deploy Pipeline

**Status:** active

## Goal

The ship pipeline. One implementation, two interfaces: the `/ship` CLI skill for interactive Claude Code sessions, and the "Ship" button in the dashboard for async autonomous results. Both trigger the same underlying flow: verify work, commit, push, create PR (or merge directly), optionally deploy.

For interactive sessions: developer finishes work, types `/ship`, the skill runs tests, checks spec drift, opens a PR, and optionally deploys.

For dashboard: agent built something, adversarial review passed, developer reviews the diff, clicks "Looks Good — Ship It," the pipeline commits, pushes, creates PR or merges, and optionally deploys to a test URL first.

**Test-then-promote flow:** After shipping to a test URL, the developer reviews the live result and either promotes to production or reports issues. When issues are reported, the pipeline distinguishes between scope clarification (amend spec, redevelop) and scope expansion/contradiction (flag to developer, require explicit spec change decision before any work resumes).

Same pipeline. Same safety gates. Two entry points.

**Out of scope:** internationalization/localization, plugin hooks for custom pipeline steps, fine-grained RBAC (single-developer tool).

## User Flow — Interactive (`/ship`)

```
Developer in Claude Code session:
  /ship

1. Detect base branch, fetch and merge latest
2. Run test suite (if present), report results
3. Check specs/000-* currency — flag drift
4. Check BACKLOG.md — completed work moved to Done
5. Run /review if skill exists (integrates with spec:004)
6. Open PR via `gh pr create` with structured description
7. For projects with deploy config: prompt "Deploy to test URL first, or production?" and execute accordingly
```

## User Flow — Dashboard ("Ship" button)

```
Results View — after adversarial review passes:

┌─────────────────────────────────────────────┐
│  Task #12: spec:003 — Validation tier enum  │
│  Adversarial: PASS                          │
│  Tests: 42 passed, 0 failed                │
│  Branch: auto/spec-003-task-12              │
│                                             │
│  [View Diff]  [View Adversarial Report]     │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  Commit message (editable):        │    │
│  │  "feat: add validation tier enum   │    │
│  │   and tier assignment logic"       │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Strategy: ( ) Create PR  (x) Merge to main│
│                                             │
│  [ Looks Good — Ship It ]  [ Reject ]       │
│                                             │
│  Deploy after merge:                        │
│  [x] Test URL first (spliffdonk.com/test/…) │
│  [ ] Straight to production                 │
│  [ ] Run post-deploy smoke test             │
└─────────────────────────────────────────────┘

1. Developer reviews diff (required — Ship disabled until viewed)
2. Edits commit message if needed
3. Chooses strategy: Create PR or Direct Merge
4. Chooses deploy path: test URL, production, or both sequentially
5. Clicks "Ship" → pipeline executes
```

## Test URL Flow

When "Test URL first" is selected, the pipeline deploys to a test URL (e.g. `spliffdonk.com/test/<slug>`) and then pauses, waiting for developer sign-off before any production deploy.

```
After test deploy completes:

┌─────────────────────────────────────────────┐
│  Task #12 — Live at test URL               │
│  https://spliffdonk.com/test/spec-003-t12  │
│                                             │
│  [ ✓ Promote to Production ]               │
│  [ ✗ Report Issues ]                        │
└─────────────────────────────────────────────┘
```

**Promote to Production:** Runs the production deploy step with the same commit already merged. No re-merge, no new pipeline — just the deploy step.

**Report Issues:** Developer describes what's wrong. The pipeline classifies the feedback:

```
Developer: "The enum labels show wrong, also we need a search filter"

Pipeline response:
┌─────────────────────────────────────────────────────────────┐
│  Feedback analysis:                                         │
│                                                             │
│  ✓ Scope clarification (will amend spec and redevelop):    │
│    — "enum labels show wrong" → spec:003 §2 says labels    │
│      should use display names; implementation used codes.   │
│      Will update spec to make this explicit and fix.        │
│                                                             │
│  ⚠ Scope expansion (requires your decision):               │
│    — "search filter" is not in spec:003. This is new        │
│      functionality. Options:                                │
│      (a) Add to spec:003 and redevelop (takes feature       │
│          out of test, scope change logged)                  │
│      (b) Create a new spec for search filter separately     │
│      (c) Skip — ship current version without search filter  │
│                                                             │
│  [ Amend spec + fix clarifications ]                        │
│  [ Choose option for scope expansion ]  [ Skip for now ]    │
└─────────────────────────────────────────────────────────────┘
```

**Scope clarification path:** Spec is amended to make the intent explicit, the feature is pulled back from test, and the agent redevelops against the clarified spec. The original test deploy is marked superseded.

**Scope expansion path:** No work proceeds until the developer makes an explicit decision. The dashboard records the decision and the scope change reason. If the developer chooses to expand scope, the feature is pulled back from test, the spec is updated, and the task re-enters the development queue. Per the spec-driven development principle: changing scope is a valid choice, but it must be a conscious, logged decision — not a quiet drift.

**Contradiction path:** If developer feedback directly contradicts the current spec (e.g. "actually the enum should be free-text, not fixed values"), the pipeline flags this as a contradiction, not a clarification:

```
  ⚠ Contradiction with spec:003 §2:
    Spec says: fixed enum values (TIER_1, TIER_2, TIER_3)
    You're asking for: free-text input
    These cannot both be true. If you want free-text, the spec
    must change. Do you want to update spec:003 to reflect this?
    [ Yes — update spec and redevelop ]  [ No — keep current spec ]
```

## Pipeline Steps (shared implementation)

### 1. Verify

**Tests:**
- Discovery: check for `pytest.ini`, `pyproject.toml [tool.pytest]`, `Makefile` with `test` target, or `package.json` with `test` script — in that priority order. If multiple are found, all are run.
- Supported runners: pytest (Python), npm test / vitest (JS). Other runners: execute as shell command if configured in `SHIP_TEST_COMMAND` env var.
- Results reported as: `N passed, M failed` with failed test names and tracebacks. Any failure aborts the pipeline.
- Dashboard: tests already verified by agent run; still re-run on interactive `/ship`.

**Spec drift:**
- "Drift" means a spec file under `specs/000-*.md` has a `last_updated` date older than 30 days, or the spec's Done When items reference files that don't exist in the repo.
- Non-blocking: pipeline flags and reports drift but does not abort. Developer sees the warning and proceeds.
- Remediation: warning message lists affected specs with suggested action ("update last_updated or mark as stable").

**BACKLOG hygiene:**
- Check that BACKLOG.md exists and that any task marked `[x]` in an "In Progress" or "To Do" section also appears in the "Done" section.
- Non-blocking: flags mismatches, does not abort.

### 2. Commit
- Interactive: commit all staged changes with structured message. If working tree is dirty (unstaged changes), pipeline aborts with: `"Dirty working tree — stage or stash changes before shipping."`
- Dashboard: worktree branch already has agent's commit; if developer edited the commit message, amend with `git commit --amend --no-edit -m "<new_message>"`.
- If nothing to commit (clean index on interactive), pipeline aborts: `"Nothing to commit."`

### 3. Push
- Push branch to `origin` using `git push origin <branch>` (no `--force`, ever).
- If push is rejected (non-fast-forward), pipeline aborts: `"Push rejected — pull and rebase manually, then re-run /ship."`
- If remote is unreachable, pipeline aborts: `"Remote unreachable — check network and retry."`

### 4. PR or Merge

**Base branch detection:**
- Read `SHIP_BASE_BRANCH` env var if set; otherwise default to `main`.
- If `main` doesn't exist, fall back to `master`. If neither exists, abort with: `"Cannot determine base branch — set SHIP_BASE_BRANCH."`

**Fetch and merge:**
- Run `git fetch origin <base>` then `git merge origin/<base>` (no rebase).
- If merge produces conflicts, pipeline aborts: `"Merge conflicts detected — resolve conflicts manually, then re-run /ship."` No partial merge state is left; pipeline runs `git merge --abort`.

**Create PR:**
- `gh pr create` with commit message as title.
- Structured body: Summary (from commit message body), Test Plan (test results summary), Adversarial Report Summary (if from dashboard), Link to dashboard result (if from dashboard).
- If a PR already exists for the branch, pipeline reports the existing PR URL and skips creation (not an error).
- If `gh` is not authenticated or PR creation fails, pipeline aborts with the `gh` error output.

**Direct Merge:**
- `git checkout <base> && git merge --ff-only <branch>` — fast-forward only.
- If fast-forward is not possible (histories have diverged), abort: `"Cannot fast-forward — fetch latest base and rebase branch before direct merge."`
- If branch protection rules block the push, report the git error and abort.
- After successful merge: `git push origin <base>`.

### 5. Deploy (optional)

**Configuration:**
```bash
# Single target (env var)
DEPLOY_COMMAND="ssh macstudio 'cd /app && docker compose up -d --build'"
DEPLOY_TIMEOUT=120  # seconds, default 120

# Multiple targets (project config, e.g. ship.toml)
[[targets]]
name = "Test URL"
command = "ssh macstudio 'cd /app && ./deploy-test.sh'"
url_pattern = "https://spliffdonk.com/test/{slug}"
timeout = 60
role = "test"   # "test" | "production"

[[targets]]
name = "Production"
command = "ssh macstudio 'systemctl restart dashboard'"
timeout = 60
role = "production"

[[targets]]
name = "Run post-deploy smoke test"
command = "ssh macstudio 'cd /app && python smoke_test.py'"
timeout = 30
role = "smoke"
```

**Behavior:**
- Interactive: prompted "Deploy to test URL, production, or skip?" for each target group; test URL is the suggested default if configured.
- Dashboard: checkbox per target, test URL checked by default if configured, production unchecked by default.
- Each target runs with its configured timeout (default 120s). On timeout: kill process, report `"Deploy timed out after Ns"`, mark step failed.
- Deploy failure is reported but does not roll back the merge/PR — merge is already complete.
- Deploy logs (stdout + stderr) are captured and shown inline (CLI) or in a collapsible log panel (dashboard).
- Multiple targets execute in order. If one fails, remaining targets are skipped and failure is reported.
- After a test deploy, pipeline enters **awaiting promotion** state. Production deploy only runs when developer explicitly promotes (see Test URL Flow above).

**Slug generation for test URLs:**
- Slug is derived from the branch name: `auto/spec-003-task-12` → `spec-003-task-12`.
- If `url_pattern` is set in `ship.toml`, the slug is substituted into the pattern.
- Test URL is shown in the dashboard and printed in CLI output immediately after test deploy completes.

## Implementation

The core logic lives in `lib/python/` as a shared module (not duplicated between skill and dashboard):

```
lib/python/ship/
    pipeline.py       — ShipPipeline class: verify → commit → push → pr/merge → deploy
    strategies.py     — PR vs direct merge logic
    deploy.py         — Deploy command execution with timeout
    state.py          — PipelineRun state persistence for retry
    feedback.py       — Classify developer feedback: clarification vs expansion vs contradiction
    promotion.py      — Test-to-production promotion flow
```

Both entry points call the same `ShipPipeline`:
- `/ship` skill: calls pipeline from Claude Code session context
- Dashboard API: `POST /results/{id}/ship` calls pipeline from FastAPI

## API Endpoint (Dashboard)

```
POST /results/{id}/ship
Body: {
    "commit_message": "feat: add validation tier enum",
    "strategy": "merge" | "pr",
    "deploy_targets": ["Test URL"]
}
Response: {
    "status": "shipped" | "failed" | "already_shipped" | "awaiting_promotion",
    "run_id": "run_abc123",
    "test_url": "https://spliffdonk.com/test/spec-003-task-12",  // if test deploy ran
    "steps": [
        {"step": "commit", "status": "ok", "sha": "abc123"},
        {"step": "push", "status": "ok", "remote": "origin"},
        {"step": "merge", "status": "ok", "base": "main"},
        {"step": "deploy_test", "status": "ok", "target": "Test URL", "url": "https://spliffdonk.com/test/spec-003-task-12", "output": "..."}
    ]
}

POST /results/{id}/promote
Body: {} (empty — promotes the awaiting test deploy to production)
Response: {
    "status": "promoted" | "failed",
    "run_id": "run_abc123",
    "steps": [
        {"step": "deploy_production", "status": "ok", "target": "Production", "output": "..."}
    ]
}

POST /results/{id}/feedback
Body: {
    "feedback": "The enum labels show wrong, also we need a search filter"
}
Response: {
    "clarifications": [
        {"issue": "enum labels show wrong", "spec_ref": "spec:003 §2", "action": "amend spec and redevelop"}
    ],
    "expansions": [
        {"issue": "search filter", "spec_ref": null, "action": "requires decision", "options": ["add_to_spec", "new_spec", "skip"]}
    ],
    "contradictions": []
}

POST /results/{id}/feedback/resolve
Body: {
    "clarification_actions": ["amend_and_redevelop"],
    "expansion_decisions": [{"issue": "search filter", "decision": "new_spec"}]
}
```

**Idempotency:** If the result has already been shipped (status `shipped`), the endpoint returns `{"status": "already_shipped", "run_id": "<original_run_id>"}` and takes no action. Shipping the same result twice is a no-op.

**Concurrency:** The endpoint acquires a per-result lock before executing. Concurrent ship requests for the same result ID return `{"status": "already_shipped"}` or a 409 if the first is still in progress.

Each step executes sequentially. If any step fails, the pipeline stops and returns the partial result with the failure reason. Developer can retry from the failed step (see Retry below).

## Retry After Failure

Pipeline state is persisted to `lib/python/ship/state.py` (SQLite-backed, keyed by `run_id`):
- Each step records: status (`ok` | `failed` | `skipped` | `awaiting_promotion`), timestamp, output.
- On retry (`POST /results/{id}/ship` with same body, or re-running `/ship`), completed steps are skipped and execution resumes from the failed step.
- Developer cannot skip steps — the pipeline always resumes in order from the point of failure.
- State is retained for 7 days, then purged.
- `awaiting_promotion` state is not retried automatically — it persists until the developer acts (promote or report issues).

## Audit Logging

All pipeline actions are appended to `logs/ship.log` (JSONL format):

```json
{"timestamp": "2024-01-15T10:23:00Z", "run_id": "run_abc123", "result_id": "12", "actor": "dashboard", "step": "merge", "status": "ok", "sha": "abc123", "base": "main"}
{"timestamp": "2024-01-15T10:25:00Z", "run_id": "run_abc123", "result_id": "12", "actor": "dashboard", "step": "deploy_test", "status": "ok", "url": "https://spliffdonk.com/test/spec-003-task-12"}
{"timestamp": "2024-01-15T10:30:00Z", "run_id": "run_abc123", "result_id": "12", "actor": "dashboard", "step": "feedback", "status": "ok", "detail": "clarification: enum labels; expansion: search filter (decision: new_spec)"}
{"timestamp": "2024-01-15T10:31:00Z", "run_id": "run_abc123", "result_id": "12", "actor": "dashboard", "step": "scope_change", "status": "ok", "detail": "scope expansion approved: search filter → new spec created", "reason": "developer decision"}
```

Scope changes get their own log entry with `"step": "scope_change"` and a `"reason"` field recording whether the change was a clarification, expansion, or contradiction resolution. This creates a permanent record of every time scope moved.

Fields: `timestamp` (ISO 8601), `run_id`, `result_id` (if dashboard), `actor` (`"dashboard"` or `"cli"`), `step`, `status`, `detail` (error message or relevant output).

Logs are local files. No remote log shipping in v1. Retention: keep last 90 days (daily rotation). Access: any process with filesystem access (single-developer tool, no ACL).

## User Feedback

**CLI (`/ship`):**
- Each step prints a status line as it starts and completes: `[ship] verify: running tests...` → `[ship] verify: 42 passed ✓`
- Warnings (drift, backlog) printed in yellow with `[warn]` prefix.
- Errors printed in red with `[error]` prefix and abort message.
- Long-running steps (push, deploy) show elapsed time every 10 seconds.
- After test deploy: prints test URL and prompts `"Promote to production? (yes/no)"`.
- After feedback classification: prints table of clarifications, expansions, and contradictions; prompts for decisions on expansions before proceeding.

**Dashboard:**
- Each step shows a spinner while running, then ✓ (green) or ✗ (red) on completion.
- Deploy log output shown in a collapsible panel below the step row.
- On failure: inline error message with the exact failure reason; "Retry from here" button appears next to the failed step.
- After test deploy: prominent "Promote to Production" and "Report Issues" buttons; test URL shown as a clickable link.
- After feedback submitted: structured panel showing clarifications (auto-handled), expansions (require decision), and contradictions (require decision) — each with appropriate action buttons.

## Safety

- **No auto-ship.** Adversarial PASS does not trigger shipping. A human must act.
- **Diff review required.** Dashboard: Ship button disabled until diff panel is expanded (frontend tracks `diff_viewed: bool`). Interactive: `/review` runs first if available.
- **Deploy is never default.** Opt-in per action — test URL checkbox checked by default only if configured, production always unchecked, prompt requires explicit "yes."
- **Production requires promotion.** When test URL is used, production deploy never runs automatically. Developer must explicitly promote.
- **Scope changes require decisions.** Expansions and contradictions block redevelopment until the developer makes an explicit, logged decision. Clarifications are handled automatically (spec amended + redevelop) but are still logged.
- **Force-push never.** Uses `git push` (no `--force`). If rejected, pipeline aborts with instructions.
- **Dirty tree blocked.** Interactive: uncommitted changes abort the pipeline before any git operations.
- **Rollback info.** After merge, shows the merge commit SHA and `git revert <sha>` for quick rollback.
- **All steps logged.** Pipeline actions recorded in `logs/ship.log` for audit trail, including every scope change decision.
- **Credentials:** Git credentials via standard git credential helpers (ssh keys, HTTPS tokens). Deploy credentials via ssh keys or env vars — never stored in pipeline state or logs. Pipeline runs as the invoking user; no privilege escalation.

## Environment Prerequisites

- `git` ≥ 2.30
- `gh` CLI ≥ 2.0, authenticated (`gh auth status` passes)
- Python ≥ 3.11 (for `lib/python/ship/`)
- SSH access configured for any deploy targets (key-based, not password)
- `SHIP_BASE_BRANCH` (optional, defaults to `main`)
- `DEPLOY_COMMAND` / `DEPLOY_TIMEOUT` (optional, for single-target deploy)
- `ship.toml` in project root (optional, for multi-target deploy config including test URL pattern)

## Inputs

- Current git branch
- Test suite (discovered by convention or `SHIP_TEST_COMMAND`)
- `specs/*.md` — spec currency check
- BACKLOG.md — completed items should be in Done
- Deploy config (`ship.toml` or env vars), including test URL pattern and production targets
- Developer feedback (post-test-deploy, via dashboard or CLI prompt)

## Outputs

- Test results (pass/fail with counts and failure details)
- Spec drift report (warnings only)
- BACKLOG hygiene warnings (non-blocking)
- PR URL or merge commit SHA
- Pipeline step-by-step status with per-step output
- Rollback instruction (`git revert <sha>`) after merge
- Test URL (if test deploy ran)
- Feedback classification report (clarifications / expansions / contradictions) when developer reports issues
- Scope change log entries for every decision made
- Optional: deployment execution result and logs

## Key Decisions

- Integrates with `/review` (runs review before shipping if skill exists; review failure blocks ship)
- Uses `gh` CLI for PR creation (no direct GitHub API)
- Deploy is optional, prompted (interactive) or checkbox (dashboard); test URL is suggested default if configured, production always unchecked
- Test-then-promote is a first-class flow: pipeline can pause at `awaiting_promotion` state indefinitely
- Feedback on test deploys is classified as clarification, expansion, or contradiction — each has a distinct handling path that ensures scope changes are conscious and logged
- One `ShipPipeline` implementation shared between CLI and dashboard
- Pipeline is sequential and stops on first failure — no partial ships
- Merge strategy is fast-forward only for direct merge; conflicts always abort
- Idempotent API: shipping twice returns `already_shipped`, not an error

## Prerequisites
- spec:004 (/review skill) — optional integration, runs before shipping; failure blocks ship
- spec:015 (Dashboard) — for the dashboard entry point
- spec:014 (Autonomous Runtime) — produces the results being shipped

## Done When

- [ ] `/ship` skill exists at `~/.claude/skills/ship/SKILL.md`
- [ ] Base branch detected from `SHIP_BASE_BRANCH` env var, falling back to `main` then `master`; pipeline aborts with clear message if none found
- [ ] `git fetch` + `git merge` runs before commit; merge conflicts abort with `git merge --abort` and a human-readable message
- [ ] Test suite discovered via `pytest.ini`, `pyproject.toml`, `Makefile test` target, or `package.json test` script; all discovered suites run; any failure aborts pipeline
- [ ] Spec drift check reports specs with `last_updated` older than 30 days or missing referenced files; non-blocking warning printed
- [ ] BACKLOG.md check reports tasks marked `[x]` in To Do or In Progress sections that are absent from Done section; non-blocking warning printed
- [ ] `/review` skill runs before PR/merge if available; review failure (non-zero exit) aborts pipeline
- [ ] Dirty working tree (unstaged changes) aborts interactive `/ship` before any git operations
- [ ] PR created via `gh pr create` with structured body (Summary, Test Plan, Adversarial Report, dashboard link); if PR already exists for branch, existing URL reported and creation skipped
- [ ] Direct merge uses `--ff-only`; non-fast-forward aborts with instructions
- [ ] After merge, rollback instruction (`git revert <sha>`) printed to user
- [ ] Deploy step reads `DEPLOY_COMMAND` env var or `ship.toml` for named targets; deploy never runs without explicit opt-in
- [ ] `ship.toml` supports `role = "test" | "production" | "smoke"` per target; test URL pattern configured via `url_pattern` field with `{slug}` substitution
- [ ] After test deploy, pipeline enters `awaiting_promotion` state; test URL printed/displayed to developer; production deploy does not run until developer explicitly promotes
- [ ] `POST /results/{id}/promote` triggers production deploy for a result in `awaiting_promotion` state; no re-merge occurs
- [ ] `POST /results/{id}/feedback` accepts developer feedback text and returns classified response: `clarifications`, `expansions`, `contradictions` arrays
- [ ] Clarifications are handled automatically: spec amended with explicit wording, feature pulled from test, task re-queued for redevelopment; action logged
- [ ] Expansions block redevelopment until developer chooses: add to current spec, create new spec, or skip; no work proceeds without an explicit decision
- [ ] Contradictions are flagged distinctly from expansions with reference to the conflicting spec section; developer must decide to update spec or keep current spec before pipeline proceeds
- [ ] Every scope change decision (clarification, expansion, contradiction resolution) logged to `logs/ship.log` with `"step": "scope_change"` and `"reason"` field
- [ ] Deploy timeout enforced (default 120s, configurable per target); timeout kills process and marks step failed
- [ ] Deploy failure reported with captured stdout/stderr; merge is not rolled back
- [ ] Dashboard Ship button disabled until diff panel is expanded (frontend `diff_viewed` flag)
- [ ] `POST /results/{id}/ship` returns `already_shipped` if result was previously shipped; no duplicate execution
- [ ] Concurrent ship requests for same result ID return 409 or `already_shipped`
- [ ] Pipeline step state persisted to SQLite via `state.py`; retry resumes from failed step, skipping completed steps; `awaiting_promotion` state persists until developer acts
- [ ] All pipeline steps appended to `logs/ship.log` in JSONL format with `timestamp`, `run_id`, `actor`, `step`, `status`, `detail`
- [ ] CLI prints per-step status lines with elapsed time for long-running steps; errors in red, warnings in yellow; after test deploy prints URL and promotion prompt; after feedback prints classification table
- [ ] Dashboard shows per-step spinner → ✓/✗; deploy logs in collapsible panel; "Retry from here" button on failure; "Promote to Production" and "Report Issues" buttons after test deploy; structured feedback panel with per-item action buttons