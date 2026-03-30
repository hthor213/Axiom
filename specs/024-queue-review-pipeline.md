# 024: Queue Review Pipeline — Every Queue Item Gets Reviewed

**Status:** draft

## Goal

Every task processed from the queue gets a review before completion. No SKIP verdicts for queue-processed work. The review type depends on what changed:

| Change type | Review method | Reviewer |
|-------------|---------------|----------|
| Code files (`.py`, `.c`, `.cs`, `.js`, `.ts`, etc.) | Full adversarial chain | Gemini → Claude → debate → GPT arbiter |
| Spec updates (modified specs in `specs/`) | Single-turn GPT review | GPT as "second pair of eyes" |
| Mixed (code + spec) | Both reviews run | Adversarial for code, GPT for spec |

SKIP is only valid during ideation — backlog creation, draft specs, brainstorming. Once work enters the queue for processing, it must be reviewed.

## Architecture

### Review routing (in `verify_code()`)

After tests pass, the pipeline classifies changed files:

```
changed_files = git_diff(base_ref) + git_ls_files(untracked)
code_files = [f for f in changed_files if f.endswith(CODE_EXTENSIONS)]
spec_files = [f for f in changed_files if f.startswith("specs/") and f.endswith(".md")]

if code_files:
    run_adversarial(code_files)     # Full 3-model chain
if spec_files:
    run_spec_review(spec_files)     # GPT single-turn review
if not code_files and not spec_files:
    verdict = "PASS"                # Non-reviewable files (configs, assets) — pass if tests pass
```

### Code review (existing adversarial chain — spec:011)

No change to the existing pipeline. Gemini challenges, Claude defends, GPT arbitrates disputes. Extended to support more file extensions:

```python
CODE_EXTENSIONS = (".py", ".c", ".h", ".cs", ".js", ".ts", ".tsx", ".go", ".rs", ".java")
```

### Spec review (new: GPT single-turn)

For spec file changes, GPT gets a single-turn review with a strict prompt:

```
You are reviewing a spec update. Your job is to find problems — you FAIL if you say everything is perfect.

For each file, provide:
1. What looks wrong or incomplete
2. What could be better
3. Any contradictions with other specs or the vision

If the changes are genuinely solid, you must still identify at least one improvement opportunity (even minor).
Respond with JSON: {"verdict": "PASS" | "FAIL", "issues": [...], "suggestions": [...]}
```

Verdict rules:
- PASS with suggestions → task passes, suggestions stored in report for reference
- FAIL with issues → task fails, issues fed back to Claude for fix session

### Untracked file detection (bug fix)

`git diff --name-only <base_ref>` misses new untracked files created by the agent. The diff command must be augmented:

```python
# Tracked changes (modifications + staged new files)
diff_files = git_diff("--name-only", base_ref)

# Untracked new files (agent-created, not yet staged)
untracked_files = git_ls_files("--others", "--exclude-standard")

all_changed = set(diff_files) | set(untracked_files)
```

This fixes the bug where `spec_currency.py` (259 lines of new Python) was invisible to the review pipeline because it was untracked.

### No SKIP for queue items

The `SKIP` verdict is removed from the queue processing path. After the review routing above:
- Code files present → adversarial review runs → PASS or FAIL
- Spec files present → GPT review runs → PASS or FAIL
- Neither present → PASS (if tests pass, non-reviewable changes are fine)
- Both present → both reviews must pass

SKIP remains valid only when `config.run_adversarial = False` (explicitly disabled via `--no-adversarial`).

## Key Decisions

- **GPT as spec reviewer, not adversary** — Spec reviews need a collaborative "second pair of eyes," not a hostile challenger. GPT's strength is systematic analysis.
- **Strict prompt** — "You FAIL if you say everything is perfect" prevents sycophantic rubber-stamp approvals.
- **Code extensions are extensible** — Adding new languages is a one-line change to `CODE_EXTENSIONS`.
- **Untracked files included** — `git ls-files --others --exclude-standard` catches agent-created files that haven't been staged.
- **Non-reviewable files pass** — Config files, assets, `.gitignore` changes don't need adversarial review. Tests are sufficient.

## Done When

- [ ] `run_adversarial()` in review.py detects untracked new files (not just `git diff`)
- [ ] Code review supports `.py`, `.c`, `.cs`, `.js`, `.ts`, `.go`, `.rs`, `.java` extensions
- [ ] Spec file changes (`specs/*.md`) trigger GPT single-turn review with strict prompt
- [ ] GPT spec review produces structured JSON with verdict, issues, and suggestions
- [ ] No SKIP verdict for queue-processed tasks — routing always produces PASS or FAIL
- [ ] Quality gate in server.py handles the new review routing (code verdict + spec verdict)
- [ ] Pipeline correctly handles mixed changes (code + spec in same commit)
