# 004: /review Skill

**Status:** draft

## Goal

Create a pre-landing PR review skill with a structured 3-pass checklist. Pass 3 (spec alignment) is our key differentiator — it checks code against the *defined intent* in specs, not just general best practices.

## Inputs

- Git diff (staged and/or branch diff vs base)
- `specs/*.md` — active specs with "Done When" criteria
- `specs/000-*-vision.md` — invariants and constraints

## Outputs

- Pass/fail per category with specific findings
- Spec alignment report: does the diff match what specs say should exist?
- Actionable fix suggestions

## Key Decisions

- 3-pass structure (not 2 like gstack) — Pass 3 is spec-specific
- Runs locally, no external service dependency
- Can be invoked standalone or as part of `/ship`

## Done When

- [ ] `/review` skill exists at `~/.claude/skills/review/SKILL.md`
- [ ] Pass 1 (Critical): SQL/data safety, auth bypass, race conditions, LLM trust boundaries
- [ ] Pass 2 (Structural): Dead code, magic numbers, missing error handling, test gaps
- [ ] Pass 3 (Spec alignment): Code matches active specs, invariants respected, new capabilities documented
- [ ] Running `/review` on a branch with changes produces a structured report
- [ ] Maestro Job 3 includes review gate that invokes this skill (-> spec in maestro update)
