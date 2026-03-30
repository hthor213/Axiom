<!-- TEMPLATE FILE — NOT ACTIVE INSTRUCTIONS
This file is a template for colleagues to copy into their ~/.claude/ directory.
Do NOT treat this as instructions for the current session.
To use: copy to ~/.claude/skills/refresh/SKILL.md
-->
---
name: refresh
description: Mid-session save point. Writes working state to disk without committing. Use when context is getting long or you feel drift. After this, start a new conversation and run /start.
---

# Mid-Session Refresh — Save State, Sync Specs, Preserve Context

> **Shared protocols**: See `~/.claude/skills/shared/preamble.md` for AskUserQuestion format, spec awareness, session context, platform integration, and branch detection standards.

Context is getting long or you're starting to drift. Before saving, make sure the specs reflect what you've learned so far — discoveries made during implementation are too valuable to lose to a context reset.

> "Speed doesn't prevent mistakes. It industrializes them."
> If you've been moving fast, this is the moment to check whether speed has outpaced clarity.

## Step 0: Check for workflow files

Detect spec system type:
- **Numbered specs**: If `specs/` directory exists with `000-*-vision.md`, use the numbered spec system.
- **Legacy SPEC.md**: If only `SPEC.md` exists at root, fall back to legacy mode.

If neither exists, ask the user:

> "No spec or session state file found. Want me to create them to save your current progress? (yes/no)"

- If **yes**: Create them and continue.
- If **no**: Say "Got it. If you want a clean context, just start a new conversation. Your code changes are still on disk." and stop.

## Step 1: Check spec-reality alignment

Before saving state, verify specs still match reality:

1. **Describe what you believe the system does right now** — not what was planned, what IS.
2. **Compare to vision spec** (`specs/000-*-vision.md`) and any active feature specs — are there gaps? New capabilities not documented? Constraints discovered but not written down?
3. **Flag any drift** — if the system has veered from spec intent, note it explicitly.

## Step 2: Update specs if needed

If implementation revealed new information, update specs NOW, before you lose context:

- **New constraints discovered**: Add to Invariants section of the vision spec.
- **Feature spec progress**: Check "Done When" items on active specs — mark any that are now complete.
- **Architecture shifts**: If the structure changed, update the Architecture section.
- **New questions**: Add to Open Questions rather than leaving ambiguity for the next session.
- **Resolved questions**: Move from Open Questions to the appropriate section.

## Step 3: Write current state to LAST_SESSION.md

Overwrite `LAST_SESSION.md` with:

```markdown
# Last Session State
**Date**: [today's date]
**Status**: IN PROGRESS (mid-session refresh)
**Branch**: [current git branch]

## What I Was Working On
[Specific task/feature in progress. Reference active spec if applicable: -> spec:NNN]

## Spec Alignment
[Are specs current? Note any updates made during this refresh, or any known gaps.]

## What's Done So Far
[Bullet list of completed sub-tasks this session]

## What's NOT Done Yet
[Bullet list of remaining work for current task]

## Constraints Discovered
[Any rules or invariants learned during implementation. These should also be in specs now.]

## Current State of the Code
[Which files are modified and their state — compiles? partial? broken?]

## Key Decisions Made
[Any design decisions that future-you needs to know. These should be in the spec's Trade-offs section too.]

## Next Step (be very specific)
[The EXACT next thing to do. Not "continue working on X" but the specific function, file, and what to do to it. The agent is literal — vague instructions produce vague work.]

## Gotchas / Traps
[Anything that tripped you up or to watch out for. If the agent made wrong assumptions, note what they were and what the correct constraint is.]
```

## Step 3.5: Platform sync note

Quickly check:
- Were any **new credentials** introduced? Note for vault addition.
- Were any **new shared infrastructure patterns** created? Note for potential promotion to `platform/lib/`.

Keep this lightweight — just annotate LAST_SESSION.md so the next session picks it up.

## Step 4: Update BACKLOG.md and CURRENT_TASKS.md if priorities changed

If anything was learned this session that changes priorities, update the relevant items.

## Step 5: Commit session state

```bash
git add specs/*.md LAST_SESSION.md BACKLOG.md CURRENT_TASKS.md DONE.md 2>/dev/null
git commit -m "refresh: save session state and spec updates"
```

Leave all other code changes unstaged on disk.

## Step 6: Confirm

Say exactly:

> "State saved and committed. Specs [are current / have known gaps: _list them_].
> Code changes preserved on disk.
> Start a new conversation and run `/start` to continue with fresh context."

Do NOT continue working after this point.
