"""Pydantic schemas for registry CRUD operations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ---- Tool ----

class ToolCreate(BaseModel):
    name: str
    version: str = "1.0"
    description: str = ""
    input_schema: dict = {}
    execution_type: str = "python"
    execution_config: dict = {}


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: str
    description: str
    input_schema: dict
    execution_type: str
    execution_config: dict
    created_at: datetime
    updated_at: datetime


class ToolUpdate(BaseModel):
    version: str | None = None
    description: str | None = None
    input_schema: dict | None = None
    execution_type: str | None = None
    execution_config: dict | None = None


# ---- Prompt ----

class PromptCreate(BaseModel):
    name: str
    version: str = "1.0"
    template: str = ""
    variables: list = []
    model_hint: str | None = None


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: str
    template: str
    variables: list
    model_hint: str | None
    created_at: datetime
    updated_at: datetime


class PromptUpdate(BaseModel):
    version: str | None = None
    template: str | None = None
    variables: list | None = None
    model_hint: str | None = None


# ---- Assistant ----

class AssistantCreate(BaseModel):
    name: str
    prompt_name: str
    model_preference: str = "claude-sonnet"
    tool_allowlist: list = []
    system_prompt: str = ""


class AssistantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prompt_name: str
    model_preference: str
    tool_allowlist: list
    system_prompt: str
    created_at: datetime
    updated_at: datetime


class AssistantUpdate(BaseModel):
    prompt_name: str | None = None
    model_preference: str | None = None
    tool_allowlist: list | None = None
    system_prompt: str | None = None


# ---- Workflow ----

class WorkflowCreate(BaseModel):
    name: str
    steps: list = []
    max_parallel_agents: int = 1


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    steps: list
    max_parallel_agents: int
    created_at: datetime
    updated_at: datetime


class WorkflowUpdate(BaseModel):
    steps: list | None = None
    max_parallel_agents: int | None = None
