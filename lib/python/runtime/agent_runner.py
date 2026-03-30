"""Agent subprocess lifecycle — launching and monitoring Claude CLI sessions.

Handles the mechanics of running Claude CLI as a subprocess,
including startup watchdog, output parsing, and fix sessions.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .db import Task, AgentSession


def find_claude_binary() -> str:
    """Resolve the claude CLI binary path.

    Checks PATH first, then common Homebrew locations.
    Raises RuntimeError if not found.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        for candidate in ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                claude_bin = candidate
                break
    if not claude_bin:
        raise RuntimeError("claude CLI not found in PATH or common locations")
    return claude_bin


def get_env_with_homebrew() -> dict:
    """Return a copy of os.environ with Homebrew paths prepended."""
    env = os.environ.copy()
    homebrew_paths = "/opt/homebrew/bin:/opt/homebrew/opt/node/bin"
    if homebrew_paths not in env.get("PATH", ""):
        env["PATH"] = homebrew_paths + ":" + env.get("PATH", "")
    return env


def _extract_text_from_stream(output: str) -> str:
    """Extract accumulated text from stream-json output."""
    text = ""
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            envelope = json.loads(line)
            event = envelope.get("event", {})
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text += delta.get("text", "")
        except (json.JSONDecodeError, TypeError):
            pass
    return text.strip()


def run_agent_session(task: Task, session: AgentSession, worktree,
                      store, config, emit_fn: Callable,
                      prompt: str) -> int:
    """Run a Claude Agent SDK session for a task.

    This is where the actual building happens. The agent gets:
    - The task description (Done When item)
    - The spec context
    - Access to MCP tools (harness check)
    - A git worktree to work in

    Returns the number of turns used.
    """
    try:
        claude_bin = find_claude_binary()
    except RuntimeError as e:
        store.update_session(
            session.id,
            status="failed",
            error=str(e),
        )
        raise

    env = get_env_with_homebrew()

    try:
        # Use Popen for startup watchdog — detect stuck processes early
        startup_timeout_sec = 120  # 2 minutes to produce first output
        total_timeout_sec = session.time_limit_min * 60

        proc = subprocess.Popen(
            [
                claude_bin,
                "-p", prompt,
                "--dangerously-skip-permissions",
                "--max-turns", str(session.max_turns),
                # Stream JSON so output appears incrementally — without this,
                # -p buffers the entire response and the startup watchdog kills
                # long-running tasks (e.g. draft reviews ~174s) before first byte.
                "--output-format", "stream-json",
                "--verbose",
            ],
            cwd=worktree.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        start = time.monotonic()
        got_output = False
        stdout_chunks = []
        stderr_chunks = []

        while proc.poll() is None:
            elapsed = time.monotonic() - start

            # Startup watchdog: if no output (stdout OR stderr) after 2 minutes,
            # the process is genuinely stuck (not just retrying on overload).
            if not got_output and elapsed > startup_timeout_sec:
                proc.kill()
                proc.wait(timeout=10)
                # Drain stderr so we can store the reason (e.g. API error message)
                try:
                    _, stderr_out = proc.communicate(timeout=5)
                except Exception:
                    stderr_out = ""
                stderr_hint = f" stderr: {stderr_out[:300]}" if stderr_out else ""
                store.update_session(
                    session.id,
                    status="failed",
                    error=(
                        f"Startup timeout — no output after {startup_timeout_sec}s."
                        f" Process killed.{stderr_hint}"
                    ),
                )
                emit_fn("task_error", {
                    "task_id": task.id,
                    "error": "startup_timeout",
                })
                return 0

            # Total time limit
            if elapsed > total_timeout_sec:
                proc.kill()
                proc.wait(timeout=10)
                store.update_session(
                    session.id,
                    status="killed",
                    error=f"Time limit exceeded ({session.time_limit_min}min)",
                )
                return session.max_turns

            # Non-blocking read with 5s poll interval.
            # Watch both stdout AND stderr — stderr activity (e.g. retry messages
            # while the API is overloaded) counts as "got output" so we don't
            # falsely trigger the startup watchdog during a legitimate retry.
            try:
                fds = [f for f in [proc.stdout, proc.stderr] if f and f.readable()]
                if fds:
                    ready, _, _ = select.select(fds, [], [], 5.0)
                    for fd in ready:
                        chunk = fd.read(4096)
                        if chunk:
                            if fd is proc.stdout:
                                stdout_chunks.append(chunk)
                            else:
                                stderr_chunks.append(chunk)
                            if not got_output:
                                got_output = True
                                emit_fn("agent_output", {
                                    "task_id": task.id,
                                    "event": "first_output",
                                    "elapsed_sec": int(elapsed),
                                })
                else:
                    time.sleep(5)
            except (IOError, OSError):
                time.sleep(5)

        # Process finished — collect remaining output
        remaining_out, remaining_err = proc.communicate(timeout=10)
        if remaining_out:
            stdout_chunks.append(remaining_out)
        if remaining_err:
            stderr_chunks.append(remaining_err)

        output = "".join(stdout_chunks)
        stderr_output = "".join(stderr_chunks)

        # With --output-format stream-json, stdout is JSONL.
        # Count tool_use events from content_block_start lines.
        # Each such event = one tool call = one turn.
        turns = 0
        last_text = ""
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                envelope = json.loads(line)
                event = envelope.get("event", {})
                etype = event.get("type", "")
                if etype == "content_block_start":
                    cb = event.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        turns += 1
                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        last_text += delta.get("text", "")
            except (json.JSONDecodeError, TypeError):
                pass
        turns = max(turns, 1)  # At least 1 turn if process ran

        # Store the last portion of extracted text (or raw output as fallback)
        display_output = last_text[-500:] if last_text else output[-500:]
        if stderr_output:
            display_output += f"\n[stderr] {stderr_output[-200:]}"

        store.update_session(
            session.id,
            last_output=display_output[-500:],
            turns_used=turns,
        )

        return turns

    except subprocess.TimeoutExpired:
        store.update_session(
            session.id,
            status="killed",
            error=f"Time limit exceeded ({session.time_limit_min}min)",
        )
        return session.max_turns
    except FileNotFoundError:
        store.update_session(
            session.id,
            status="failed",
            error=f"claude CLI not executable at {claude_bin}",
        )
        raise RuntimeError(f"claude CLI not executable at {claude_bin}")


def run_plan_session(task: Task, worktree, config,
                     emit_fn: Callable, prompt: str) -> str:
    """Run a Claude CLI session in plan mode to generate a build plan.

    Uses --permission-mode plan so Claude reads the codebase and plans
    without executing any tool calls. Returns the plan text.
    """
    claude_bin = find_claude_binary()
    env = get_env_with_homebrew()

    startup_timeout_sec = 60
    total_timeout_sec = 300  # 5 minutes max for plan generation

    proc = subprocess.Popen(
        [claude_bin, "-p", prompt, "--permission-mode", "plan",
         "--max-turns", "5", "--output-format", "stream-json", "--verbose"],
        cwd=worktree.path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )

    start = time.monotonic()
    got_output = False
    stdout_chunks: list[str] = []

    while proc.poll() is None:
        elapsed = time.monotonic() - start
        if not got_output and elapsed > startup_timeout_sec:
            proc.kill()
            proc.wait(timeout=10)
            emit_fn("plan_error", {"task_id": task.id, "error": "startup_timeout"})
            return ""
        if elapsed > total_timeout_sec:
            proc.kill()
            proc.wait(timeout=10)
            return ""
        try:
            fds = [f for f in [proc.stdout, proc.stderr] if f and f.readable()]
            ready = select.select(fds, [], [], 5.0)[0] if fds else []
            for fd in ready:
                chunk = fd.read(4096)
                if chunk:
                    if fd is proc.stdout:
                        stdout_chunks.append(chunk)
                    got_output = True
        except (IOError, OSError):
            time.sleep(2)

    remaining_out, _ = proc.communicate(timeout=10)
    if remaining_out:
        stdout_chunks.append(remaining_out)

    return _extract_text_from_stream("".join(stdout_chunks))


def run_fix_session(task: Task, worktree, feedback: str, config) -> int:
    """Run a Claude session to fix adversarial review issues.

    Shorter session (half the turns) focused on applying fixes
    in the existing worktree.
    """
    from .prompts import build_fix_prompt
    prompt = build_fix_prompt(task.spec_number, feedback)

    claude_bin = find_claude_binary()
    env = get_env_with_homebrew()

    fix_max_turns = max(config.max_turns_per_task // 2, 10)

    try:
        result = subprocess.run(
            [
                claude_bin,
                "-p", prompt,
                "--dangerously-skip-permissions",
                "--max-turns", str(fix_max_turns),
            ],
            cwd=worktree.path,
            capture_output=True,
            text=True,
            timeout=config.time_limit_per_task_min * 60,
            env=env,
        )

        output = result.stdout
        turns = output.count("Tool:") + output.count("tool_use") + 1
        return turns

    except subprocess.TimeoutExpired:
        return fix_max_turns
