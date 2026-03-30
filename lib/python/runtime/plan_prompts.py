"""Prompt templates for the plan-then-execute pipeline.

Pure functions that build prompts for Claude's plan mode
(--permission-mode plan). No DB access, no side effects.
"""

from __future__ import annotations

from .spec_parser import extract_goal, extract_done_when_items


def build_plan_prompt(task_item: str, spec_number: str, spec_title: str,
                      spec_content: str, user_instructions: str) -> str:
    """Build the prompt for a plan-only session (no execution).

    Instructs Claude to read the codebase and produce a plan, mapping
    changes to Done When items. Used with --permission-mode plan.
    """
    goal_sentence, _ = extract_goal(spec_content)
    context_line = f"\n\n**Spec goal:** {goal_sentence}" if goal_sentence else ""

    user_block = ""
    if user_instructions:
        user_block = f"\n\n## Additional Instructions from Human\n{user_instructions}\n"

    return f"""## YOUR MISSION
Plan the implementation of: {task_item}

## Context — Spec {spec_number}: {spec_title}{context_line}

## Full Spec
{spec_content}

## What You Must Produce
A numbered implementation plan. For each step:
1. Which file(s) will be created or modified (full paths)
2. What changes are needed in each file
3. Which Done When item this step satisfies
4. Any risks, blockers, or assumptions

Read the existing codebase first. Understand patterns and conventions
before proposing changes. Reference existing functions you'll reuse.

Do NOT execute any changes — plan only.
{user_block}"""


def build_full_spec_plan_prompt(spec_number: str, spec_title: str,
                                spec_content: str,
                                user_instructions: str) -> str:
    """Build the plan prompt for a full-spec build (milestone-level).

    Used with --permission-mode plan for __full_spec__ tasks.
    """
    goal_sentence, full_goal = extract_goal(spec_content)
    done_when = extract_done_when_items(spec_content)
    unchecked = [item["text"] for item in done_when if not item["checked"]]

    mission_block = f"## YOUR MISSION\n{goal_sentence}\n\n" if goal_sentence else ""
    criteria = "\n".join(f"- [ ] {item}" for item in unchecked) if unchecked else ""

    user_block = ""
    if user_instructions:
        user_block = f"\n\n## Additional Instructions from Human\n{user_instructions}\n"

    return f"""{mission_block}## Plan the full implementation of Spec {spec_number}: {spec_title}

## Full Spec
{spec_content}

## What You Must Produce
A milestone-level implementation plan. Group related Done When items
into logical milestones that deliver working functionality.

For each milestone:
1. Which Done When items it covers
2. Which files will be created or modified
3. Key implementation decisions
4. Dependencies on other milestones
5. How to verify the milestone works

## Remaining Acceptance Criteria
{criteria}

Read the existing codebase first. Understand patterns, conventions,
and what already exists before planning. Reference specific functions
and modules you'll build on.

Do NOT execute any changes — plan only.
{user_block}"""
