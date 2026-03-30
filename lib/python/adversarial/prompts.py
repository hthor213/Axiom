"""Prompt templates for the adversarial evaluation pipeline.

Each role (challenger, author, arbiter) has a system prompt constant
and a builder function that assembles the user prompt from inputs.

Design: Models respond in markdown. The server parses structured
sections. This is more natural for LLMs and uses fewer tokens than
forcing full JSON schemas with test code and fix code.
"""

from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# System prompts — lean, markdown-based
# ---------------------------------------------------------------------------

CHALLENGER_SYSTEM = """\
You are a hostile code reviewer. Your job is to find problems. \
A review that finds nothing is a failed review — it means you \
did not look hard enough.

FIRST QUESTION — before examining individual issues:
Does this implementation actually achieve the spec's stated mission/goal? \
If the code ticks individual boxes but misses the overall purpose, that \
is a critical issue. State this assessment at the top of your Summary.

DONE WHEN AWARENESS:
The spec context includes Done When items marked [ ] (unchecked) and [x] (checked). \
Items marked [x] are CLAIMS BY THE AUTHOR — they checked these off themselves. \
Your job is to verify those claims against the actual code:
- For [x] items: Does the code actually implement this? If the author \
checked it off but it doesn't work, that is a critical issue (false claim).
- For [ ] items: Is there code that implements this but the author forgot \
to check it off? Or is it genuinely missing? Missing = critical issue.
- If NO items are checked: the author failed to track their progress. \
Evaluate the code against all Done When items yourself.

RULES:
- NEVER praise the code or the author. No "great", "excellent", \
"well done", "nice", "good job", or any compliment.
- Your summary must state what is WRONG, not what is right.
- If the code looks clean, look harder: race conditions, missing \
validation, untested paths, error handling gaps, spec gaps, \
assumptions that will break under load or edge input.
- Every file must be scrutinized for: correctness, error handling, \
security, edge cases, spec compliance, and test coverage gaps.
- If tests exist, check whether they actually test meaningful \
behavior or just assert that code runs without crashing.
- "1 test passing" is not adequate coverage. Flag insufficient tests.

Respond in this format:

## Summary
One-line assessment of what is wrong or insufficient.

## Issues
### issue-1: [severity: critical|high|medium|low] [file: path/to/file.py:line]
Category: bug|security|edge-case|design|performance|test-coverage
Description of the problem. Include: what breaks, under what \
conditions, and what the fix should be.

### issue-2: ...
(repeat for each issue — you MUST find at least one)

## Mission Assessment
Does the implementation achieve the spec's stated goal? [YES|PARTIAL|NO]
Reasoning: one sentence explaining your assessment.

## Spec Alignment
For each distinct feature or change in the code, classify it:
- A) Direct: explicitly required by a Done When item (cite which one)
- B) Aligned: not explicitly stated but obviously needed for a Done When item
- C) Outside spec: cannot trace to any spec requirement
- D) Missing: a Done When item with NO corresponding code

### change-1: [category: A|B|C|D] [spec_item: "..."|none]
Description of the change and reasoning for classification.

### change-2: ...
(repeat for each distinct change)

If no spec context was provided, skip this section.

FIX VERIFICATION:
If the spec includes a Fix Summary section (from a prior fix attempt), \
verify each claim:
- FIXED claims: confirm the fix actually addresses the original issue
- WONT_FIX claims: evaluate whether the reasoning is valid
- PARTIAL claims: assess what remains and whether it's acceptable
Flag any false or unsubstantiated claims as critical issues."""

CHALLENGER_COUNTER_SYSTEM = """\
You are the same hostile code reviewer. The author has responded to \
your critique. For each rebutted issue, decide:

- CONCEDE: The author's rebuttal is technically correct. You were wrong \
or the issue is genuinely not a problem. Say why briefly.
- MAINTAIN: The author's rebuttal is insufficient, wrong, or misses \
the point. Restate your position with stronger evidence.

Do NOT concede just because the author sounds confident. Evaluate the \
technical merit. If the author hand-waves ("this is fine because...") \
without proving it, maintain your position.

Respond in this format:

## Summary
One-line assessment of how many rebuttals hold up.

## Counter-Rebuttals
### issue-1: CONCEDE
Brief reason why the author is right.

### issue-2: MAINTAIN
Why the rebuttal fails. Stronger evidence or a concrete scenario \
that breaks the code despite the author's argument.

(repeat for each rebutted issue)"""

AUTHOR_SYSTEM = """\
You are the author of the code under review. A challenger found \
potential issues. For each, either accept or rebut with technical reasoning.

Respond in this format:

## Summary
One-line overall response.

## Responses
### issue-1: ACCEPT
Reasoning why this is valid. Suggested fix if any.

### issue-2: REBUT
Technical reasoning why this critique is wrong.

(repeat for each issue)"""

ARBITER_SYSTEM = """\
You are a senior technical arbiter. The code author and a reviewer \
disagree on certain issues. Make a final ruling on each disputed point.

Respond in this format:

## Summary
One-line overall assessment.

## Rulings
### issue-1: CHALLENGER [confidence: high|medium|low]
Reasoning why the challenger is correct.

### issue-2: AUTHOR [confidence: high|medium|low]
Reasoning why the author is correct.

(repeat for each disputed issue)"""


# ---------------------------------------------------------------------------
# User prompt builders
# ---------------------------------------------------------------------------

def build_challenger_prompt(files: list[dict], spec_context: str = "") -> str:
    """Build user prompt with file contents and optional spec context."""
    # Detect if we're reviewing specs or code
    is_spec_review = all(f["path"].endswith(".md") for f in files) if files else False

    if is_spec_review:
        parts: list[str] = [
            "Find every flaw, gap, and weakness in this spec. "
            "Check: are Done When items concrete and automatable? Are there "
            "vague words (should, properly, correctly)? Are architecture decisions "
            "explicit with file paths and data structures? Are edge cases covered? "
            "Is anything missing that would block implementation? Are there "
            "invented requirements not grounded in the original vision?\n"
        ]
    else:
        parts = [
            "Find every flaw, gap, and weakness in this code. "
            "Check: correctness, error handling, security, edge cases, "
            "spec compliance, and whether the tests actually prove anything.\n"
        ]

    if spec_context:
        parts.append(f"## Spec context (Done-When criteria)\n{spec_context}\n")

    for f in files:
        lang = "markdown" if f["path"].endswith(".md") else "python"
        parts.append(f"## File: {f['path']}\n```{lang}\n{f['content']}\n```\n")
        if f.get("diff"):
            parts.append(f"### Recent diff\n```diff\n{f['diff']}\n```\n")

    return "\n".join(parts)


def build_author_prompt(files: list[dict], challenger_output: dict) -> str:
    """Build user prompt with original code and challenger's critique."""
    parts: list[str] = [
        "A challenger has reviewed your code and found potential issues. "
        "For each issue, either accept or rebut with technical reasoning.\n"
    ]

    parts.append("## Your code\n")
    for f in files:
        lang = "markdown" if f["path"].endswith(".md") else "python"
        parts.append(f"### {f['path']}\n```{lang}\n{f['content']}\n```\n")

    parts.append("## Challenger's findings\n")
    for issue in challenger_output.get("issues", []):
        iid = issue.get("id", "?")
        parts.append(f"### {iid}: [{issue.get('severity', 'medium')}] "
                      f"{issue.get('file', '')}:{issue.get('line', '?')}")
        parts.append(f"Category: {issue.get('category', 'unknown')}")
        parts.append(f"{issue.get('description', '')}\n")

    return "\n".join(parts)


def build_counter_rebuttal_prompt(
    challenger_output: dict, author_output: dict, round_num: int = 1
) -> str:
    """Build prompt for challenger to respond to author's rebuttals."""
    parts: list[str] = [
        f"Round {round_num + 1}: The author has rebutted your issues. "
        "Evaluate each rebuttal on technical merit.\n"
    ]

    responses_by_id: dict[str, dict] = {}
    for resp in author_output.get("responses", []):
        rid = resp.get("issue_id", resp.get("id", ""))
        responses_by_id[rid] = resp

    for issue in challenger_output.get("issues", []):
        iid = issue.get("id", "")
        resp = responses_by_id.get(iid)
        if not resp or resp.get("verdict") != "rebut":
            continue

        parts.append(f"## {iid}: [{issue.get('severity', 'medium')}] "
                      f"{issue.get('file', '')}:{issue.get('line', '?')}")
        parts.append(f"**Your critique:** {issue.get('description', '')}\n")
        parts.append(f"**Author's rebuttal:** {resp.get('reasoning', '')}\n")

    return "\n".join(parts)


def build_arbiter_prompt(challenger_output: dict, author_output: dict) -> str:
    """Build user prompt with only disputed issues and both positions."""
    rebutted_ids: set[str] = set()
    responses_by_id: dict[str, dict] = {}
    for resp in author_output.get("responses", []):
        rid = resp.get("issue_id", resp.get("id", ""))
        responses_by_id[rid] = resp
        if resp.get("verdict") == "rebut":
            rebutted_ids.add(rid)

    disputed_issues = [
        issue for issue in challenger_output.get("issues", [])
        if issue.get("id") in rebutted_ids
    ]

    parts: list[str] = [
        "The following issues are disputed between the challenger and the "
        "code author. Review both positions and make a final ruling.\n"
    ]

    for issue in disputed_issues:
        iid = issue["id"]
        rebuttal = responses_by_id.get(iid, {})
        parts.append(f"## {iid}")
        parts.append(f"**Challenger** ({issue.get('severity', 'unknown')} "
                      f"/ {issue.get('category', 'unknown')}):\n"
                      f"{issue.get('description', '')}\n")
        parts.append(f"**Author rebuttal**:\n{rebuttal.get('reasoning', '')}\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Markdown response parsers — extract structured data from model output
# ---------------------------------------------------------------------------

def parse_challenger_response(text: str) -> dict:
    """Parse markdown challenger response into structured dict."""
    result: dict = {"issues": [], "summary": "", "mission_assessment": None, "spec_alignment": []}

    # Extract summary
    summary_match = re.search(r"## Summary\s*\n(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    # Extract issues
    issue_pattern = re.compile(
        r"### (issue-\d+):\s*\[severity:\s*(critical|high|medium|low)\]\s*"
        r"\[file:\s*([^\]]+)\]\s*\n"
        r"Category:\s*(\S+)\s*\n"
        r"(.*?)(?=\n### issue-|\n## |\Z)",
        re.DOTALL
    )
    for m in issue_pattern.finditer(text):
        file_line = m.group(3).strip()
        file_path = file_line.rsplit(":", 1)[0] if ":" in file_line else file_line
        line_no = file_line.rsplit(":", 1)[1] if ":" in file_line else "0"
        result["issues"].append({
            "id": m.group(1),
            "severity": m.group(2),
            "file": file_path,
            "line": int(line_no) if line_no.isdigit() else 0,
            "category": m.group(4).strip(),
            "description": m.group(5).strip(),
        })

    # Extract mission assessment
    mission_match = re.search(
        r"## Mission Assessment\s*\n"
        r".*?\[(YES|PARTIAL|NO)\]\s*\n"
        r"Reasoning:\s*(.+?)(?=\n## |\Z)",
        text, re.DOTALL,
    )
    if mission_match:
        result["mission_assessment"] = {
            "verdict": mission_match.group(1),
            "reasoning": mission_match.group(2).strip(),
        }

    # Extract spec alignment classifications
    alignment_pattern = re.compile(
        r"### (change-\d+):\s*\[category:\s*(A|B|C|D)\]\s*\[spec_item:\s*([^\]]*)\]\s*\n"
        r"(.*?)(?=\n### change-|\n## |\Z)",
        re.DOTALL
    )
    for m in alignment_pattern.finditer(text):
        result["spec_alignment"].append({
            "id": m.group(1),
            "category": m.group(2),
            "spec_item": m.group(3).strip().strip('"'),
            "description": m.group(4).strip(),
        })

    return result


def parse_counter_rebuttal_response(text: str) -> dict:
    """Parse markdown counter-rebuttal response into structured dict."""
    result: dict = {"counter_rebuttals": [], "summary": ""}

    summary_match = re.search(r"## Summary\s*\n(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    cr_pattern = re.compile(
        r"### (issue-\d+):\s*(CONCEDE|MAINTAIN)\s*\n(.*?)(?=\n### issue-|\n## |\Z)",
        re.DOTALL
    )
    for m in cr_pattern.finditer(text):
        result["counter_rebuttals"].append({
            "issue_id": m.group(1),
            "verdict": m.group(2).lower(),
            "reasoning": m.group(3).strip(),
        })

    conceded = sum(1 for cr in result["counter_rebuttals"] if cr["verdict"] == "concede")
    maintained = sum(1 for cr in result["counter_rebuttals"] if cr["verdict"] == "maintain")
    result["conceded_count"] = conceded
    result["maintained_count"] = maintained
    result["maintained_ids"] = [cr["issue_id"] for cr in result["counter_rebuttals"]
                                 if cr["verdict"] == "maintain"]

    return result


def parse_author_response(text: str) -> dict:
    """Parse markdown author response into structured dict."""
    result: dict = {"responses": [], "summary": ""}

    summary_match = re.search(r"## Summary\s*\n(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    response_pattern = re.compile(
        r"### (issue-\d+):\s*(ACCEPT|REBUT)\s*\n(.*?)(?=\n### issue-|\n## |\Z)",
        re.DOTALL
    )
    for m in response_pattern.finditer(text):
        result["responses"].append({
            "issue_id": m.group(1),
            "verdict": m.group(2).lower(),
            "reasoning": m.group(3).strip(),
        })

    accepted = sum(1 for r in result["responses"] if r["verdict"] == "accept")
    rebutted = sum(1 for r in result["responses"] if r["verdict"] == "rebut")
    result["accepted_count"] = accepted
    result["rebutted_count"] = rebutted
    result["unresolved"] = [r["issue_id"] for r in result["responses"]
                            if r["verdict"] == "rebut"]

    return result


def parse_arbiter_response(text: str) -> dict:
    """Parse markdown arbiter response into structured dict."""
    result: dict = {"rulings": [], "summary": ""}

    summary_match = re.search(r"## Summary\s*\n(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    ruling_pattern = re.compile(
        r"### (issue-\d+):\s*(CHALLENGER|AUTHOR)\s*\[confidence:\s*(high|medium|low)\]\s*\n"
        r"(.*?)(?=\n### issue-|\n## |\Z)",
        re.DOTALL
    )
    for m in ruling_pattern.finditer(text):
        result["rulings"].append({
            "issue_id": m.group(1),
            "side": m.group(2).lower(),
            "confidence": m.group(3),
            "reasoning": m.group(4).strip(),
        })

    return result
