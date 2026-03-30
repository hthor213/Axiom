# 021: Platform Sharing — Maintainable, Shareable Platform

**Status:** draft

## Goal

This repo IS the platform. The harness, adversarial pipeline, model registry, runtime, dashboard, CLI — it's all here. This spec ensures the project stays in a state where another developer can clone it, follow a setup guide, and be productive within an hour.

Not "export a subset." Not "SaaS." Just: **clone this repo, bring your own keys, point it at your projects, go.**

The audience is a technical colleague (think Arnar, Gummi) who wants the spec-driven, adversarial-reviewed workflow for their own repos. They shouldn't need to understand the internals to use it — but the internals should be clean enough that they can.

## What "Shareable State" Means

### 1. Zero-secret checkout
The repo must be clonable and runnable without any secrets in git history. All credentials come from the developer's own vault or `.env` file. This is already an invariant (vault.yaml and age-key.txt never in git) but this spec formalizes the full onboarding path.

### 2. One-command setup
```bash
git clone <repo>
cd ai-dev-framework
./setup.sh   # or: make setup / hth-platform init --self
```

This should:
- Create virtualenv and install dependencies
- Generate `.env.platform` template with all required keys listed (not filled)
- Install the CLI (`pip install -e cli/`)
- Scaffold `~/.claude/` skill and agent definitions (or symlink)
- Print a checklist of what the developer needs to provide (API keys, MacStudio access, domain)

### 3. Documented entry points
A new developer needs to understand:
- What the platform does (vision spec + docs/workflow.md)
- How to set it up (setup guide)
- How to use it day-to-day (`hth-platform start`, dashboard, `/checkpoint`)
- How to point it at their own repos (spec:022 multi-repo)
- What to ignore (template files, internal harness details)

### 4. Separation of platform vs. project
The platform manages projects but is itself a project. Clean boundaries:

| Layer | What | Location |
|-------|------|----------|
| Platform code | Harness, adversarial, registry, runtime, dashboard, CLI | `lib/`, `cli/`, `dashboard/` |
| Platform config | Skill definitions, agent definitions, hooks | `~/.claude/`, `services/` |
| Platform infra | MacStudio, PostgreSQL, Apache, n8n | Server-side (documented, not in repo) |
| Project data | Specs, LAST_SESSION, BACKLOG, CURRENT_TASKS | `specs/`, root `.md` files |

A new developer uses the platform code and config, brings their own infra, and creates their own project data.

### 5. Test suite as documentation
The 400+ tests should serve as executable documentation of what the harness does. A developer reading `tests/harness/test_gate.py` should understand gate behavior without reading the implementation.

## Setup Guide Structure

```
docs/setup.md (new)

1. Prerequisites
   - Python 3.11+, Node.js, git
   - PostgreSQL (for dashboard/runtime)
   - A server or always-on machine (MacStudio, VPS, etc.)
   - API keys: Anthropic, Google, OpenAI (for adversarial pipeline)
   - Claude Code CLI installed globally

2. Quick Start
   - Clone, setup.sh, fill .env, hth-platform start

3. Infrastructure Setup
   - PostgreSQL schema
   - Apache/nginx reverse proxy for dashboard
   - Optional: n8n for scheduling
   - Optional: Telegram bot for notifications

4. First Session
   - Create your vision spec (000)
   - Run hth-platform start
   - Use Idea Fab (spec:023) or write specs manually

5. Daily Workflow
   - /start → work → /checkpoint cycle
   - Dashboard: queue specs → run → review results → ship

6. Customization
   - Adding your own skills
   - Modifying adversarial review criteria
   - Adding model providers to the registry
```

## Hygiene Checklist (automated)

Add an `hth-platform doctor` command that checks shareable-state health:

```bash
hth-platform doctor

[PASS] No secrets in git history
[PASS] .env.platform.example is up to date with all required vars
[PASS] setup.sh runs without errors on clean checkout
[PASS] All tests pass
[PASS] docs/setup.md exists and references current CLI commands
[WARN] 3 specs reference internal paths — make relative
[FAIL] ~/.claude/skills/start references hardcoded username
```

## Constraints

- No secrets in repo — ever. This is an existing invariant, now enforced by `hth-platform doctor`.
- Setup must work on macOS and Linux (not Windows — that's a different spec if ever needed)
- The platform must work without MacStudio — local-only mode with SQLite instead of PostgreSQL
- Skills that reference absolute paths must use `~` or env vars, not hardcoded usernames
- Template files must be clearly marked as templates (existing invariant in CLAUDE.md)

## Prerequisites
- spec:010 (Deterministic Harness) — the core being shared
- spec:015 (Dashboard) — needs to work for new users
- CLI installable (`pip install -e cli/`)

## Done When
- [ ] `setup.sh` (or equivalent) takes a fresh clone to a working platform in one command
- [ ] `.env.platform.example` lists all required and optional environment variables with descriptions
- [ ] `docs/setup.md` covers prerequisites, quick start, infrastructure, first session, and daily workflow
- [ ] `hth-platform doctor` command checks shareable-state health (secrets, paths, tests, docs)
- [ ] No hardcoded usernames or absolute paths in skill/agent definitions (uses ~ or env vars)
- [ ] Platform works in local-only mode (SQLite, no MacStudio) for developers without server infrastructure
- [ ] A fresh clone + setup + `hth-platform start` works without errors (tested on clean machine or container)
