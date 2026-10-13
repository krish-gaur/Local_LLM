"""Safe structured tool interface and small JSON-schema validator."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Any, Callable, Mapping

from localpilot.agent.types import AgentError, Json


class PermissionClass(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXECUTION = "execution"
    SENSITIVE = "sensitive"


@dataclass(frozen=True, slots=True)
class ToolContext:
    cancellation: threading.Event

    def raise_if_cancelled(self) -> None:
        if self.cancellation.is_set():
            raise ToolFailure(AgentError("cancelled", "operation cancelled", False))


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: Json = None
    error: AgentError | None = None
    metadata: Mapping[str, Json] = field(default_factory=dict)

    @classmethod
    def success(cls, data: Json = None, **metadata: Json) -> "ToolResult":
        return cls(True, data, metadata=metadata)

    @classmethod
    def failure(cls, code: str, message: str, recoverable: bool = False) -> "ToolResult":
        return cls(False, error=AgentError(code, message, recoverable))


class ToolFailure(RuntimeError):
    def __init__(self, error: AgentError):
        super().__init__(error.message)
        self.error = error


Verifier = Callable[[dict[str, Json], ToolResult, dict[str, Json]], tuple[bool, str]]


class Tool(ABC):
    name: str
    description: str
    schema: dict[str, Json]
    permission: PermissionClass
    timeout_seconds: float = 10.0
    verifier: Verifier | None = None

    @abstractmethod
    def execute(self, arguments: dict[str, Json], context: ToolContext) -> ToolResult:
        pass


def validate_schema(schema: object, location: str = "schema") -> list[str]:
    """Validate the supported JSON Schema subset without executing a tool."""
    if not isinstance(schema, dict): return [f"{location}: invalid schema"]
    supported = {"string", "integer", "number", "boolean", "array", "object", "null"}
    expected = schema.get("type", "object" if "properties" in schema else None)
    if expected not in supported: return [f"{location}: unsupported or missing schema type"]
    errors: list[str] = []
    if expected == "object":
        properties, required = schema.get("properties", {}), schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list): return [f"{location}: invalid object schema"]
        if not all(isinstance(item, str) and item in properties for item in required):
            errors.append(f"{location}: invalid required properties")
        for name, child in properties.items(): errors.extend(validate_schema(child, f"{location}.{name}"))
        extra = schema.get("additionalProperties", False)
        if isinstance(extra, dict): errors.extend(validate_schema(extra, f"{location}.*"))
        elif not isinstance(extra, bool): errors.append(f"{location}: invalid additionalProperties")
    if expected == "array":
        if "items" not in schema: errors.append(f"{location}: array schema requires items")
        else: errors.extend(validate_schema(schema["items"], f"{location}.items"))
    if "enum" in schema and not isinstance(schema["enum"], list): errors.append(f"{location}: invalid enum")
    return errors


def validate_arguments(schema: dict[str, Json], values: dict[str, Json]) -> list[str]:
    """Validate a fail-closed JSON Schema subset used by local and discovered MCP tools."""
    schema_errors = validate_schema(schema)
    if schema_errors: return schema_errors
    errors: list[str] = []
    type_map: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "string": str, "integer": int, "number": (int, float), "boolean": bool,
        "array": list, "object": dict, "null": type(None),
    }

    def visit(spec: object, value: object, location: str) -> None:
        if not isinstance(spec, dict):
            errors.append(f"{location}: invalid schema")
            return
        expected = spec.get("type", "object" if "properties" in spec else None)
        if expected not in type_map:
            errors.append(f"{location}: unsupported or missing schema type")
            return
        wanted = type_map[str(expected)]
        if not isinstance(value, wanted) or expected in {"integer", "number"} and isinstance(value, bool):
            errors.append(f"{location} must be {expected}")
            return
        if "enum" in spec and (not isinstance(spec["enum"], list) or value not in spec["enum"]):
            errors.append(f"{location} is not an allowed value")
        if isinstance(value, str):
            maximum = spec.get("maxLength")
            if isinstance(maximum, int) and len(value) > maximum: errors.append(f"{location} exceeds maxLength")
        if isinstance(value, list):
            maximum = spec.get("maxItems")
            if isinstance(maximum, int) and len(value) > maximum: errors.append(f"{location} exceeds maxItems")
            item_spec = spec.get("items")
            if item_spec is None: errors.append(f"{location}: array schema requires items")
            else:
                for index, item in enumerate(value): visit(item_spec, item, f"{location}[{index}]")
        if isinstance(value, dict):
            properties, required = spec.get("properties", {}), spec.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list):
                errors.append(f"{location}: invalid object schema")
                return
            for key in required:
                if not isinstance(key, str) or key not in value: errors.append(f"missing required argument: {location}.{key}")
            extra_rule = spec.get("additionalProperties", False)
            for key, child in value.items():
                child_spec = properties.get(key)
                if child_spec is None:
                    if extra_rule is False: errors.append(f"unknown argument: {location}.{key}")
                    elif isinstance(extra_rule, dict): visit(extra_rule, child, f"{location}.{key}")
                    elif extra_rule is not True: errors.append(f"{location}: invalid additionalProperties")
                else: visit(child_spec, child, f"{location}.{key}")

    visit(schema, values, "arguments")
    return errors
