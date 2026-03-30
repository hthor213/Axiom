"""Verification helpers for the ship pipeline.

Test discovery, spec drift checks, and BACKLOG hygiene checks.
Extracted from pipeline.py to keep files under the 350-line cap.
"""

from __future__ import annotations

import os
import subprocess
import time


def _run_cmd(args: list[str], cwd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=args, returncode=-1,
                                           stdout="", stderr="Timed out")
    except (FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(args=args, returncode=-1,
                                           stdout="", stderr=str(e))


def _read_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


def discover_and_run_tests(root: str) -> tuple[bool, str]:
    """Discover and run test suites. Returns (passed, detail)."""
    runners_found = []

    if os.path.isfile(os.path.join(root, "pytest.ini")):
        runners_found.append(("pytest", ["python", "-m", "pytest", "-v"]))
    elif os.path.isfile(os.path.join(root, "pyproject.toml")):
        content = _read_file(os.path.join(root, "pyproject.toml"))
        if "[tool.pytest" in content:
            runners_found.append(("pytest", ["python", "-m", "pytest", "-v"]))

    makefile = os.path.join(root, "Makefile")
    if os.path.isfile(makefile):
        content = _read_file(makefile)
        if "\ntest:" in content or content.startswith("test:"):
            runners_found.append(("make", ["make", "test"]))

    pkg_json = os.path.join(root, "package.json")
    if os.path.isfile(pkg_json):
        import json
        try:
            data = json.loads(_read_file(pkg_json))
            if "test" in data.get("scripts", {}):
                runners_found.append(("npm", ["npm", "test"]))
        except (json.JSONDecodeError, KeyError):
            pass

    env_cmd = os.environ.get("SHIP_TEST_COMMAND", "")
    if env_cmd:
        runners_found.append(("custom", ["sh", "-c", env_cmd]))

    if not runners_found:
        return True, "No test suite discovered"

    results = []
    for name, cmd in runners_found:
        r = _run_cmd(cmd, cwd=root, timeout=300)
        if r.returncode == 0:
            results.append(f"{name}: passed")
        else:
            output = (r.stdout + r.stderr).strip()[-500:]
            return False, f"{name}: FAILED\n{output}"

    return True, "; ".join(results)


def check_spec_drift(root: str) -> str:
    """Check spec drift -- advisory, non-blocking. Returns warning or empty."""
    import glob as g
    import re
    specs = g.glob(os.path.join(root, "specs", "000-*.md"))
    warnings = []
    now = time.time()
    threshold = 30 * 86400  # 30 days

    for spec_path in specs:
        content = _read_file(spec_path)
        spec_name = os.path.basename(spec_path)

        # Check last_updated date
        for line in content.splitlines():
            if line.strip().lower().startswith("last_updated:"):
                date_str = line.split(":", 1)[1].strip()
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str)
                    age = now - dt.timestamp()
                    if age > threshold:
                        days = int(age / 86400)
                        warnings.append(
                            f"{spec_name}: last_updated {days} days ago"
                        )
                except (ValueError, TypeError):
                    pass

        # Check for referenced files that don't exist
        for match in re.finditer(r"`([^`]+\.[a-zA-Z]{1,6})`", content):
            ref = match.group(1)
            # Only check relative-looking paths (no spaces, no URLs)
            if "/" in ref and not ref.startswith("http") and " " not in ref:
                full_path = os.path.join(root, ref)
                if not os.path.exists(full_path):
                    warnings.append(
                        f"{spec_name}: referenced file missing: {ref}"
                    )

    return "; ".join(warnings) if warnings else ""


def check_backlog(root: str) -> str:
    """Check BACKLOG.md hygiene -- advisory. Returns warning or empty."""
    path = os.path.join(root, "BACKLOG.md")
    if not os.path.isfile(path):
        return ""
    content = _read_file(path)
    lines = content.splitlines()
    in_todo_or_progress = False
    checked_items: list[str] = []
    done_section = False
    done_items: list[str] = []

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("## ") or stripped.startswith("# "):
            heading = stripped.lstrip("# ").strip()
            if "to do" in heading or "in progress" in heading:
                in_todo_or_progress = True
                done_section = False
            elif "done" in heading:
                done_section = True
                in_todo_or_progress = False
            else:
                in_todo_or_progress = False
                done_section = False

        if in_todo_or_progress and line.strip().startswith("- [x]"):
            item = line.strip()[5:].strip()
            checked_items.append(item)
        if done_section and line.strip().startswith("- "):
            done_items.append(line.strip()[2:].strip().lower())

    missing = [
        item for item in checked_items
        if item.lower() not in " ".join(done_items)
    ]
    if missing:
        return f"BACKLOG: {len(missing)} checked items not in Done section"
    return ""
