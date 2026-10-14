"""JSON tool protocol — the model-agnostic tool loop contract.

The model emits ONE JSON object per turn:
    {"tool": "<name>", "args": {...}}     -> run a tool
    {"final": "<answer>", "citations": [{"source": ..., "page": ...}]}
Parsed with Pydantic; never `bind_tools`, never a provider tool template —
that is what lets qwen3, llama3.1 and deepseek-r1 run the SAME graph.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = {}


class Citation(BaseModel):
    source: str
    section: str | None = None        # KB section ("3", "3.1") — preferred
    page: int | str | None = None

    @field_validator("section", mode="before")
    @classmethod
    def _section_str(cls, v):  # small models emit 3 / 3.1 as numbers
        return None if v is None else str(v).lstrip("§ ")


class Final(BaseModel):
    final: str
    citations: list[Citation] = []


Decision = ToolCall | Final

_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _candidates(raw: str):
    """JSON object candidates, outermost first, tolerant of prose around it."""
    text = _THINK.sub("", raw).strip()
    fence = _FENCE.search(text)
    if fence:
        yield fence.group(1)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    break
        start = text.find("{", start + 1)


def parse_decision(raw: str) -> Decision:
    """Raw model text -> ToolCall | Final. Raises ProtocolError when nothing
    in the reply is a valid protocol object."""
    for cand in _candidates(raw):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        try:
            if "tool" in obj:
                return ToolCall.model_validate(obj)
            if "final" in obj:
                return Final.model_validate(obj)
        except ValidationError:
            continue
    raise ProtocolError(raw)


class ProtocolError(ValueError):
    def __init__(self, raw: str):
        super().__init__("no valid protocol JSON in model reply")
        self.raw = raw


RETRY_MESSAGE = (
    'Your reply was not a valid protocol object. Reply with EXACTLY ONE JSON '
    'object and nothing else: {"tool": "<name>", "args": {...}} to use a tool, '
    'or {"final": "<answer>", "citations": [{"source": "...", "page": ...}]} '
    "to answer."
)


def render_tools(tools: dict[str, dict]) -> str:
    """Tool block for the system prompt: name, description, JSON args schema."""
    lines = []
    for name, spec in tools.items():
        lines.append(f'- "{name}": {spec["description"]}')
        lines.append(f'  args schema: {json.dumps(spec["args"], ensure_ascii=False)}')
    return "\n".join(lines)
