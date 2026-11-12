"""Provider-neutral types: the CONTRACT between your agent code and any model provider.

Everything in agentlab speaks these types. Provider adapters (you write them in Node 02)
translate to and from each vendor's wire format. This file is given, not written by you,
because every later node and every test depends on it; Node 02 YOU_DO asks you to critique it.

Design notes (see nodes/02-agent-loop/TEXTBOOK.md §4):
- Content is a list of typed blocks, not a string. Tool calls, tool results, images and
  reasoning are all blocks. This mirrors Anthropic's format and is a superset of OpenAI Chat's.
- Tool results are sent back with role "user" (Anthropic convention). The OpenAI adapter
  converts them to role "tool" messages.
- Round-trip fidelity: some providers attach opaque data that MUST come back unchanged on the
  next request (Anthropic thinking signatures, OpenRouter `reasoning_details`, Gemini thought
  signatures). `provider_data` fields carry it; `provider` says whose it is, so an adapter can
  drop blocks that belong to a different vendor (e.g. after a model fallback, Node 14/15).
- Malformed tool arguments are DATA, not exceptions: an adapter that can't parse a model's
  argument string still returns a ToolUseBlock, with `input={}` and `parse_error` set. The loop
  then sends the error back to the model to fix (Node 02 §5).
- Everything serializes to plain dicts (`to_dict` / `block_from_dict` / `Message.from_dict`) for
  transcripts, memory (Node 06) and durable execution (Node 14).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Literal, Protocol, Union, runtime_checkable

StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "pause_turn",
                     "context_window_exceeded", "content_filter", "other"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass
class TextBlock:
    text: str
    cache: bool = False          # provider-neutral cache breakpoint AFTER this block (Node 15)
    type: Literal["text"] = "text"


@dataclass
class ImageBlock:
    media_type: str              # "image/png" | "image/jpeg" | ...
    data_b64: str
    type: Literal["image"] = "image"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    raw_arguments: str | None = None    # the model's original argument string, when the wire format had one
    parse_error: str | None = None      # set when raw_arguments could not be parsed into an object
    provider: str | None = None
    provider_data: dict[str, Any] | None = None
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list[Union[TextBlock, ImageBlock]]   # str for most tools; blocks for screenshots etc.
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass
class ThinkingBlock:
    text: str
    provider: str | None = None                   # whose reasoning this is; foreign blocks get dropped
    provider_data: dict[str, Any] | None = None   # opaque; round-trip unchanged (e.g. signatures)
    type: Literal["thinking"] = "thinking"


Block = Union[TextBlock, ToolUseBlock, ToolResultBlock, ImageBlock, ThinkingBlock]
_BLOCK_TYPES = {"text": TextBlock, "image": ImageBlock, "tool_use": ToolUseBlock,
                "tool_result": ToolResultBlock, "thinking": ThinkingBlock}


def to_dict(obj: Any) -> Any:
    """Dataclasses (and lists of them) to plain JSON-ready dicts."""
    if isinstance(obj, list):
        return [to_dict(o) for o in obj]
    return asdict(obj)


def block_from_dict(d: dict) -> Block:
    d = dict(d)
    cls = _BLOCK_TYPES[d.get("type", "text")]
    if cls is ToolResultBlock and isinstance(d.get("content"), list):
        d["content"] = [block_from_dict(b) for b in d["content"]]
    return cls(**d)


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: list[Block]

    @staticmethod
    def user(text: str) -> "Message":
        return Message("user", [TextBlock(text)])

    @staticmethod
    def from_dict(d: dict) -> "Message":
        return Message(d["role"], [block_from_dict(b) for b in d["content"]])

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema object: {"type": "object", "properties": {...}, "required": [...]}


@dataclass
class Usage:
    input_tokens: int = 0         # UNCACHED input tokens billed at the normal rate
    output_tokens: int = 0        # includes reasoning tokens where the provider bills them as output
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0     # informational subset of output_tokens, if the provider reports it
    cost_usd: float | None = None # set when the provider reports cost directly (e.g. OpenRouter)

    def __add__(self, o: "Usage") -> "Usage":
        cost = None if self.cost_usd is None and o.cost_usd is None else (self.cost_usd or 0) + (o.cost_usd or 0)
        return Usage(self.input_tokens + o.input_tokens, self.output_tokens + o.output_tokens,
                     self.cache_read_tokens + o.cache_read_tokens, self.cache_write_tokens + o.cache_write_tokens,
                     self.reasoning_tokens + o.reasoning_tokens, cost)

    @property
    def total_input(self) -> int:
        """All prompt tokens, cached or not. This is what context-length limits and price tiers see."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass
class ModelResponse:
    content: list[Block]
    stop_reason: StopReason
    usage: Usage
    model: str
    provider: str
    id: str | None = None          # provider's response id (cache diagnostics, response chaining)
    latency_s: float = 0.0
    raw_stop_reason: str | None = None   # the vendor's original value, for debugging
    raw: Any = field(default=None, repr=False)   # the vendor's original response object

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


@runtime_checkable
class ChatModel(Protocol):
    """Anything that can take a conversation and return the next assistant turn.

    `system` may be a plain string or a list of TextBlocks (use TextBlock(cache=True) to mark a
    cache breakpoint). Streaming is a separate, optional protocol (StreamingChatModel, below),
    added in Node 17; design your adapters so it can be bolted on.
    """
    provider: str
    model: str

    def complete(self, *, system: str | list[TextBlock], messages: list[Message],
                 tools: list[ToolSpec] | None = None, max_tokens: int = 1024, **opts: Any) -> ModelResponse:
        """opts (adapters ignore what they don't support, and record that in a debug log):
        effort: "low"|"medium"|"high"|"xhigh"|"max" -> Anthropic output_config.effort / OpenAI reasoning_effort
        temperature: float              -> only where the provider still accepts (and honours) it
        tool_choice: "auto"|"any"|"none"|{"name": str}
        json_schema: dict               -> structured output (Anthropic output_config.format / OpenAI response_format)
        cache: bool                     -> automatic prompt caching where the provider needs opting in (Node 15)
        parallel_tools: bool            -> False forbids several tool calls in one turn (useful for write tools)
        """
        ...


@runtime_checkable
class StreamingChatModel(ChatModel, Protocol):
    def stream(self, *, system: str | list[TextBlock], messages: list[Message],
               tools: list[ToolSpec] | None = None, max_tokens: int = 1024, **opts: Any) -> Iterator[dict]:
        """Yields {"type": "text_delta", "text": ...} | {"type": "tool_use_start", ...} | ...
        and finally {"type": "response", "response": ModelResponse}. Defined in Node 17."""
        ...
