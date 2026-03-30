# Test Suite Quality Audit

**Date**: 2026-03-29
**Reported**: 626 tests passing
**Actual test functions**: 559 (difference from `@pytest.mark.parametrize` expansion)

## Summary

~55-60% of the 626 reported tests would catch a real production bug. The harness/ tests are the strongest section. The adversarial/ section is the weakest. The headline number is padded by structural assertions and a mock DB layer that tests its own correctness rather than the production system's.

## Category Breakdown

| Category | Count | % of 559 | Description |
|----------|-------|----------|-------------|
| **Real functionality** | 278 | 50% | Meaningful behavior, edge cases, state mutations |
| **Basic correctness** | 175 | 31% | Simple happy-path, one-liner assertions |
| **Structural/smoke** | 60 | 11% | Dataclass defaults, field name assertions, import checks |
| **Security/adversarial** | 15 | 3% | Credential boundary, JWT tampering, injection patterns |
| **Integration** | 6 | 1% | Multiple real subsystems working together |
| **Mock-testing-mock** | 5 | 1% | Tests that import no production code |

## Per-File Assessment

### harness/ (331 functions) -- STRONGEST

| File | Tests | S | B | F | I | A | Notes |
|------|-------|---|---|---|---|---|-------|
| test_platform_check.py | 52 | 8 | 12 | 20 | 0 | 12 | Best in suite. 12 security tests cover credential allowlist/denylist + injection patterns |
| test_git_ops.py | 52 | 6 | 14 | 28 | 4 | 0 | Real git subprocess calls. Handles quoted paths, branch fallbacks |
| test_maestro_support.py | 43 | 4 | 18 | 21 | 0 | 0 | Scope change detection, trajectory thresholds |
| test_scanner.py | 41 | 8 | 15 | 18 | 0 | 0 | Real markdown parsing against tmp_path spec files |
| test_session.py | 33 | 6 | 12 | 15 | 0 | 0 | State machine transition validation |
| test_project.py | 32 | 5 | 14 | 13 | 0 | 0 | Project detection, worktree resolution |
| test_refresh.py | 28 | 5 | 12 | 11 | 0 | 0 | Snapshot capture, invariant checks |
| test_checkpoint.py | 28 | 5 | 10 | 13 | 0 | 0 | Backlog updates, commit staging |
| test_drift.py | 22 | 2 | 7 | 13 | 0 | 0 | Deletes real files, checks regression detection. One of the strongest files |
| test_ground_truth.py | 11 | 0 | 2 | 9 | 0 | 0 | Complete scenario tests. Bootstrap idempotency verified |

### adversarial/ (19 functions) -- WEAKEST

| File | Tests | S | B | F | I | A | Notes |
|------|-------|---|---|---|---|---|-------|
| test_adversarial.py | 5 | 0 | 0 | 0 | 0 | 0 | **DELETE CANDIDATE.** All 5 test mock classes defined in the test file. Zero production code imported |
| test_pipeline.py | 14 | 0 | 3 | 11 | 0 | 0 | Tests real parsers and report generation. Best adversarial file |

### runtime/ (82 functions)

| File | Tests | S | B | F | I | A | Notes |
|------|-------|---|---|---|---|---|-------|
| test_triage.py | 26 | 0 | 5 | 21 | 0 | 0 | Strong. Threshold boundaries, escalation chains, event emission |
| test_spec_parser.py | 15 | 0 | 4 | 11 | 0 | 0 | Code fence edge case is standout test |
| test_db.py | 15 | 0 | 8 | 7 | 0 | 0 | **220-line MockCursor.** Tests mock behavior, not PostgreSQL. Silent divergence risk |
| test_worktree.py | 10 | 0 | 3 | 7 | 0 | 0 | Real git subprocess calls |
| test_mcp_tools.py | 6 | 0 | 4 | 2 | 0 | 0 | Tool dispatch |
| test_server.py | 5 | 0 | 3 | 2 | 0 | 0 | FastAPI TestClient with mock store |
| test_schema.py | 5 | 5 | 0 | 0 | 0 | 0 | **Weak.** Just `assert "column_name" in sql_string`. Doesn't validate SQL is executable |

### ship/ (90 functions)

| File | Tests | S | B | F | I | A | Notes |
|------|-------|---|---|---|---|---|-------|
| test_pipeline.py | 16 | 0 | 3 | 13 | 0 | 0 | Best ship file. Resume-from-failure uses assert_not_called() |
| test_strategies.py | 16 | 1 | 4 | 11 | 0 | 0 | Merge conflict, network error mapping |
| test_state.py | 16 | 2 | 6 | 8 | 0 | 0 | Real SQLite (not mocked). Purge, upsert, ordering |
| test_deploy.py | 15 | 2 | 6 | 7 | 0 | 0 | Deploy targets, command execution |
| test_feedback.py | 12 | 1 | 5 | 6 | 0 | 0 | Feedback classification pipeline |
| test_promotion.py | 7 | 0 | 3 | 4 | 0 | 0 | Complete promotion scenario |
| test_audit.py | 4 | 0 | 2 | 2 | 0 | 0 | Audit log write/read |
| test_ship_routes.py | 4 | 0 | 2 | 1 | 0 | 1 | Lock test tests a Lock() defined in the test body, not production code |

### dashboard/ (26 functions)

| File | Tests | S | B | F | I | A | Notes |
|------|-------|---|---|---|---|---|-------|
| test_api.py | 15 | 0 | 5 | 8 | 2 | 0 | FastAPI TestClient with mock store. Auth integration verified |
| test_auth.py | 11 | 0 | 3 | 6 | 0 | 2 | JWT tampering, expiration. Real round-trip tests |

## Best Tests (examples worth copying)

1. **test_ground_truth.py::test_second_run_imports_nothing** -- Two-pass idempotency with real file I/O
2. **test_pipeline.py::test_resume_from_failure** (ship) -- assert_not_called() on completed steps
3. **test_drift.py::test_done_regressions_detects_missing_file** -- Deletes real file, checks detection
4. **test_auth.py::test_tampered_token** -- One character flip, expect None
5. **test_platform_check.py::TestValidateCredentialAccess** -- Allowlist/denylist invariant

## Worst Tests (candidates for replacement)

1. **test_adversarial.py** (all 5) -- Mock classes defined in test file, zero production code
2. **test_schema.py** (all 5) -- String-contains on SQL, doesn't validate executability
3. **test_ship_routes.py::test_concurrent_lock_logic** -- Tests Lock() defined in test body
4. **TestDataclasses clusters** (across harness files) -- Field name/default checks only

## Untested Areas

| Area | Risk | Notes |
|------|------|-------|
| **CLI commands** (cli/) | High | 15 commands, 0 tests. Any CLI regression invisible |
| **Model registry** (registry/) | High | "music domain never gets text model" invariant untested |
| **Orchestrator** (orchestrator/) | Medium | Autonomous build loop untested |
| **Real PostgreSQL** | High | MockCursor divergence risk. 35+ tests use it |
| **End-to-end harness workflow** | Medium | State machine tested unit-by-unit but never as sequence |
| **Dashboard routes** (new route modules) | Medium | project_routes, spec_crud_routes, task_routes have minimal coverage |

## Recommendations

1. Delete test_adversarial.py (5 fiction tests) and replace with real pipeline tests
2. Replace MockCursor with real PostgreSQL via testcontainers or sqlite fallback
3. Add CLI smoke tests (at minimum: each command runs with --help)
4. Add model registry boundary tests (music -> Suno, never GPT)
5. Rewrite test_schema.py to validate SQL executes against a real DB
6. Add integration tests: queue -> build -> review -> merge as a workflow
