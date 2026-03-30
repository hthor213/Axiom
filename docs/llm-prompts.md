# LLM Prompt Reference

All prompts sent to LLMs from the platform. Each entry shows: who receives it, what context/payload they get, and what they're asked to do.

---

## Claude Code (Agent SDK) — Full Repo Access

These prompts are sent to Claude Code via `claude -p`. The agent has **full repo access**: file editing, bash, MCP tools, 1M context window, maestro/sub-agents.

| Prompt | File | Trigger | What Claude Gets |
|--------|------|---------|-----------------|
| **Build Full Spec** | `runtime/prompts.py:140` | "Build" button on dashboard | North star goal at top + full spec + acceptance criteria checklist at bottom + optional user instructions |
| **Build Single Item** | `runtime/prompts.py:95` | Per-item task | YOUR MISSION header with task + spec goal context + acceptance criterion at bottom |
| **Draft Review** | `runtime/prompts.py:33` | Autonomous draft refinement | Full spec + resume context (prior Q&A, Gemini feedback) + "refine this draft" |
| **Fix from Feedback** | `runtime/prompts.py:254` | Adversarial FAIL verdict | Mission assessment + consolidated issues + instruction to write Fix Summary in spec file |

**North star extraction**: The server parses `## Goal` and `## Done When` from spec markdown deterministically (`runtime/spec_parser.py`). The first sentence of Goal becomes the YOUR MISSION header. Done When items are split into unchecked (acceptance criteria) and checked (previously completed). A synthesized mission criterion is prepended as checkbox #1.

**Spec as progress tracker**: Claude is instructed to check off `- [ ]` → `- [x]` in the spec file as it completes each Done When item. The adversarial reviewer reads the spec from the worktree, so it sees Claude's claims and verifies them against the actual code. On merge, the checked-off items flow into main — keeping the spec in sync with reality.

**Fix resolution reporting**: When adversarial review FAILs, Claude receives the mission assessment (YES/PARTIAL/NO) plus issue list. After fixing, Claude writes a `## Fix Summary` section in the spec file with FIXED/WONT_FIX/PARTIAL per issue. On re-check, Gemini verifies these claims against the actual code changes and flags false claims as critical.

**Mission confirmation chain**: Gemini's Mission Assessment (YES/PARTIAL/NO + reasoning) flows through: challenger output → `generate_report()` → Result record → `assemble_feedback()` (for fix sessions) → markdown report. The dashboard can display it from the `mission_assessment` field in `adversarial_report`.




### Build Full Spec prompt (what "Build" sends)
```
## YOUR MISSION
{first sentence of Goal — extracted by server from ## Goal section}

## Goal
{full Goal section text}

## Full Spec — {number}: {title}
{entire spec markdown}

## CRITICAL: Scope Constraint
You MUST only build what this spec requires. Every change must trace
back to a Done When item. Do NOT fix unrelated code, refactor outside
scope, work on backlog items, or reinterpret the spec.

## How to Work
Use maestro to plan this work into milestones. The Done When items
define acceptance criteria — they are NOT independent tasks. Many
will overlap. Plan milestones that deliver working functionality.

1. Read the existing codebase to understand patterns
2. Use maestro to break the spec into logical milestones
3. Build each milestone, running tests after each
4. Use the platform_harness_check tool to verify Done When criteria
5. All Done When items should be satisfied when you're done

## Constraints
- Python files: 200-line soft cap, 350-line hard cap
- Use dataclasses, match existing patterns
- No external dependencies beyond requirements

## ACCEPTANCE CRITERIA — You Are Done When ALL Pass
- [ ] The spec goal is achieved: {north star rephrased as outcome}
- [ ] {unchecked Done When item 1}
- [ ] {unchecked Done When item 2}
...

## Previously Completed
{If unchecked items remain: "Verify they still work but focus effort on unchecked criteria above."}
{If all items checked: "Challenge whether each truly works end-to-end. Confirm the mission is achieved."}
- [x] {checked Done When item 1}
...

## Additional Instructions from Human
{optional user instructions from the Build panel}
```

---

## Adversarial Pipeline — Code Review (spec:011)

Three models review code changes after Claude builds. Each gets **specific file contents** (not full repo).

### Gemini — Challenger
| File | `adversarial/prompts.py:21` + `adversarial/challenger.py` |
|------|---|
| **Receives** | Changed file contents (Python/markdown), spec context (mission + Done When), file sizes |
| **Role** | Hostile code reviewer. First question: does this achieve the spec's mission? Then find bugs. |
| **Output** | Markdown: mission assessment (YES/PARTIAL/NO), issues with severity, spec alignment |
| **API** | Gemini REST, temp 0.2, max 8192 tokens |

### Claude — Author Defense
| File | `adversarial/prompts.py:96` + `adversarial/author_rebuttal.py` |
|------|---|
| **Receives** | Changed file contents + Gemini's issues |
| **Role** | Defend the code. Accept valid issues, rebut invalid ones with evidence. |
| **Output** | JSON: per-issue accept/rebut with reasoning |
| **API** | Anthropic Messages API, max 4096 tokens |

### Gemini — Counter-Rebuttal
| File | `adversarial/prompts.py:68` + `adversarial/challenger.py` |
|------|---|
| **Receives** | Original issues + Claude's rebuttals |
| **Role** | Evaluate rebuttals. Concede if author is right, maintain if not. |
| **Output** | JSON: per-issue concede/maintain |
| **API** | Gemini REST |

### GPT — Arbiter
| File | `adversarial/prompts.py:114` + `adversarial/arbiter.py` |
|------|---|
| **Receives** | Only disputed issues (not conceded/accepted) + both positions |
| **Role** | Senior arbiter. Rule on disputed issues. |
| **Output** | JSON: per-issue ruling (challenger/author) + final verdict (PASS/FAIL) |
| **API** | OpenAI Chat Completions (`gpt-5.4`), temp 0.2, max 4096 tokens |

**API details**: GPT = `gpt-5.4`, Claude = `claude-opus-4-6`, temp 0.3, max 16384 tokens


---

## Spec Review Pipeline — Interactive (spec:025)

User clicks "Spec" button → GPT + Claude review the spec. Each gets **spec content only** (not full repo).

### Flow A: No instructions (blank)

| Step | Model | File | Receives | Role |
|------|-------|------|----------|------|
| 1 | GPT | `spec_routes.py:99` | Spec content | Mentor: "What is this spec missing? Be a good teacher." |
| 2 | Claude | `spec_routes.py:126` | Spec + GPT feedback | Editor: incorporate mentor feedback, return edited spec |

### Flow B: With instructions

| Step | Model | File | Receives | Role |
|------|-------|------|----------|------|
| 1 | Claude | `spec_routes.py:135` | Spec + user instructions | Editor: edit per author's instructions |
| 2 | GPT | `spec_routes.py:112` | Original + edited spec + instructions | Reviewer: "Review the changes. What's still missing?" |

### On Modify (iteration)

| Step | Model | File | Receives | Role |
|------|-------|------|----------|------|
| 1 | Claude | `spec_routes.py:144` | Original + previous edit + human comments | Re-editor: address human's feedback |
| 2 | GPT | `spec_routes.py:99` | Original + previous feedback + human comments + new edit | Re-reviewer: "What do you think of the changes?" |

**API details**: GPT = `gpt-5.4`, Claude = `claude-opus-4-6`, temp 0.3, max 16384 tokens

---

## Test Failure Triage — GPT Helper (spec:014)

| File | `runtime/test_triage.py` / `runtime/review.py:62` |
|------|---|
| **Receives** | Last 4000 chars of pytest output + test trajectory context |
| **Role** | Analyze test failures: recommend fix/reject/escalate |
| **Output** | JSON: recommendation, reasoning, guidance |
| **API** | OpenAI Chat Completions |

---

## Draft Spec Review — Gemini (autonomous)

| File | `runtime/draft_lifecycle.py:272` |
|------|---|
| **Receives** | Original spec + Claude's refined version |
| **Role** | Senior technical reviewer evaluating a spec refinement |
| **Output** | Structured feedback on the changes |
| **API** | Gemini REST |

---

## Model Summary

| Model | Role in System | Access Level |
|-------|---------------|-------------|
| **Claude Code (Agent SDK)** | Builder — writes code, edits files, runs tests | Full repo, bash, MCP tools, maestro |
| **Claude (API)** | Defender (adversarial), Editor (spec review) | Specific file contents or spec text only |
| **Gemini (API)** | Challenger (adversarial), Draft reviewer | Specific file contents or spec text only |
| **GPT (API)** | Arbiter (adversarial), Mentor (spec review), Triage helper | Specific file contents, spec text, or test output only |
