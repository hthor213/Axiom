"""Markdown parsing helpers for spec files and session state files."""

from __future__ import annotations

import os
import re
from typing import Optional


def extract_done_when(spec_path: str) -> list[dict]:
    """Parse a spec markdown file and extract Done When checklist items.

    Returns list of dicts with keys: text, checked, raw_line.
    """
    try:
        with open(spec_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    in_done_when = False
    items: list[dict] = []

    for line in lines:
        stripped = line.strip()

        # Detect start of Done When section
        if re.match(r"^##\s+Done\s+When\b", stripped, re.IGNORECASE):
            in_done_when = True
            continue

        # A new h2 section ends Done When
        if in_done_when and re.match(r"^##\s+", stripped):
            break

        if not in_done_when:
            continue

        # Match checklist items: - [ ] or - [x]
        m = re.match(r"^-\s+\[([ xX])\]\s+(.+)$", stripped)
        if m:
            checked = m.group(1).lower() == "x"
            text = m.group(2).strip()
            items.append({
                "text": text,
                "checked": checked,
                "raw_line": stripped,
            })

    return items


def extract_spec_status(spec_path: str) -> str:
    """Parse the **Status:** line from a spec file.

    Returns one of: 'draft', 'active', 'done', or 'unknown'.
    """
    try:
        with open(spec_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return "unknown"

    m = re.search(r"\*\*Status:\*\*\s*(draft|active|done)", content, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return "unknown"


def extract_spec_number(filename: str) -> str:
    """Extract the spec number from a filename.

    '003-validation-tiers.md' -> '003'
    """
    basename = os.path.basename(filename)
    m = re.match(r"^(\d{3})-", basename)
    if m:
        return m.group(1)
    return ""


def extract_spec_title(spec_path: str) -> str:
    """Extract the title from the first H1 heading in a spec file."""
    try:
        with open(spec_path, "r") as f:
            for line in f:
                m = re.match(r"^#\s+(.+)$", line.strip())
                if m:
                    return m.group(1).strip()
    except FileNotFoundError:
        pass
    return ""


def scan_active_specs(specs_dir: str) -> list[dict]:
    """Scan specs/ directory, return list of specs with status=active.

    Each dict has keys: path, number, title, status.
    """
    if not os.path.isdir(specs_dir):
        return []

    results: list[dict] = []
    for fname in sorted(os.listdir(specs_dir)):
        if not fname.endswith(".md"):
            continue
        number = extract_spec_number(fname)
        if not number:
            continue

        fpath = os.path.join(specs_dir, fname)
        status = extract_spec_status(fpath)
        if status == "active":
            title = extract_spec_title(fpath)
            results.append({
                "path": fpath,
                "number": number,
                "title": title,
                "status": status,
            })

    return results


def count_current_tasks(tasks_path: str) -> int:
    """Count items under '## Active' section in CURRENT_TASKS.md."""
    try:
        with open(tasks_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return 0

    in_active = False
    count = 0

    for line in lines:
        stripped = line.strip()

        if re.match(r"^##\s+Active\b", stripped, re.IGNORECASE):
            in_active = True
            continue

        if in_active and re.match(r"^##\s+", stripped):
            break

        if in_active and re.match(r"^-\s+", stripped):
            count += 1

    return count
