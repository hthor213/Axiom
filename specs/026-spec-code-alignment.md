# 026: Ground Truth & Oversight — Dashboard Reflects Reality

**Status:** active

## Goal

The dashboard should always reflect reality — what's been developed, what's been deployed, and what remains — regardless of where work happened. Today the dashboard only knows about work that flowed through its Build pipeline. The harness reads spec files and reports "22/29 done" but the dashboard shows "nothing started." This spec closes that gap.

The core problem: two independent tracking systems with no sync. The harness reads spec markdown checkboxes (source of truth for progress). The dashboard database tracks tasks created via the Build button. Work done locally in Claude Code, manually, or in any other tool is invisible to the dashboard.

## Architecture

### Phase 1 — Ground Truth Scan + Health Tab (deterministic)

A new Health tab in the dashboard that surfaces the project's actual state. No LLM calls.

**Ground truth comparison**: A new `ground_truth.py` module takes the spec-file state (from `scanner.scan_specs()`) and the dashboard's task records, then produces a `GroundTruthReport` showing per-spec: what the spec file says is done vs what the dashboard tracked.

**API endpoints**:
- `GET /health/ground-truth` — per-spec comparison with mismatches identified
- `GET /health/drift` — wraps existing `drift.check_alignment()` for stale specs, regressions, uncovered directories

**Health tab** (6th nav tab): shows each spec with "Spec says X/Y" vs "Dashboard tracked Z", drift signals with severity badges, scan timestamp, and a refresh button.

### Phase 2 — Bootstrap (CLI) + Sync (Dashboard)

Two mechanisms to bring the dashboard in sync with reality:

**Bootstrap** (`hth-platform bootstrap`): One-time CLI command. Reads all spec files, finds checked Done When items with no corresponding dashboard record, creates `imported` records. Run once to bring the DB in sync.

**Sync** (dashboard button): Ongoing mechanism on the Health tab. `POST /health/sync` re-scans spec files, detects newly checked items or untracked commits, imports them. Can chain with Pull (Pull → Sync). Compares `git log` on main against task records to flag commits that touched spec-related files without a dashboard task.

Imported records use a distinct `imported` status — they are not fake pipeline tasks.

### Phase 3 — Deployment Status

The dashboard and runtime run as Docker containers on MacStudio. This phase tracks whether what's deployed matches what's in the repo.

**Build-time commit**: The dashboard tmux session exports `GIT_COMMIT=$(git rev-parse HEAD)` on startup. Each service self-reports its deployed commit.

**Code lifecycle is three states**: synced (imported from spec files via bootstrap/sync), merged (approved into main), deployed (merge commit is ancestor of running `GIT_COMMIT`, verified via `git merge-base --is-ancestor`). "Merged" and "deployed" are distinct — code can be on main but not yet running on the server.

**API endpoint**: `GET /health/deployment` returns each container's deployed commit vs latest main, with a count of how many commits behind.

**Health tab integration**: Deployment freshness — green (up to date), yellow (1-5 commits behind), red (6+ behind or unknown).

### Phase 4 — Semantic Alignment (LLM-assisted)

Code inventory and semantic drift detection. Deterministic code scanning with LLM judgment for the "does this match the spec's intent?" question.

**Code inventory** (`inventory.py`): Parse CLI commands from Click groups, API endpoints from FastAPI decorators, harness module public functions. Cross-reference against spec Done When items and body text.

**Semantic checks**: For active/done specs, ask an LLM to identify features beyond spec scope, unmet requirements, and implementation choices that shifted intent.

**Report**: Four categories — uncovered (code with no spec), scope-drift (code exceeds spec), incomplete (spec exceeds code), stale-spec (spec describes removed code). Integrated with `hth-platform drift --deep`.

## Discrepancy Categories (Phase 4)

| Category | Meaning | Example |
|----------|---------|---------|
| **uncovered** | Code feature exists with no spec backing | API endpoint no spec mentions |
| **scope-drift** | Spec says X, code does X + Y | Spec says "find printers," code finds all accessories |
| **incomplete** | Spec says X, code does X - 1 | 5 Done When items, only 3 met |
| **stale-spec** | Spec describes something the code moved past | Spec references a refactored-away module |

## Key Decisions

- **Health tab is additive** — Queue/Live/Review/Results/History remain unchanged
- **Imported records, not fake tasks** — bootstrap/sync creates records with `imported` status, not pretend-passed pipeline tasks
- **Bootstrap = CLI one-time, Sync = dashboard ongoing** — different processes for different needs. Sync can chain with Pull.
- **Commit SHA baked at build time** — no SSH needed for deployment status. Container self-reports.
- **Report, don't fix** — This is an audit/oversight tool. Humans decide what to act on.
- **LLM for semantics only (Phase 4)** — code inventory and cross-referencing is deterministic Python
- **Scanner/drift modules reused as-is** — existing harness code is imported, not duplicated

## Prerequisites

- spec:015 (Dashboard) — UI home
- spec:025 (Dashboard Queue Redesign) — task infrastructure, `GET /specs` endpoint

## Done When

### Phase 1: Ground Truth + Health Tab
- [x] `GET /health/ground-truth` returns per-spec comparison: spec-file checked items vs dashboard task records, with mismatches identified
- [x] Health tab shows each spec with "Spec says X/Y done" vs "Dashboard tracked Z" — mismatches highlighted
- [x] Health tab integrates drift signals (stale specs, done regressions, uncovered directories)
- [x] Health tab loads on click with refresh button and scan timestamp

### Phase 2: Bootstrap + Sync
- [x] `hth-platform bootstrap` imports all checked Done When items as `imported` records, bringing DB in sync with spec reality (one-time)
- [ ] Bootstrap is idempotent — running twice creates no duplicates
- [x] "Sync" button on Health tab re-scans specs and imports newly completed items (ongoing, can chain with Pull)
- [ ] Sync flags commits on main that modified spec-tracked files but have no dashboard task
- [ ] After bootstrap/sync, Health tab shows true completion state (e.g., 22/29) instead of 0/29

### Phase 3: Deployment Status
- [x] Dashboard startup exports `GIT_COMMIT` env var (tmux session on MacStudio)
- [x] `GET /health/deployment` returns each container's deployed commit vs latest main
- [x] The dashboard accurately reflects "deployed" when latest repo code matches what's running on MacStudio (spliffdonk.com)
- [x] Deployment status degrades gracefully when `GIT_COMMIT` is missing

### Phase 4: Semantic Alignment
- [ ] `hth-platform drift --deep` produces a code inventory (CLI commands, API endpoints, harness modules)
- [ ] Inventory items cross-referenced against spec Done When items
- [ ] Uncovered code features flagged in report
- [ ] LLM semantic check identifies scope drift between spec intent and code
- [ ] Report uses four categories: uncovered, scope-drift, incomplete, stale-spec
- [ ] Existing `drift` command (without flags) unaffected
