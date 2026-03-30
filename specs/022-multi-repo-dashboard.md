

# 022: Multi-Repo Dashboard — Project Selector and Session Isolation

**Status:** draft

## Goal

The dashboard (spec:015) currently manages a single repo. This spec adds a project selector so the developer can manage multiple repos from the same dashboard, with each repo getting its own isolated Claude Code sessions, task queues, worktrees, and adversarial reviews. When two repos are running simultaneously, they must not interfere — different branches, different worktrees, different context.

This is the difference between "a dashboard for one project" and "a control plane for all your projects."

## Architecture

```
┌─────────────────────────────────────────────┐
│  Dashboard (spliffdonk.com/dashboard)       │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  Project Selector (top bar)         │    │
│  │  [☁✓ ai-dev-framework] [☁ golf] .. │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Queue | Live | Results | History           │
│  (all scoped to selected project)           │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  API: all endpoints accept ?project=<id>    │
│                                             │
│  Projects table:                            │
│  id | name | repo_path | remote_url |       │
│  local_status | remote_status | branch      │
│                                             │
│  Tasks, runs, results all have project_id   │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │  Per-project:       │
    │  - Own worktree dir │
    │  - Own task queue   │
    │  - Own spec scanner │
    │  - Own base branch  │
    │  - Own .env / keys  │
    └─────────────────────┘
```

## Project Sync Status

Each project in the selector shows a small icon indicating where it lives and whether local and remote are in sync:

| Icon | Meaning | State |
|------|---------|-------|
| ☁✓ | **Cloud + Local, in sync** | Remote exists, local clone exists, no unpushed/unpulled commits |
| ☁↕ | **Cloud + Local, out of sync** | Remote exists, local clone exists, but ahead/behind |
| ☁ | **Cloud only** | Remote URL known but no local clone on this machine |
| 💾 | **Local only** | Local repo exists, no remote configured |
| ✦ | **New / empty** | Just created via "New Project" — skeleton only |

The sync status is computed on project selection and periodically refreshed:

- **Local exists?** — check if `repo_path` is a valid git directory
- **Remote exists?** — check if `remote_url` is set and reachable (`git ls-remote`)
- **In sync?** — compare `git rev-parse HEAD` with `git rev-parse @{u}` (ahead/behind count)

### Actions by State

- **Cloud only (☁):** Dashboard offers a "Clone to Local" button → runs `git clone <remote_url> <repo_path>`
- **Local only (💾):** Dashboard offers "Push to Remote" if developer configures a remote URL
- **Out of sync (☁↕):** Dashboard shows ahead/behind counts and offers "Pull" / "Push" buttons
- **In sync (☁✓):** Ready to work, no action needed

## Session Isolation

When the runtime spawns Claude Code for project A, it must not bleed context into project B:

| Concern | Isolation Method |
|---------|-----------------|
| Git state | Separate worktree dirs per project (`/tmp/hth-worktrees/<project-id>/`) |
| Environment | Each project loads its own `.env` — different API keys possible |
| Specs | Scanned from each project's `specs/` directory |
| Tasks | `tasks.project_id` foreign key — queue is per-project |
| Claude sessions | `cwd` set to project's worktree, CLAUDE.md from that repo |
| Adversarial review | Runs in project's worktree with project's credentials |
| Results | Scoped by project_id — dashboard filters by selected project |

## Concurrent Runs

Two projects can run simultaneously if the MacStudio has capacity. The runtime server manages this:

- Each project gets its own `RuntimeServer` instance (or the server is parameterized by project)
- `_run_task` becomes a dict of `{project_id: asyncio.Task}`
- The "already running" check is per-project, not global
- WebSocket events include `project_id` so the frontend filters correctly

## Project Registration

There are three ways to get a project into the dashboard:

### 1. Add an Existing Local Project

```bash
# CLI
platform project add --name "AI Dev Framework" --path /path/to/your-project

# Dashboard: Settings > Add Project > Browse Local Path
```

Detects remote URL automatically from `git remote -v`. Sets status to 💾 or ☁✓ accordingly.

### 2. Clone a Remote Project

```bash
# CLI
platform project clone --name "Golf Planner" --url git@github.com:hjalti/golf-trip-planner.git

# Dashboard: Settings > Add Project > Clone from Remote > paste URL
```

Clones to a default workspace directory (e.g. `~/code/<name>/`), registers, and sets status to ☁✓.

### 3. Start a Brand New Project

```bash
# CLI
platform project new --name "My New Idea"

# Dashboard: Settings > Add Project > Start New Project > enter name
```

This creates:
- A new directory at the workspace root (`~/code/my-new-idea/`)
- `git init`
- A `specs/` directory with a single `001-vision.md` containing an empty vision template:

```markdown
# 001: Vision

**Status:** draft

## Goal

<!-- What is this project? What problem does it solve? Write your vision here. -->

## Done When
- [ ] Vision is written and committed
```

- A `CLAUDE.md` with the standard project preamble
- An initial commit: `"Initial commit: empty vision spec"`
- Registers the project in the dashboard with status ✦

The developer's first action is to fill in the vision spec — then the normal spec-driven workflow takes over.

## Project Schema

Projects are stored in PostgreSQL:

```sql
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    repo_path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    base_branch TEXT DEFAULT 'main',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Add project_id to existing tables
ALTER TABLE tasks ADD COLUMN project_id INTEGER REFERENCES projects(id);
ALTER TABLE runs ADD COLUMN project_id INTEGER REFERENCES projects(id);
ALTER TABLE results ADD COLUMN project_id INTEGER REFERENCES projects(id);
```

Sync status (local_exists, remote_exists, ahead/behind) is computed live — not stored — since it changes with every push/pull.

## Frontend Changes

- Project selector dropdown in the header (between title and connection status)
- Each project entry shows its sync status icon (☁✓, ☁, 💾, etc.)
- Selecting a cloud-only project prompts "Clone to local?" before enabling work
- All API calls include `?project=<id>` query parameter
- Selected project persisted in localStorage
- Queue view scans specs from the selected project's repo
- "Add Project" menu with three options: Add Local, Clone Remote, Start New
- Sync action buttons (Clone, Pull, Push) shown contextually based on project state

## Prerequisites
- spec:015 (Dashboard) — the thing being extended
- spec:014 (Autonomous Runtime) — must support project parameterization

## Done When
- [x] Projects table exists in PostgreSQL with CRUD endpoints
- [x] Dashboard header has a project selector dropdown with sync status icons per project
- [x] Sync status is computed live: checks local path exists, remote reachable, ahead/behind counts
- [x] Cloud-only projects (☁) can be cloned to local from the dashboard
- [x] Local-only projects (💾) can be registered via CLI or dashboard
- [x] "Start New Project" creates a git repo with an empty `specs/001-vision.md` and `CLAUDE.md`
- [x] All views (Queue, Live, Results, History) are scoped to the selected project
- [x] Specs are loaded from the selected project's repo path
- [x] Runtime spawns Claude Code with `cwd` set to the correct project's worktree
- [ ] Two projects can be queued and run without interfering (different worktrees, different branches)
- [ ] WebSocket events include project_id; frontend filters by selected project
- [x] `platform project add`, `platform project clone`, and `platform project new` CLI commands work
- [x] Dashboard startup auto-discovers all GitHub repos (via API) and local workspace repos, registers new ones
- [ ] "Add Project" UI in the dashboard — buttons/form for Add Local, Clone Remote, Start New (backend endpoints exist, frontend missing)
- [x] Cloud-only projects show "Not synced locally" with Clone & Sync button instead of empty specs
- [x] Selecting a cloud-only project and cloning it updates the view to show specs without page reload
