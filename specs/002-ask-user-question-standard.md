# 002: AskUserQuestion Standard

**Status:** draft

## Problem

No standard format for how skills and agents ask the user questions. Questions lack context (user may not have looked in 20 minutes), recommendations, or structured options. This makes async collaboration harder.

## Approach

Define a standard AskUserQuestion format and add it to all skills via the shared preamble (-> spec:001). Adapted from gstack's approach but enhanced with spec-awareness.

**Format:**
1. **Re-ground**: State the project, branch, current task (1-2 sentences)
2. **Simplify**: Plain English a smart 16-year-old could follow
3. **Recommend**: "RECOMMENDATION: Choose [X] because [reason]"
4. **Options**: Lettered options A) B) C) with effort estimates
5. **Spec reference**: If relevant, cite `specs/NNN` constraints that affect the decision

## Done When

- [x] Format documented in shared preamble (`~/.claude/skills/shared/preamble.md`) -> spec:001
- [x] All 4 global skills (start, checkpoint, refresh, macstudio) reference the preamble
- [x] At least 2 agents (maestro, analyst) reference the preamble
- [x] One real question from a skill demonstrates the format correctly (legacy migration prompt in /start)
