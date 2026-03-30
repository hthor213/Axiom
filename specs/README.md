# Specs

Feature specs live here. They define **what** we're building and **when it's done** — before implementation starts.

## Band Numbering

`{NNN}-{slug}.md` — band-based numbering, kebab-case slug.

| Band      | Purpose                                      |
|-----------|----------------------------------------------|
| 000       | Vision — singleton north-star document        |
| 001-009   | Foundation — building blocks everything needs |
| 010-099   | MVP — first usable capabilities               |
| 100-199   | V1 — next expansion                          |
| 200-299   | V2 — and so on per major version              |
| 900-999   | Backlog/ideas — uncommitted explorations      |

### Subsystem bands

When a feature area grows to 3+ specs, promote it to a subsystem band:
- `X00` = subsystem vision (e.g., `150-runtime-vision.md`)
- `X01-X09` = implementation specs within that subsystem

Subsystem bands nest inside the version range they belong to.

### 900-series rules

- 9XX specs are ideas/explorations with no commitment
- To promote: assign a real number in the appropriate band, update INDEX.md
- The old 9XX file becomes a one-line redirect: `Promoted to spec:NNN`
- Unpromoted 9XX specs can be deleted without ceremony

## Tiers

### Tier 1 — Quick Spec

Bug fixes, cleanup, <2hr work. Minimal structure:

```markdown
# NNN: Title

**Status:** draft | active | done

## Problem
What's wrong or missing.

## Approach
How we'll fix it.

## Done When
- [ ] Verifiable criterion (DB query, curl, file check)
```

### Tier 2 — Full Spec

Features, pipelines, UI work. More structure:

```markdown
# NNN: Title

**Status:** draft | active | done

## Goal
What we're building and why. Reference product vision if relevant.

## Inputs
Data sources, tables, APIs.

## Outputs
Endpoints, UI pages, DB changes.

## Key Decisions
Trade-offs and why.

## Edge Cases
Boundary conditions.

## Done When
- [ ] Verifiable criterion
```

## Rules

1. **"Done When" written first** — it defines the work
2. **Items must be verifiable** — queries, commands, checks. Not subjective ("feels good")
3. **Under 60 lines** — if longer, split into multiple specs
4. **Specs say WHAT, not HOW** — implementation details belong in code
5. **Trivial tasks skip specs** — typo fixes, one-liner changes don't need a spec
6. **Cross-reference in BACKLOG.md** — use `-> spec:NNN` to link backlog items to specs
7. **New specs get a band number** — foundation (001-009), MVP (010-099), or backlog (900+). See Band Numbering above.

## Status Flow

`draft` -> `active` -> `done`

- **draft**: Written, not yet started
- **active**: Implementation in progress
- **done**: All "Done When" items verified (checked by `/checkpoint`)

## Integration

- `/start` scans for active specs and reports their status
- `/checkpoint` verifies "Done When" items and marks specs done
- `/refresh` notes active spec in LAST_SESSION.md
- BACKLOG.md links items to specs via `-> spec:NNN`
- CURRENT_TASKS.md tracks the active sprint
- INDEX.md groups specs by topic — updated when specs are created or promoted
