"""SQLAlchemy 2.0 ORM models for the Null Realm registry."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class with common columns."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Tool(Base):
    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_type: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    execution_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Prompt(Base):
    __tablename__ = "prompts"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variables: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Assistant(Base):
    __tablename__ = "assistants"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_preference: Mapped[str] = mapped_column(String(100), nullable=False, default="claude-sonnet")
    tool_allowlist: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Workflow(Base):
    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    max_parallel_agents: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Repository(Base):
    __tablename__ = "repos"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="public")  # public, token
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending, indexing, ready, failed
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
