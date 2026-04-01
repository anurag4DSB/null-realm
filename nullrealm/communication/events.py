"""Stream event models for agent-to-UI communication via NATS."""

from typing import Any

from pydantic import BaseModel


class StreamEvent(BaseModel):
    type: str
    session_id: str


class TextDeltaEvent(StreamEvent):
    type: str = "text_delta"
    content: str


class ToolUseEvent(StreamEvent):
    type: str = "tool_use"
    tool: str
    input: dict[str, Any]


class ToolResultEvent(StreamEvent):
    type: str = "tool_result"
    tool: str
    output: str


class TaskCompleteEvent(StreamEvent):
    type: str = "task_complete"
    result: str
