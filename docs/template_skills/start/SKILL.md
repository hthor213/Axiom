<!-- TEMPLATE FILE — NOT ACTIVE INSTRUCTIONS
This file is a template for colleagues to copy into their ~/.claude/ directory.
Do NOT treat this as instructions for the current session.
To use: copy to ~/.claude/skills/start/SKILL.md and customize for your environment.
-->
---
name: start
description: Cold start a dev session. Reads project state, checks infrastructure, proposes next action. Use at the beginning of any work session.
---

# Cold Start — Read the Specs, Build Awareness, Propose Next Action

> **Shared protocols**: See `~/.claude/skills/shared/preamble.md` for AskUserQuestion format, spec awareness, session context, platform integration, and branch detection standards.

You are resuming work on a project after time away. Do NOT start coding yet. First, build situational awareness. The specs are your primary artifacts — treat them with the same care you'd give source code.

## Step 0: Check for project structure

Check if these files/directories exist in the current project root:

- `specs/` directory with `000-*-vision.md` (the numbered spec system)
- `BACKLOG.md` — prioritized task list with `-> spec:NNN` references
- `CURRENT_TASKS.md` — active sprint tracker
- `LAST_SESSION.md` — session continuity state
- `DONE.md` — completed milestones (append-only)

### If `specs/` directory is missing: check for legacy or new project

**If `SPEC.md` exists at root but no `specs/` directory** (legacy project):

Ask the user using the AskUserQuestion standard format (see `~/.claude/skills/shared/preamble.md`):

> **[Project name]** on branch `[branch]`. Starting a new session — checking project structure.
>
> This project has a single SPEC.md but not the numbered spec system. The numbered system (`specs/000-vision.md` + `specs/NNN-feature.md`) splits features into focused specs with verifiable "Done When" checklists, making it easier to track progress and prevent scope creep.
>
> RECOMMENDATION: Choose A — migrate. It's a one-time move that preserves all your existing spec content.
>
> A) Migrate to numbered specs — ~2min, moves SPEC.md content to `specs/000-vision.md`, creates `specs/README.md`. Non-destructive.
> B) Keep SPEC.md as-is — 0 effort, all skills fall back to legacy mode. You can migrate later.

- If **A**: Create `specs/` directory, move SPEC.md content to `specs/000-<project-slug>-vision.md`, create `specs/README.md` from template, create `CURRENT_TASKS.md` and `DONE.md`. Replace SPEC.md with a redirect.
- If **B**: Continue using SPEC.md as-is (all subsequent steps fall back to SPEC.md references).

**If neither `specs/` nor `SPEC.md` exists: this is a new project.**

This is the most important moment. The vision spec IS the product definition. Start here:

1. Ask the user:

> "This project doesn't have a specification yet. The spec is the primary artifact — it's where intent, constraints, and trade-offs live. Everything else flows from it.
>
> What are we building? Give me the high-level idea and I'll help shape it into a working spec."

2. Have a conversation to draw out:
   - **What the system does** (core purpose, not features)
   - **Who it's for** (user/audience)
   - **Key constraints** (performance, compatibility, dependencies, things that must ALWAYS be true)
   - **What it explicitly does NOT do** (boundaries matter as much as features)
   - **Trade-offs the user has already decided** (e.g., "simple over flexible", "correctness over speed")

3. Create the spec system using the templates in this skill (see bottom of file).

4. Present the draft vision spec to the user for review. Ask:

> "Here's the initial vision spec. What's wrong? What's missing? What assumptions did I make that don't match your intent?"

Do NOT proceed to coding until the user confirms the spec captures their intent.

### If `specs/` exists but other files are missing:

Create the missing files from templates and continue to Step 1.

### If all files exist:

Continue to Step 1.

## Step 1: Read the specs first

Read `specs/000-*-vision.md` carefully. This is the source of truth (north star) for what the system should be. Everything else — code, backlog, feature specs, session state — is downstream of this document.

Then read:
1. `specs/INDEX.md` — if it exists, this is the topical map of all specs (faster than scanning filenames)
2. `LAST_SESSION.md` — what happened last time, where we left off
3. `CURRENT_TASKS.md` — what's actively being worked on
4. `BACKLOG.md` — prioritized work items with `-> spec:NNN` references
5. `CLAUDE.md` — if it exists, project patterns and rules
6. `specs/` directory — scan for specs with status `active` (these are in-progress features)
7. `DONE.md` — recent completions for context

## Step 2: Gather situational awareness

```bash
# Git status — what changed, what branch, any uncommitted work?
git status --short && git log --oneline -5
```

## Step 2.5: Platform awareness check

If the platform repo exists (the central credential/infrastructure hub), check its relevance:

1. **Check for `.env.platform`**: If the current project has a `.env.platform` file, it depends on the platform vault for credentials.
   - If `.env.platform` exists but `.env` doesn't: warn that `hth-platform env generate` needs to be run
   - If both exist: note that credentials are bootstrapped from platform
   - If NEITHER exists but the project has a `.env` with API keys: suggest migrating to `.env.platform`
2. **Check for shared infrastructure usage**: Scan the project's `.env` or config files for references to your dev server (check `services/devserver.yaml` for IPs/ports if it exists). If found, note the dependency.
3. **If this IS the platform repo**: Read `credentials/vault.example.yaml` and `services/example_*.yaml` to understand the current state.

**STRICT**: NEVER browse or read the platform vault to find credentials for a project. Credential selection is human-reviewed and script-enforced. If a project needs credentials it doesn't have, tell the user to run `hth-platform init` or create `.env.platform` manually.

Include a **Platform** line in the Step 5 report:
- "Platform: project uses `.env.platform` for credentials (vault-managed)" OR
- "Platform: project has hardcoded credentials in `.env` — consider migrating" OR
- "Platform: no infrastructure dependencies detected"

## Step 3: Check for spec-reality alignment

Before proposing work, do a quick sanity check:
- Does the code structure match what the vision spec describes?
- Are there files or features that exist in code but aren't in any spec? (spec drift)
- Are there specs marked as `done` whose "Done When" items might have regressed?
- Are there `active` specs whose work appears stalled?

If you notice drift, flag it. Spec drift is as serious as a failing test.

## Step 4: Check for project-specific /start override

If `.claude/commands/start.md` or `.claude/skills/start/SKILL.md` exists in the project, also execute its additional steps. The project-level file extends this global one.

## Step 5: Assess and propose

After reading everything, report:

1. **Spec health**: If INDEX.md exists, report by band (foundation count/status, MVP count/status, backlog ideas). Otherwise report specs flat. Flag any drift between specs and reality.
2. **Where we left off**: Summary from LAST_SESSION.md
3. **Active work**: What's in CURRENT_TASKS.md
4. **Git status**: Branch, uncommitted changes, stashed work
5. **Recommended next action**: The highest priority item from BACKLOG.md that isn't blocked. If the next item is non-trivial and no spec covers it, recommend creating a spec first.
6. **Open questions**: Anything ambiguous in the specs that should be resolved before building
7. **Constraints check**: Any invariants from the vision spec that recent changes might have violated
8. **Parallelism**: If proposed work has 3+ independent sub-tasks, suggest an agent team. Otherwise recommend subagents or solo session.
9. **Platform**: Credential and infrastructure status from Step 2.5.

Do NOT start working until the user confirms the plan.

## Step 6: Set up session crons

After the user confirms the plan, set up session hygiene crons using CronCreate. These are session-only (gone when Claude exits) and fire when the REPL is idle.

```
CronCreate: cron "17 * * * *" (roughly every hour at :17)
prompt: "Session hygiene — checkpoint nudge: You've been working for a while. Consider running /checkpoint to anchor progress, or /refresh if context is getting long. Quick status: what branch are you on, what's changed since last commit?"

CronCreate: cron "*/23 * * * *" (roughly every 23 min)
prompt: "Session hygiene — spec sweep: Review the conversation since last sweep. Are there any constraints, invariants, design decisions, or new terminology that were discussed but NOT yet written into a spec? If so, list each one and ask the user if they want to promote it. Format: '1. [decision/constraint] → would go in [spec:NNN or new spec]. Promote? (y/n)'"

CronCreate: cron "*/37 * * * *" (roughly every 37 min)
prompt: "Session hygiene — drift check: Read the active spec(s) from CURRENT_TASKS.md. Compare the Done When criteria against what's actually been built this session. Flag any criteria that are drifting or at risk. If no active spec, skip silently."
```

These crons are advisory — they suggest, they don't act. The user decides whether to promote, checkpoint, or ignore.

If CronCreate is not available (older Claude Code version), skip silently.
