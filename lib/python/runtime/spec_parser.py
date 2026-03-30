"""Parse structured sections from spec markdown content.

Pure functions — string in, data out. No file I/O, no side effects.
Mirrors harness/parser.py patterns but operates on content strings
instead of file paths (prompts.py works with already-loaded content).
"""

from __future__ import annotations

import re


def extract_goal(spec_content: str) -> tuple[str, str]:
    """Extract the Goal section from spec markdown.

    Returns (first_sentence, full_goal_text).
    first_sentence is the north-star summary — just the opening sentence.
    full_goal_text is everything under ## Goal until the next ## heading.
    Returns ("", "") if no Goal section found.
    Skips ## Goal inside code fences.
    """
    lines = spec_content.splitlines()
    in_fence = False
    in_goal = False
    goal_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if re.match(r"^##\s+Goal\s*$", stripped):
            in_goal = True
            continue

        if in_goal and re.match(r"^##\s+", stripped):
            break

        if in_goal:
            goal_lines.append(line)

    full_text = "\n".join(goal_lines).strip()
    if not full_text:
        return "", ""

    # First sentence: split at first period followed by space or end-of-string.
    # Fall back to entire first non-empty line if no period found.
    sentence_match = re.match(r"(.+?\.)\s", full_text, re.DOTALL)
    if sentence_match:
        first_sentence = sentence_match.group(1).strip()
    else:
        first_sentence = full_text.split("\n")[0].strip()

    return first_sentence, full_text


def extract_done_when_items(spec_content: str) -> list[dict]:
    """Extract Done When checklist items from spec markdown.

    Returns list of dicts: {"text": str, "checked": bool}.
    Skips Done When headings inside code fences.
    """
    lines = spec_content.splitlines()
    in_fence = False
    in_done_when = False
    items: list[dict] = []

    for line in lines:
        stripped = line.strip()
        # Track code fences
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        # Detect start of Done When section (outside code fences)
        if re.match(r"^##\s+Done\s+When\b", stripped, re.IGNORECASE):
            in_done_when = True
            continue

        # A new h2 ends the section
        if in_done_when and re.match(r"^##\s+", stripped):
            break

        if not in_done_when:
            continue

        m = re.match(r"^-\s+\[([ xX])\]\s+(.+)$", stripped)
        if m:
            items.append({
                "text": m.group(2).strip(),
                "checked": m.group(1).lower() == "x",
            })
    return items


def build_mission_criterion(goal_sentence: str) -> str:
    """Rephrase the goal as a user-observable acceptance criterion.

    Prepended as checkbox #1 in the acceptance criteria so Claude
    checks the forest, not just the trees.
    """
    if not goal_sentence:
        return ""
    # Strip trailing period for cleaner sentence flow
    clean = goal_sentence.rstrip(".")
    return f"The spec goal is achieved: {clean}"
