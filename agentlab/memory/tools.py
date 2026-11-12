"""The memory tool the assistant gets when memory is on: forget_memory (TEXTBOOK §7: deletion on request)."""
from __future__ import annotations

import json

from agentlab.memory.store import MemoryStore
from agentlab.tools.base import Tool
from agentlab.tools.errors import ToolError


def make_memory_tools(store: MemoryStore, customer_id: int) -> list[Tool]:
    def forget_memory(memory_id: int):
        if not store.forget(customer_id, memory_id):      # bound to this customer: other ids look like missing ones
            raise ToolError(f"No saved memory m{memory_id} for this customer. The ids are shown as [m<id>] in "
                            f"customer_memory; if it isn't listed there, there is nothing to forget.")
        # why the note: the memory block in the system prompt was rendered at session start and isn't re-rendered
        # mid-conversation (that would break the cache); the model must be told the line is now void
        return json.dumps({"forgotten": True, "memory_id": memory_id,
                           "note": f"m{memory_id} is deleted. It still appears in customer_memory for the rest of "
                                   f"this conversation; ignore it."})

    return [Tool("forget_memory",
                 "Permanently delete one saved memory about this customer. Use when the customer asks you to forget "
                 "something, or says a saved memory is wrong. Takes the number from the [m<id>] label in "
                 "customer_memory (for [m12], pass 12). Returns {forgotten: true, memory_id}. Deletion can't be "
                 "undone; to record a corrected preference, just state it in your reply.",
                 {"type": "object", "properties": {"memory_id": {"type": "integer", "description":
                  "id from the [m<id>] label, e.g. 12"}}, "required": ["memory_id"], "additionalProperties": False},
                 forget_memory, side_effects=True)]
