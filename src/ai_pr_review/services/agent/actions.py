"""Validated Actions exchanged between Chat Copilot and business services."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatAction(BaseModel):
    """A structured intent that can be safely dispatched by the application."""

    action: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    confirmed: bool = False
    risk_level: str = "low"
    source: str = "chat"
    request_id: str | None = None

    @property
    def is_confirmed(self) -> bool:
        return not self.requires_confirmation or self.confirmed


class ActionResult(BaseModel):
    """Serializable result returned by an Action Executor."""

    action: str
    ok: bool = True
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
