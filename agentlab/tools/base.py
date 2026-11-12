"""Tools: a name, a description and a schema the model reads, plus a function it never sees.

Execution never raises into the loop: every failure becomes an error ToolResultBlock with a message
the model can act on (TEXTBOOK §5, "errors are data").
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from agentlab.llm.types import ToolResultBlock, ToolSpec, ToolUseBlock
from agentlab.tools.errors import ToolError

_TYPES = {
    "string": lambda v: isinstance(v, str),
    # why: bool is a subclass of int in Python, but a model sending true for an order id is an error
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]
    side_effects: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.input_schema)


def _check_value(field: str, schema: dict, v: Any) -> list[str]:
    problems: list[str] = []
    t = schema.get("type")
    if t and t in _TYPES and not _TYPES[t](v):
        return [f"{field}: expected {t}, got {type(v).__name__} {v!r}"[:200]]
    if "enum" in schema and v not in schema["enum"]:
        problems.append(f"{field}: must be one of {schema['enum']}, got {v!r}")
    if t in ("integer", "number"):
        if "minimum" in schema and v < schema["minimum"]:
            problems.append(f"{field}: must be >= {schema['minimum']} (minimum), got {v}")
        if "maximum" in schema and v > schema["maximum"]:
            problems.append(f"{field}: must be <= {schema['maximum']} (maximum), got {v}")
    if t == "string":
        if "minLength" in schema and len(v) < schema["minLength"]:
            problems.append(f"{field}: must be at least {schema['minLength']} characters")
        if "maxLength" in schema and len(v) > schema["maxLength"]:
            problems.append(f"{field}: must be at most {schema['maxLength']} characters")
    if t == "array" and "items" in schema:
        for i, item in enumerate(v):
            problems += _check_value(f"{field}[{i}]", schema["items"], item)
    return problems


def validate_args(schema: dict, args: dict) -> list[str]:
    """Validate a model's arguments against the course's JSON Schema subset. Returns problems ([] = valid)."""
    if not isinstance(args, dict):
        return [f"arguments must be an object, got {type(args).__name__}"]
    props = schema.get("properties", {})
    problems = [f"missing required field '{r}'" for r in schema.get("required", []) if r not in args]
    for k, v in args.items():
        if k not in props:
            if schema.get("additionalProperties") is False:
                problems.append(f"unexpected field '{k}' (allowed: {sorted(props)})")
            continue
        problems += _check_value(k, props[k], v)
    return problems


class ToolRegistry:
    def __init__(self, tools: list[Tool], invalid_formatter: Callable[[str, list[str]], str] | None = None) -> None:
        # invalid_formatter(tool_name, problems) -> content for argument-validation errors (Node 05: one error shape)
        self._invalid_formatter = invalid_formatter
        self._tools: dict[str, Tool] = {}
        for t in tools:
            if t.name in self._tools:
                raise ValueError(f"duplicate tool name {t.name!r}")
            self._tools[t.name] = t

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        # why: tools sit at the start of the prompt; a stable order keeps the prompt cache valid (Node 01 §3)
        return [self._tools[n].spec() for n in self.names()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def execute(self, call: ToolUseBlock) -> ToolResultBlock:
        from shopfront.services import ShopError   # local import: tools/ shouldn't hard-depend on shopfront
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResultBlock(call.id, f"Unknown tool '{call.name}'. Available tools: {', '.join(self.names())}.",
                                   is_error=True)
        problems = validate_args(tool.input_schema, call.input)
        if problems:
            if self._invalid_formatter:
                return ToolResultBlock(call.id, self._invalid_formatter(call.name, problems), is_error=True)
            return ToolResultBlock(call.id, f"Invalid arguments for {call.name}: " + "; ".join(problems), is_error=True)
        try:
            value = tool.fn(**call.input)
        except ToolError as e:
            return ToolResultBlock(call.id, str(e), is_error=True)    # message written for the model; show as-is
        except ShopError as e:
            return ToolResultBlock(call.id, json.dumps(e.to_dict()), is_error=True)
        except Exception as e:  # noqa: BLE001 - a tool bug must not crash the agent
            return ToolResultBlock(call.id, f"Tool {call.name} failed: {type(e).__name__}: {e}", is_error=True)
        content = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
        return ToolResultBlock(call.id, content)
