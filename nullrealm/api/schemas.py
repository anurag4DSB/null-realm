"""Pydantic models for the Null Realm API."""

from pydantic import BaseModel


class ChatMessage(BaseModel):
    type: str  # "user_message" or "assistant_message"
    content: str
    session_id: str
