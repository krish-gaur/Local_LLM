"""Postcondition verification based on actual results, not model assertions."""
from __future__ import annotations

from localpilot.agent.types import Json
from localpilot.tools.base import Tool, ToolResult


class Verifier:
    def verify(self, tool: Tool, arguments: dict[str, Json], result: ToolResult,
               expected: dict[str, Json]) -> tuple[bool, str]:
        if not result.ok:
            return False, result.error.message if result.error else "tool failed without an error"
        if tool.verifier is not None:
            return tool.verifier(arguments, result, expected)
        if isinstance(result.data, dict):
            for key, wanted in expected.items():
                if result.data.get(key) != wanted:
                    return False, f"postcondition failed: {key} != {wanted!r}"
        elif expected:
            return False, "tool has no structured data for expected postconditions"
        return True, "verified"
