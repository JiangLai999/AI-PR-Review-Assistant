"""Structured events emitted by Agent and review execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    """A transport-neutral progress/event envelope."""

    event_type: str
    phase: str = ""
    message: str = ""
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    current_file: str | None = None
    completed: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=0)
    source: str = "agent"
    data: dict[str, Any] = Field(default_factory=dict)
