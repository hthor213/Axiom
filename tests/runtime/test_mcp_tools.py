"""Tests for MCP tool definitions and handlers."""

from __future__ import annotations

import json
import os
import pytest

from lib.python.runtime.mcp_tools import (
    harness_check_tool_definition,
    run_harness_check,
    handle_mcp_tool_call,
    get_all_tool_definitions,
)


class TestToolDefinitions:

    def test_harness_check_definition_structure(self):
        defn = harness_check_tool_definition()
        assert defn["name"] == "platform_harness_check"
        assert "description" in defn
        assert "input_schema" in defn
        schema = defn["input_schema"]
        assert "spec_number" in schema["properties"]
        assert "project_root" in schema["properties"]
        assert schema["required"] == ["spec_number", "project_root"]

    def test_get_all_tools(self):
        tools = get_all_tool_definitions()
        assert len(tools) >= 1
        names = [t["name"] for t in tools]
        assert "platform_harness_check" in names


class TestHarnessCheck:

    def test_nonexistent_spec(self, tmp_path):
        """Harness check on nonexistent spec returns error gracefully."""
        os.makedirs(tmp_path / "specs", exist_ok=True)
        result = run_harness_check("999", str(tmp_path))
        assert result["total"] == 0
        assert "error" in result or result["passed"] == 0

    def test_with_real_spec(self, tmp_path):
        """Harness check on a simple spec with file_exists check."""
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec = specs_dir / "001-test.md"
        spec.write_text(
            "# 001: Test Spec\n\n"
            "**Status:** active\n\n"
            "## Done When\n"
            "- [ ] `specs/001-test.md` exists\n"
            "- [ ] Some judgment item\n"
        )
        result = run_harness_check("001", str(tmp_path))
        assert result["total"] == 2
        assert result["passed"] >= 1  # file_exists should pass


class TestMCPHandler:

    def test_handle_harness_check(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "001-test.md").write_text(
            "# 001: Test\n**Status:** active\n## Done When\n- [ ] judgment item\n"
        )
        result_json = handle_mcp_tool_call(
            "platform_harness_check",
            {"spec_number": "001", "project_root": str(tmp_path)},
            str(tmp_path),
        )
        result = json.loads(result_json)
        assert "total" in result

    def test_handle_unknown_tool(self, tmp_path):
        result_json = handle_mcp_tool_call("unknown_tool", {}, str(tmp_path))
        result = json.loads(result_json)
        assert "error" in result
