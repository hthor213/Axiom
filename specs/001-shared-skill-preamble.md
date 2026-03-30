# 001: Shared Skill Preamble

**Status:** draft

## Problem

Common patterns are duplicated across skills: spec awareness, session context checks, question format, platform integration. Changes to these patterns require updating every skill individually.

## Approach

Create `~/.claude/skills/shared/preamble.md` containing common patterns that all skills reference. Contents:

1. **AskUserQuestion format** (from -> spec:002)
2. **Spec awareness protocol**: Read `specs/000-*-vision.md` before suggesting approaches; scan for active specs
3. **Session context check**: Read LAST_SESSION.md for where we left off
4. **Platform integration**: Check `.env.platform`, report credential status (from existing platform awareness in skills)
5. **Branch detection**: Determine base branch for git operations

Skills reference it with: "See `~/.claude/skills/shared/preamble.md` for standard protocols."

## Done When

- [x] `~/.claude/skills/shared/preamble.md` exists with all 5 sections
- [x] AskUserQuestion standard from spec:002 is included
- [x] All 4+ global skills reference the preamble (start, checkpoint, refresh, macstudio)
- [x] At least 2 agents reference the preamble (maestro, analyst)
