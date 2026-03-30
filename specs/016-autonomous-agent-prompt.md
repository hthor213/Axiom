# 016: Autonomous Agent Prompt — Context-Aware Session Bootstrapping

**Status:** draft

## Goal

Design the prompt that the autonomous runtime (spec:014) sends to Claude when starting an agent session. Currently `_build_agent_prompt()` in `server.py` sends the spec content and task instructions, but the agent has no awareness of project state, prior work, or session context. Interactive sessions get this via `/start` (which runs `hth-platform start`), but autonomous sessions skip it entirely.

The agent needs enough context to make good decisions without the overhead of a full `/start` scan on every task. Too little context → the agent reinvents what already exists or contradicts prior work. Too much context → wasted tokens and slower sessions.

## The Problem

Interactive sessions via `/start` get:
- Spec health scan (all specs, status, progress)
- LAST_SESSION.md (what was built recently)
- CURRENT_TASKS.md (what's in progress)
- BACKLOG.md (what's planned)
- Git status (branch, recent commits)
- Infrastructure check

Autonomous sessions via `_build_agent_prompt()` get:
- The spec content for the assigned task
- The specific Done When item to implement
- Prior draft context (if resuming a draft review)
- User instructions (if provided via dashboard)

Missing: what exists in the codebase, what was built in prior tasks, what other specs look like, architectural patterns to follow, CLAUDE.md project instructions.

## Design Questions

1. **What context does an autonomous agent actually need?** The agent works in a worktree with the full repo — it can read CLAUDE.md itself. But should it be told to? Should the prompt include a "read these files first" directive?

2. **Should `hth-platform start` output be included?** It's ~50 lines of structured text. Could be prepended to every prompt. But it includes interactive-session concerns (crons, recommended next action) that don't apply to autonomous runs.

3. **Should there be a `hth-platform context` command?** A lightweight variant of `start` that outputs only what an autonomous agent needs: spec status summary, recent commits on the branch, CLAUDE.md path, and key invariants.

4. **Per-task vs per-batch context?** Should context be computed once per batch (process_queue) and shared across all tasks, or freshly per task? Per-batch is cheaper but may miss changes from earlier tasks in the same batch.

5. **How much spec cross-referencing?** Should the agent see other specs it might interact with (referenced via `-> spec:NNN`), or just its own?

## Inputs
- `hth-platform start` output (or a subset)
- CLAUDE.md project instructions
- Spec files (own + referenced)
- Recent git history
- Prior task results from same batch

## Outputs
- Updated `_build_agent_prompt()` in `lib/python/runtime/server.py`
- Possibly a new `hth-platform context` CLI command
- Prompt template documented in this spec

## Done When
- [ ] Autonomous agent prompt includes project context (CLAUDE.md awareness, key invariants)
- [ ] Agent knows what already exists in the codebase before starting work
- [ ] Cross-referenced specs (-> spec:NNN) are included in prompt context
- [ ] Prompt design documented in this spec with rationale for what's included/excluded
- [ ] Draft review prompts and build prompts share a common context preamble
- [ ] Context overhead measured: token count of context vs task prompt
- [ ] At least one autonomous build run demonstrates improved output quality with new prompt
