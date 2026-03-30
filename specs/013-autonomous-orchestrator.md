# 013: Autonomous Orchestrator

**Status:** draft

## Goal

Build a deterministic Python orchestrator that autonomously builds the platform — delegating code generation to LLMs via API, running tests, sending output through adversarial review (Gemini critique → Claude defense → GPT arbitration), incorporating feedback, and continuing to the next module. Runs for hours with zero human intervention. Python controls the loop; LLMs provide intelligence.

Per Arnar: "Agents are autonomous loops that stop only when their human-defined task is complete or if they encounter a situation that violates their safety guardrails."

Per Gummi: "Speed makes iteration cheap. Structure makes iteration safe."

## Architecture

### The Loop

```
while not terminated:
    1. Read state (.orchestrator-state.json) → next module
    2. Build prompt with spec + context + existing code
    3. Call Claude API → generate module code
    4. Write code to disk
    5. Run pytest → deterministic pass/fail
    6. Call Gemini → adversarial critique of code
    7. Call Claude → defend or accept critique
    8. If unresolved → Call GPT → arbitrate
    9. If changes accepted → Call Claude → implement fixes
    10. Re-run pytest → verify fixes
    11. Update state → module complete
    12. Check termination conditions
```

### Termination conditions
- All phases complete → SUCCESS
- 3 consecutive module failures → STOP (needs human)
- pytest regression (existing tests broke) → STOP
- Time limit (6 hours default) → STOP
- API budget exceeded → STOP

### State file (.orchestrator-state.json)
```json
{
  "started_at": "ISO",
  "current_phase": 1,
  "current_module": "project.py",
  "completed_modules": ["conftest.py", "project.py"],
  "failed_modules": [],
  "consecutive_failures": 0,
  "test_results": {"passed": 12, "failed": 0},
  "adversarial_reviews": [...],
  "total_api_calls": 14,
  "total_loc_written": 580
}
```

## Inputs
- CURRENT_TASKS.md (the maestro plan with 7 phases, 12 modules)
- Existing harness code (lib/python/harness/)
- API keys for all 3 providers (.env)
- Spec files for context

## Outputs
- Built Python modules in lib/python/harness/
- Test files in tests/harness/
- CLI commands in cli/commands/
- .orchestrator-state.json (progress tracking)
- .orchestrator-log.md (human-readable build log)

## CLOC Targets

| Category | Before | Target | Growth |
|----------|--------|--------|--------|
| harness/ (lib) | 856 | ~3,300 | +2,470 |
| harness/ templates | 0 | ~200 | +200 |
| tests/ | 0 | ~1,500 | +1,500 |
| cli/ commands | ~500 | ~940 | +440 |
| registry/ (new) | 0 | ~500 | +500 |
| orchestrator | 0 | ~400 | +400 |
| **Total Python** | **~2,500** | **~7,500** | **+5,000** |

## Done When
- [x] `lib/python/orchestrator/orchestrator.py` exists and runs the build loop
- [ ] Orchestrator builds at least Phase 0-1 modules autonomously — code structure exists, not verified running end-to-end
- [x] Each built module has passing tests — 398 tests passing
- [ ] Adversarial review runs on each module (Gemini + Claude + GPT) — pipeline exists separately, integration not confirmed
- [x] State persisted to .orchestrator-state.json between steps
- [x] Build log written to .orchestrator-log.md
- [x] Termination conditions enforced (consecutive failures, time limit)
- [x] `cloc` shows significant growth toward 7,500 LOC target — 6,805 lines (91%)
