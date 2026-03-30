# 027: Repo Hygiene — Automated Code Quality Passes

**Status:** draft

## Goal

Run automated hygiene passes on a repo that enforce coding standards, flag violations, and optionally refactor. Today coding standards (200/350 line caps, 50-line function max, import limits) exist as memory/documentation but aren't machine-enforced. This spec makes them executable.

## Checks

| Check | Threshold | Severity |
|-------|-----------|----------|
| File length | > 200 lines: warn, > 350 lines: error | warn / error |
| Function length | > 50 lines | warn |
| Class methods | > 10 methods | warn |
| Import count | > 15 unique imports | warn |
| Dead imports | Imported but unused | info |
| Dead code | Functions/classes defined but never called | info |
| Naming conventions | Non-snake_case functions/variables in Python | info |

Severity levels: `error` blocks merge (in queue pipeline), `warn` appears in report, `info` is advisory.

## Approach

### Phase 1 — Static analysis (deterministic)

Python AST-based analysis. No LLM needed for measurement:

```python
import ast

def analyze_file(path: str) -> FileReport:
    tree = ast.parse(path.read_text())
    return FileReport(
        lines=len(source.splitlines()),
        functions=[f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)],
        classes=[c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)],
        imports=extract_imports(tree),
    )
```

Each check is a pure function: `(FileReport) -> list[Violation]`.

### Phase 2 — Refactor suggestions (LLM-assisted, opt-in)

When run with `--fix` or `--suggest`, the LLM proposes splits for files exceeding thresholds:

- Files > 350 lines: suggest concrete split points (which functions/classes move where)
- Functions > 50 lines: suggest extraction points
- Dead code: confirm it's truly unused before suggesting removal

The LLM call structure: provide the file, the violations, and the coding standards. Ask for a refactoring plan, not direct edits.

### Phase 3 — Report

```
Repo Hygiene Report — 2026-03-26
Target: lib/python/

ERRORS (blocking):
  lib/python/harness/state.py — 387 lines (cap: 350)

WARNINGS:
  lib/python/adversarial/debate.py — 248 lines (cap: 200)
  lib/python/runtime/server.py:process_task — 63 lines (cap: 50)

INFO:
  lib/python/harness/parser.py — 3 unused imports (os, re, json)

Summary: 1 error, 2 warnings, 1 info across 42 files scanned
```

## Integration Points

- **CLI**: `hth-platform hygiene [path]` — scan a directory, default to project root
- **CLI flags**: `--fix` (LLM suggests refactors), `--errors-only`, `--json` (machine-readable)
- **Queue pipeline**: Add as optional chain step after tests pass, before adversarial review
- **Adversarial review**: Gemini reviewer already flags file size (per coding_standards.md). This makes it deterministic and pre-review.

## Key Decisions

- **AST over regex** — Python's `ast` module gives accurate function/class/import counts. Regex would miss nested definitions and get confused by strings.
- **Deterministic measurement, LLM judgment** — Counting lines is Python's job. Deciding where to split is the LLM's job. Same separation as the rest of the platform.
- **No auto-apply** — `--fix` suggests, it doesn't edit. The developer reviews and applies. This prevents surprise refactors.
- **Incremental by default** — When run on a directory, only report violations. Don't touch files that pass. "One improvement per file per sprint" philosophy.

## Done When

- [ ] `hth-platform hygiene` scans Python files and reports line counts, function lengths, class method counts, and import counts
- [ ] Files > 350 lines are flagged as errors, > 200 as warnings
- [ ] Functions > 50 lines are flagged as warnings
- [ ] `--fix` flag triggers LLM-assisted refactoring suggestions (split points, not direct edits)
- [ ] Report output includes summary with error/warning/info counts
- [ ] `--json` flag produces machine-readable output for pipeline integration
