<!-- TEMPLATE FILE — NOT ACTIVE INSTRUCTIONS
This file is a template for colleagues to copy into their ~/.claude/ directory.
Do NOT treat this as instructions for the current session.
To use: copy to ~/.claude/skills/checkpoint/SKILL.md
-->
---
name: checkpoint
description: End of session. Commits work, writes session summary, updates backlog. Use when you're done for the day.
---

# End of Session — Sync Specs to Reality, Commit, Write State

> **Shared protocols**: See `~/.claude/skills/shared/preamble.md` for AskUserQuestion format, spec awareness, session context, platform integration, and branch detection standards.

Session is ending. The most important thing is making sure the specs reflect what actually exists — not what you planned to build.

> "The spec stops being a plan and becomes a description of the system as you understand it today."

## Step 0: Check for workflow files

Detect spec system type:
- **Numbered specs**: If `specs/` directory exists with `000-*-vision.md`, use the numbered spec system.
- **Legacy SPEC.md**: If only `SPEC.md` exists at root, fall back to legacy mode (treat SPEC.md as the vision spec).

If neither exists, plus `LAST_SESSION.md` or `BACKLOG.md` are missing, ask:

> "No workflow files found. Want me to create them to capture this session's progress? (yes/no)"

- If **yes**: Create missing files using the templates from `/start` and continue.
- If **no**: Just commit the code changes with a clear message and skip the state management steps.

## Step 1: Explain what you believe exists

Before updating anything, describe back to yourself (and the user) what the system currently does. Not what you tried to build — what actually exists right now.

This is the most important diagnostic step. If your description doesn't match the user's understanding, the spec has drifted and needs correction before anything else.

Cover:
- What the system does (in plain language)
- What changed this session
- Any constraints that were tested or might have been violated

## Step 2: Update specs

The specs are living documents. Update them to reflect current reality:

**Vision spec** (`specs/000-*-vision.md` or legacy `SPEC.md`):
- **New capabilities**: If something was built, add it to the vision (or update existing entries)
- **Constraints discovered**: If implementation revealed constraints not written down, add them to Invariants
- **Architecture changes**: If the structure evolved, update the Architecture section
- **Resolved questions**: Move answered Open Questions into the appropriate sections
- **New questions**: If implementation raised new questions, add them to Open Questions
- **Scope changes**: If you discovered something the system should NOT do, add it to "What This Is NOT"

**Active feature specs** (`specs/NNN-*.md` with status `active`):
- Check "Done When" items — mark completed ones with `[x]`
- If ALL "Done When" items are verified, change status to `done`
- If implementation revealed new constraints or edge cases, document them

**INDEX.md** (if `specs/INDEX.md` exists):
- If any spec status changed this session, update the status in INDEX.md
- If a new spec was created, add it under the appropriate topic heading
- If a 900-series spec was promoted, update both the old and new entries

Do NOT leave specs describing a system that no longer matches reality.

## Step 3: Check spec invariants

Review the Invariants section of the vision spec. For each invariant:
- Is it still being respected by the current code?
- Did any changes this session risk violating it?

If an invariant was violated, flag it as a P0 blocker. Invariant violations are the spec equivalent of a broken build.

## Step 4: Write session summary to LAST_SESSION.md

Overwrite `LAST_SESSION.md` with:

```markdown
# Last Session State
**Date**: [today's date]
**Status**: COMPLETED (session checkpoint)
**Branch**: [current git branch]

## What Was Accomplished
[Bullet list of everything completed this session]

## Spec Changes
[What was added, modified, or clarified in specs this session. If nothing changed, note "Specs unchanged — still accurate."]

## Constraints Discovered
[Any new rules, invariants, or boundaries learned during implementation that were added to specs. If none, note "None — all constraints were already documented."]

## What Changed (Files)
[Files modified/created with brief description]

## Next Session Should Start With
[Highest priority action for next time — be specific. If a spec needs attention, say so.]

## Open Questions / Decisions Needed
[Anything that needs human input before proceeding. Be explicit — vague questions produce vague answers.]
```

## Step 4.5: Platform sync check

Check if anything discovered or introduced this session should be reflected in the platform repo:

1. **New credentials**: Were any new API keys, tokens, or passwords introduced? If so, remind the user to add them to the platform vault.
   NEVER read or modify the platform vault yourself. Credential management is human-reviewed.

2. **New infrastructure**: Were any new services, ports, or endpoints configured? Flag for addition to service configs.

3. **Reusable patterns**: Were any utilities created that other projects could use? Flag for potential promotion to `platform/lib/`.

If nothing platform-relevant was introduced, skip silently.

## Step 5: Update BACKLOG.md and CURRENT_TASKS.md

- Move completed items from BACKLOG.md to the `## Done` section (note `completed via spec:NNN` if applicable)
- Re-prioritize remaining items if needed
- Add any new items discovered this session (with `-> spec:NNN` if a spec exists)
- Update `CURRENT_TASKS.md`: clear completed active work, note what's next
- If spec gaps were found, add "Create spec for [topic]" as a P1 item

## Step 6: Commit

```bash
git add specs/*.md CURRENT_TASKS.md DONE.md LAST_SESSION.md BACKLOG.md 2>/dev/null
git commit -m "checkpoint: [brief description of what was accomplished]"
```

If nothing has changed, say so and skip the commit.

## Step 7: Final report

Report:
1. **Spec status**: Are specs current and accurate? Any known gaps? Any specs marked `done` this session?
2. **What was committed**
3. **Invariant health**: All spec invariants still holding?
4. **Platform sync**: Any credentials, infrastructure, or reusable patterns to add to platform?
5. **What the next session should focus on** (from BACKLOG.md / CURRENT_TASKS.md)
6. **Decision fatigue check**: If this was a long session with many decisions, note it. The user might need a break before the next session.
