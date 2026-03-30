# 010: Deterministic Harness

**Status:** draft

## Goal

Add a deterministic execution layer that prevents session drift by enforcing state transitions, validating spec completion, and providing termination conditions. The harness is the referee — skills remain the LLM's playbook, the harness validates that the rules are followed. Motivated by Arnar Hrafnkelsson's insight that the agentic harness (runtime with state management and execution loops) matters more than rigid protocols.

## Inputs
- Spec markdown files (specs/*.md) with "Done When" checklists
- Session state files (CURRENT_TASKS.md, BACKLOG.md, LAST_SESSION.md)
- Git state (branch, status)

## Outputs
- `lib/python/harness/` — Python module with state machine, spec parser, gate checks, termination evaluation
- `cli/commands/harness.py` — CLI subcommands: start, status, check, gate
- `.harness.json` — Ephemeral session state file (gitignored)
- Updated shared preamble with Harness Protocol section

## Key Decisions
- JSON over SQLite for state (LLM-readable, no deps)
- Gate checks are "required" vs "advisory" — start all as advisory, promote as confidence grows
- Judgment-type Done When items stay LLM-driven — only automate what's deterministic
- Harness wraps skills, doesn't replace them

## Edge Cases
- Missing specs/ directory — harness operates in degraded mode, reports warnings
- Done When items that look automatable but aren't — classification errs toward "judgment"
- Multiple active specs — harness tracks all, gates evaluate per-spec
- Mid-session crash — .harness.json may be stale, load_state handles gracefully

## Done When
- [x] `hth-platform harness start` initializes .harness.json with STARTED phase
- [x] `hth-platform harness check` runs against specs/003 and reports pass/fail per Done When item
- [x] `hth-platform harness status` shows session phase and active specs
- [x] `hth-platform harness gate checkpoint` validates session state
- [x] lib/python/harness/ contains: __init__.py, state.py, parser.py, spec_check.py, gates.py, termination.py (+ 12 additional modules)
- [x] .harness.json is in .gitignore
- [x] specs/000 vision spec references harness as core capability
- [x] specs/000 vision spec contains Influences & Prior Art section crediting Arnar
