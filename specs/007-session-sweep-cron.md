# 007: Session Hygiene Crons

**Status:** draft

## Problem

Decisions, constraints, and invariants emerge during conversation but aren't always captured in specs. Sessions run long without checkpoints. Spec drift goes unnoticed until /checkpoint.

## Approach

Three session-scoped crons (via CronCreate) set up by /start. All session-only (gone when Claude exits), fire when REPL idle.

1. **Checkpoint nudge** (~60 min) — remind user to /checkpoint or /refresh
2. **Spec sweep** (~23 min) — flag unanchored decisions/constraints for promotion to specs
3. **Drift check** (~37 min) — compare recent work against active spec's Done When criteria

/start gains a new step: "Set up session crons" after situational awareness.

## Done When

- [x] /start skill has a "Session crons" step that creates 3 CronCreate jobs
- [ ] Checkpoint nudge fires with actionable prompt (needs live test)
- [ ] Spec sweep fires and reviews for unanchored decisions (needs live test)
- [x] Drift check fires and compares against active spec (verified 2026-03-18)
- [x] All crons use off-minute scheduling (not :00 or :30)
- [x] INDEX.md updated with this spec
