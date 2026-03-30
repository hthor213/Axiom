"""MCP tool definitions for Claude Agent SDK sessions.

Exposes hth-platform harness check and other deterministic tools
that agents can call during their build sessions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional


def harness_check_tool_definition() -> dict:
    """Return the MCP tool definition for hth-platform harness check.

    This is passed to the Claude Agent SDK so the agent can
    self-verify against spec Done When criteria during the build.
    """
    return {
        "name": "platform_harness_check",
        "description": (
            "Run hth-platform harness check against a spec to verify Done When criteria. "
            "Returns which items pass, fail, or need judgment. "
            "Use this to verify your work against the spec before declaring a task complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spec_number": {
                    "type": "string",
                    "description": "The spec number to check (e.g., '014')",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to the project root directory",
                },
            },
            "required": ["spec_number", "project_root"],
        },
    }


def run_harness_check(spec_number: str, project_root: str) -> dict:
    """Execute harness check for a spec.

    This is the implementation that backs the MCP tool.
    It calls the harness spec_check module directly.

    Args:
        spec_number: Spec number (e.g., "014").
        project_root: Project root directory.

    Returns:
        Dict with check results: {spec_path, items, passed, failed, judgment, total}.
    """
    # Add the library path so we can import harness modules
    lib_path = os.path.join(project_root, "lib", "python")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    try:
        from harness.spec_check import check_spec

        # Find the spec file
        specs_dir = os.path.join(project_root, "specs")
        spec_file = None
        if os.path.isdir(specs_dir):
            for fname in os.listdir(specs_dir):
                if fname.startswith(f"{spec_number}-") and fname.endswith(".md"):
                    spec_file = os.path.join(specs_dir, fname)
                    break

        if not spec_file:
            return {
                "error": f"Spec file not found for spec:{spec_number}",
                "passed": 0,
                "failed": 0,
                "judgment": 0,
                "total": 0,
            }

        return check_spec(spec_file, project_root)
    except Exception as e:
        return {
            "error": str(e),
            "passed": 0,
            "failed": 0,
            "judgment": 0,
            "total": 0,
        }


def handle_mcp_tool_call(tool_name: str, tool_input: dict, project_root: str) -> str:
    """Handle an MCP tool call from the agent.

    Args:
        tool_name: Name of the tool being called.
        tool_input: Input parameters for the tool.
        project_root: Default project root.

    Returns:
        JSON string with the tool result.
    """
    if tool_name == "platform_harness_check":
        spec_number = tool_input.get("spec_number", "")
        root = tool_input.get("project_root", project_root)
        result = run_harness_check(spec_number, root)
        return json.dumps(result, indent=2)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def get_all_tool_definitions() -> list[dict]:
    """Return all MCP tool definitions for agent sessions."""
    return [
        harness_check_tool_definition(),
    ]
