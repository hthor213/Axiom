# 025: Dashboard Queue Redesign — Spec vs Dev, Scoped Runs

**Status:** active

## Goal

The dashboard queue view becomes the single control plane for all spec work: creating new specs, reviewing existing specs, and building features. Two buttons per spec card ("Review Spec" and "Build") replace the old checkbox-and-run model. Runs are scoped to the user's explicit selection — the runtime never silently picks up old queued tasks. A new "Idea Fab" input lets the user create specs directly from the dashboard.

This spec also adds stop/resume controls and crash recovery so the user can interrupt and continue work mid-pipeline.

## Architecture

### Idea Fab (new spec creation)

A freeform text input at the top of the Queue view. The user types a raw idea, and the system generates a structured spec draft.

```
User types: "need a way to share this platform with arnar so he
             can try it on his project. should export the harness
             and adversarial stuff but obviously not my keys"

→ Clicks "Draft Spec" (or Cmd+Enter)
→ LLM generates structured spec (number, title, goal, architecture, done when)
→ Inline preview with edit capability
→ "Save as Draft" writes specs/<number>-<title>.md
→ Spec appears in the Queue view below
```

**API:**

```
POST /specs/draft
Body: { "idea": "freeform text", "band": "mvp" }
Response: { "number": "026", "title": "platform-sharing", "markdown": "...", "suggested_prerequisites": ["010", "011"] }

POST /specs/save
Body: { "number": "026", "filename": "026-platform-sharing.md", "content": "..." }
Response: { "status": "saved", "path": "specs/026-platform-sharing.md" }
```

The LLM receives: the raw idea, the spec template format, INDEX.md (to avoid overlap), the vision spec (000), available numbers in the band, and standard constraints from CLAUDE.md. The LLM drafts; the human approves. No spec is written to disk without explicit "Save" action.

### Two-button UX

Each spec card shows two action buttons:

| Button | Action | When |
|--------|--------|------|
| **Review Spec** | Opens a spec viewer/editor popup | Always available |
| **Build** | Expands Done When checkboxes for per-item selection | Available for all specs. Warns on draft specs (see below) |

#### Review Spec flow

Clicking "Review Spec" opens a modal/popup with:

1. **Spec content** — the full spec rendered as readable markdown
2. **"Suggest modifications" text box** (optional) — the user describes what they want feedback on
3. **"Get Review" button** — triggers the review pipeline:
   - **GPT as mentor** (single-turn): "Here's this spec, what am I missing? Be a good teacher — no praise, not hostile."
   - **Claude as editor**: receives spec + GPT's mentor feedback → makes corrections
4. **Human reviews** the edited spec as a diff + GPT's feedback summary:
   - **Approve** → spec saved to disk, git committed
   - **Modify** → human adds comments → Claude re-edits → GPT re-reviews ("had this spec, human gave feedback, I made these changes — what do you think?") → back to human review
   - **Reject** → discard changes

Key design: GPT is the constructive mentor, Claude is the trusted editor, the human is the approver. No adversarial debate — this is spec refinement, not code review. No queued tasks or worktrees — synchronous API calls.

This reuses the same spec viewer/editor component as Idea Fab — the difference is that Idea Fab starts from a blank idea, while Review Spec starts from an existing spec.

#### Build flow

Clicking "Build" on a spec:

1. **Draft spec warning** — If the spec has `Status: draft`, a popup appears showing the full spec with the message: "Spec is draft — review before starting development?" The popup includes the same Review Spec controls (suggest modifications, submit). The user can review first or dismiss and proceed.
2. **Done When expansion** — The spec card expands to show all Done When items as checkboxes. Items already marked done are unchecked by default but can be re-checked for rework.
3. **"Run Selected Items" button** — Queues the selected items and starts a scoped run.

### Scoped runs

The current flow (`POST /queue` → `POST /run` processes entire queue) is replaced:

```
1. User clicks "Review Spec" or selects items + "Run Selected Items"
2. Frontend: POST /queue → response: {task_ids: [52, 53, 54]}
3. Frontend: POST /run {task_ids: [52, 53, 54]} → only these tasks are processed
4. Runtime: claim_next_task(task_ids=[52, 53, 54]) — scoped to this batch
```

`POST /run` without `task_ids` is rejected (HTTP 400). No more "process everything."

### Queue visibility

Queued tasks are visible in the Live tab — not just running tasks:

- The Live tab shows both queued (waiting) and running (active) tasks
- Each queued task shows a "Cancel" button
- When a run finishes, queued tasks that weren't processed stay visible with "Stale" badge
- A "Clear Stale" button cancels all tasks from previous sessions

**Automatic cleanup:** Tasks with `status = 'queued'` older than 24 hours are auto-cancelled on dashboard boot and periodically.

### Stop and resume

Tasks track their pipeline stage so work can be stopped and resumed mid-pipeline:

```
Pipeline stages (persisted to DB):
  agent_building → tests_running → triage_fixing → adversarial_review → complete
```

| Feature | Behavior |
|---------|----------|
| **Stop button** | Sends SIGTERM to the runtime process. Running task moves to `stopped` status with current stage preserved. Dashboard shows "Stopped" badge. |
| **Resume button** | Resumes a `stopped` task from its last completed stage. If stage is `adversarial_review`, skips agent session and goes straight to Gemini. |
| **Crash recovery** | On startup, the runtime checks for tasks with `status = 'running'` that have no live process. Marks them `stopped` with reason `crash_recovery`. |
| **Manual stage injection** | For testing: create a task, set `pipeline_stage = 'adversarial_review'`, click Resume → goes straight to Gemini review without building code first. |
| **External code import** | Code written outside the system (e.g., on a laptop in Claude Code) can enter the pipeline at `tests_running` — skipping the agent build stage and going straight to test generation, triage, and adversarial review. The user commits and pushes, clicks "Pull" on the dashboard, then starts a run from the `tests_running` stage. |
| **Pull button** | Dashboard "Pull" button triggers `git pull` on MacStudio so the server has the latest code. Eliminates the need to SSH into MacStudio when starting work locally and handing off to the pipeline. |

The `pipeline_stage` column on the tasks table tracks where the task is in the pipeline. The worktree is preserved (not cleaned up) when a task is stopped, so resume can pick up the exact file state.

**External code workflow:**
```
1. Developer writes code locally (laptop, Claude Code, etc.)
2. Commits and pushes to remote
3. Dashboard: clicks "Pull" → MacStudio runs git pull
4. Dashboard: selects spec + Done When items → "Run Selected Items"
5. Task starts at tests_running stage (skips agent_building)
6. Pipeline: generates tests → runs tests → triage → adversarial review
7. Results appear on dashboard as normal
```

This closes the loop between local development and the platform's testing/review infrastructure — the developer can start work anywhere and hand off to the pipeline for validation.

### Shared UI component: Spec viewer/editor

Both Idea Fab and Review Spec use the same spec viewer/editor component:

- Rendered markdown view of the spec
- Text input for modifications or instructions
- Diff preview after LLM edits
- Accept / reject / edit further controls
- Save to disk action

The component is parameterized: Idea Fab passes an empty spec + raw idea, Review Spec passes the existing spec + modification instructions.

## Key Decisions

- **Two buttons over smart routing** — Explicit user control. The user decides whether to review or build.
- **Scoped runs over queue-wide** — Only process what was just queued. Previous tasks are visible but not auto-processed.
- **Build warns on draft specs** — Soft guard, not a hard block. User can review first or dismiss and proceed.
- **No restart of old tasks** — Failed/passed tasks have results. They don't go back on the queue. To retry, the user explicitly re-queues.
- **Idea Fab lives in Queue view** — Spec creation belongs where specs are managed, not in a separate tab.
- **Shared spec editor** — One component for both creating and reviewing specs. Avoids building the same UI twice.
- **Review Spec uses Claude for edits, GPT for review** — Claude edits the spec per user instructions, then GPT reviews the result (per spec:024). Separation of roles: editor vs. reviewer.

## Prerequisites

- spec:015 (Dashboard) — UI home
- spec:024 (Queue Review Pipeline) — GPT single-turn review used by Review Spec flow

## Done When

### Idea Fab
- [ ] Queue view has a freeform text input ("Idea Fab") at the top
- [ ] "Draft Spec" sends text to API and returns structured spec markdown
- [ ] Generated spec follows existing format (Status, Goal, Architecture, Constraints, Done When)
- [ ] Inline preview shows the generated spec with edit capability
- [ ] "Save as Draft" writes the spec file to the repo's specs/ directory
- [ ] Spec numbering auto-detects next available number in the appropriate band

### Two-button UX
- [x] Each spec card shows "Review Spec" and "Build" buttons instead of a single checkbox
- [x] "Review Spec" opens a popup with spec content and "Suggest modifications" text input
- [x] GPT mentors the spec (single-turn, constructive teacher role), then Claude edits based on feedback
- [x] Human reviews diff with Approve / Modify / Reject; Modify iterates (Claude re-edits → GPT re-reviews)
- [x] "Build" expands Done When as progress indicators; "Build Spec" queues one task per spec (not per item)
- [x] "Build" on a draft spec shows warning with option to review first
- [x] Done items shown as progress indicators (not selectable checkboxes)

### Scoped runs
- [x] `POST /run` accepts `task_ids` parameter and only processes those tasks
- [x] `POST /run` without `task_ids` returns HTTP 400
- [x] `claim_next_task()` accepts optional `task_ids` filter

### Queue visibility
- [x] Live tab shows both queued and running tasks
- [x] Each queued task in Live tab has a "Cancel" button
- [x] Stale queued tasks (from previous sessions) are visible with "Stale" badge
- [x] Stale tasks can be cleared with a single action

### Stop / resume
- [x] Stop button in Live tab sends SIGTERM and moves task to `stopped` status
- [x] `stopped` tasks preserve their worktree and pipeline stage
- [x] Resume button on `stopped` tasks continues from last completed stage
- [x] Crash recovery on startup: orphaned `running` tasks marked `stopped` with reason
- [x] `pipeline_stage` column on tasks table tracks current position in the pipeline
- [ ] Manual stage injection works: set stage → Resume → skips to that stage

### External code import
- [x] Dashboard has a "Pull" button that triggers `git pull` on MacStudio
- [x] A task can start at `tests_running` stage, skipping `agent_building`, for externally written code
- [x] External code workflow: push → pull → select items → run from `tests_running` → tests + triage + adversarial review
