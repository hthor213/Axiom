"""Prompt templates for Claude Agent SDK sessions.

All functions are pure — no DB access, no side effects.
They take data in and return prompt strings.
"""

from __future__ import annotations

import os
from typing import Optional

from .draft_context import load_resume_context
from .spec_parser import extract_goal, extract_done_when_items, build_mission_criterion


def find_spec(spec_number: str, repo_root: str) -> Optional[str]:
    """Find a spec file by number. Returns the file path or None."""
    specs_dir = os.path.join(repo_root, "specs")
    if not os.path.isdir(specs_dir):
        return None
    for fname in os.listdir(specs_dir):
        if fname.startswith(f"{spec_number}-") and fname.endswith(".md"):
            return os.path.join(specs_dir, fname)
    return None


def build_draft_prompt(spec_number: str, spec_title: str,
                       spec_content: str, resume_context: str) -> str:
    """Build the prompt for a draft review session.

    Pure function — assembles the refinement prompt from the spec
    content and any resume context from prior reviews.
    """
    return f"""You are a thorough technical analyst refining a draft spec. \
This spec defines an entire module — getting it right is critical. \
A shallow review is a FAILURE. Go deep.

## Spec: {spec_number} — {spec_title}
{spec_content}

## Your process (follow this exactly)

### Phase 1: Understand context
- Read the codebase thoroughly — especially lib/python/, specs/, and CLAUDE.md
- Understand what already exists and how this spec fits in
- Check every spec referenced (-> spec:NNN) for consistency

### Phase 2: Challenge every line
For each statement in the spec, ask yourself:
- Is this testable? Can a machine verify it?
- Is this ambiguous? Could two developers interpret it differently?
- Is this complete? What's missing?
- Is this consistent with the rest of the system?
- Does this make assumptions that should be explicit?

### Phase 3: Write questions
You MUST write at least 3 questions in a "## Questions for Human" section \
at the bottom of the spec. These should be genuine ambiguities or design \
decisions that only the human can answer.

Each question MUST follow this EXACT format (the server parses this):

### Q1: Short title
One-sentence question ending with ?
- a) Option text <- RECOMMENDED
- b) Option text
- c) Option text (optional, 2-4 options per question)

Rules:
- Mark exactly ONE option as RECOMMENDED with "\u2190 RECOMMENDED"
- Keep questions short (1 sentence). Keep options short (1 line each).
- 2-4 options per question, no more
- The human reads these on a phone — brevity is critical
- Each question must be a genuine ambiguity, not something you can answer yourself

If you can't find 3 real questions, you haven't looked hard enough. \
Think about edge cases, integration points, error handling, and scope boundaries.

### Phase 4: Rewrite the spec
Write the improved spec directly to the spec file. Include:
- Clear, testable Done When items (every one must be automatable)
- Explicit architecture decisions (not implied)
- Dependencies on other specs listed
- Your questions section at the bottom
- Keep status as "draft" — the human decides when to promote

## Constraints
- Do NOT invent features or requirements — only clarify and sharpen what's there
- Do NOT change the fundamental intent of the spec
- DO challenge vague language ("should", "might", "could", "properly", "correctly")
- DO add concrete file paths, function names, and data structures where possible
{resume_context}"""


def build_code_prompt(task_item: str, spec_number: str, spec_title: str,
                      spec_content: str, user_instructions: str,
                      plan_context: str = "") -> str:
    """Build the prompt for a code-building session.

    Pure function — assembles the execution prompt from the task
    item, spec content, and optional user instructions.
    """
    user_instructions_block = ""
    if user_instructions:
        user_instructions_block = f"\n\n## Additional Instructions from Human\n{user_instructions}\n"

    # Extract goal for context
    goal_sentence, _ = extract_goal(spec_content)
    context_line = f"\n\n**Spec goal:** {goal_sentence}" if goal_sentence else ""

    plan_block = ""
    if plan_context:
        plan_block = f"\n{plan_context}\n"

    return f"""## YOUR MISSION
{task_item}
{plan_block}
## Context — Spec {spec_number}: {spec_title}{context_line}

## Full Spec
{spec_content}

## CRITICAL: Scope Constraint
You MUST only build what the task above requires. Every change must trace back
to the Done When item specified. Do NOT fix unrelated code, refactor files
outside this spec's scope, or substitute different work if you hit a blocker.

## Instructions
1. Read the existing codebase to understand patterns (especially lib/python/harness/)
2. Build the code needed to satisfy the Done When item above
3. Write tests (pytest) for your code
4. Run the tests and fix any failures
5. Check off the Done When item in `specs/{spec_number}-*.md`:
   change `- [ ]` to `- [x]` for the item you completed.
   The adversarial reviewer will verify your claim.
6. Use the platform_harness_check tool to verify your work against the spec

## Constraints
- Use dataclasses for data structures (match existing patterns)
- Import from existing modules where appropriate
- No external dependencies beyond what's already in requirements
- Handle missing files gracefully (return defaults, don't crash)
- Keep code clean, typed, and documented

## ACCEPTANCE CRITERIA — This Task Is Done When
- [ ] {task_item}
{user_instructions_block}"""


def build_full_spec_prompt(spec_number: str, spec_title: str,
                           spec_content: str, user_instructions: str,
                           plan_context: str = "") -> str:
    """Build the prompt for a full-spec build session.

    The spec is the unit of work. Claude gets the entire spec and all
    Done When items. It uses maestro to plan milestones internally.

    The server extracts Goal and Done When deterministically so they
    appear prominently: north star at top, acceptance criteria at bottom.
    """
    user_instructions_block = ""
    if user_instructions:
        user_instructions_block = f"\n\n## Additional Instructions from Human\n{user_instructions}\n"

    # Extract structured sections from spec
    goal_sentence, full_goal = extract_goal(spec_content)
    done_when = extract_done_when_items(spec_content)
    unchecked = [item["text"] for item in done_when if not item["checked"]]
    checked = [item["text"] for item in done_when if item["checked"]]

    # Build north star header
    mission_block = ""
    if goal_sentence:
        mission_block = f"## YOUR MISSION\n{goal_sentence}\n\n"

    # Build goal section (only if extracted — avoids duplication if parsing fails)
    goal_block = ""
    if full_goal:
        goal_block = f"## Goal\n{full_goal}\n\n"

    # Build acceptance criteria with mission checkpoint as #1
    criteria_block = ""
    mission_criterion = build_mission_criterion(goal_sentence)
    if unchecked or mission_criterion:
        lines = []
        if mission_criterion:
            lines.append(f"- [ ] {mission_criterion}")
        for item in unchecked:
            lines.append(f"- [ ] {item}")
        criteria_block = (
            "## ACCEPTANCE CRITERIA — You Are Done When ALL Pass\n"
            + "\n".join(lines)
            + "\n"
        )

    # Show checked items with guidance based on mission state
    already_done_block = ""
    if checked:
        checked_lines = [f"- [x] {item}" for item in checked]
        if unchecked:
            # Mission incomplete — verify existing progress still works, focus on unchecked
            already_done_block = (
                "\n## Previously Completed\n"
                "These items are marked complete. Verify they still work but focus\n"
                "your effort on the unchecked acceptance criteria above.\n"
                + "\n".join(checked_lines)
                + "\n"
            )
        else:
            # All items checked — verify accuracy, challenge whether it truly works
            already_done_block = (
                "\n## Previously Completed — Verify Accuracy\n"
                "All items are marked complete. Challenge whether each truly works\n"
                "end-to-end. Run the code, check edge cases, confirm the mission\n"
                "is actually achieved — not just that boxes are ticked.\n"
                + "\n".join(checked_lines)
                + "\n"
            )

    plan_block = ""
    if plan_context:
        plan_block = f"{plan_context}\n\n"

    return f"""{mission_block}{goal_block}{plan_block}## Full Spec — {spec_number}: {spec_title}
{spec_content}

## CRITICAL: Scope Constraint
You MUST only build what this spec requires. Every change you make must trace
back to a Done When item in the spec above. Do NOT:
- Fix unrelated code, even if you notice problems
- Refactor files that aren't part of this spec's scope
- Work on backlog items, tech debt, or improvements outside this spec
- Reinterpret the spec to mean something different than what it says

If a Done When item is ambiguous, implement the most literal interpretation.
If you cannot build a feature because of a blocker, document it — do NOT
substitute a different piece of work instead.

## How to Work
Use maestro to plan this work into milestones. The Done When items in the spec
define acceptance criteria — they are NOT independent tasks. Many will overlap.
Plan milestones that deliver working functionality, not one-item-at-a-time.

1. Read the existing codebase to understand patterns and what already exists
2. Use maestro to break the spec into logical milestones
3. Build each milestone, running tests after each
4. After completing a Done When item, CHECK IT OFF in the spec file:
   change `- [ ]` to `- [x]` in `specs/{spec_number}-*.md`
   This is how you report progress. The adversarial reviewer will verify
   your claims — only check off items you have genuinely completed.
5. Use the platform_harness_check tool to verify Done When criteria
6. All Done When items should be checked off when you're done

## Constraints
- Use dataclasses for data structures (match existing patterns)
- Import from existing modules where appropriate
- No external dependencies beyond what's already in requirements
- Python files: 200-line soft cap, 350-line hard cap
- Keep code clean, typed, and documented

{criteria_block}{already_done_block}{user_instructions_block}"""


def build_fix_prompt(spec_number: str, feedback: str) -> str:
    """Build the prompt for an adversarial fix session.

    Pure function — assembles a focused fix prompt from
    the adversarial feedback.
    """
    return f"""Adversarial review found issues with your code for spec {spec_number}.

## Consolidated Feedback
{feedback}

## Instructions
1. Read the feedback carefully — it comes from three independent model reviews
2. Fix the issues in the existing code (do not rewrite from scratch)
3. Run tests after fixing to make sure nothing is broken
4. Do NOT change functionality — only fix the issues raised
5. After fixing, update the spec file (`specs/{spec_number}-*.md`) with a
   `## Fix Summary` section at the end. For each issue raised above, report:
   - FIXED: what you changed (one line)
   - WONT_FIX: why this is not a real issue (one line)
   - PARTIAL: what you did and what remains (one line)
   The adversarial reviewer will verify these claims on re-check.

## Constraints
- Stay in the existing worktree — all files are already here
- Focus on the specific issues raised, not general improvements"""


def build_agent_prompt(task, store, repo_root: str,
                       plan_context: str = "") -> str:
    """Build the full prompt for a Claude Agent SDK session.

    Looks up the spec file and any resume context, then delegates
    to the appropriate prompt builder (draft or code).
    """
    spec_path = find_spec(task.spec_number, repo_root)
    spec_content = ""
    if spec_path:
        try:
            with open(spec_path) as f:
                spec_content = f.read()
        except OSError:
            pass

    resume_context = load_resume_context(task, store)

    if task.done_when_item == "__draft_review__":
        return build_draft_prompt(
            task.spec_number, task.spec_title,
            spec_content, resume_context,
        )

    if task.done_when_item == "__full_spec__":
        return build_full_spec_prompt(
            task.spec_number, task.spec_title,
            spec_content, task.user_instructions,
            plan_context=plan_context,
        )

    return build_code_prompt(
        task.done_when_item, task.spec_number,
        task.spec_title, spec_content,
        task.user_instructions,
        plan_context=plan_context,
    )
