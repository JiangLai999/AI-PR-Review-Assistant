"""Conversation context and state models for the Agent layer."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AgentState(StrEnum):
    """Stable states used by CLI, Web, and Chat Copilot."""

    UNCONFIGURED = "unconfigured"
    CONFIGURING = "configuring"
    READY = "ready"
    REVIEW_CONFIRMING = "review_confirming"
    REVIEW_PLANNING = "review_planning"
    REVIEW_RUNNING = "review_running"
    REVIEW_COMPLETED = "review_completed"
    EXPLAINING_FINDING = "explaining_finding"
    HISTORY_QUERY = "history_query"
    ERROR = "error"


class ChatContext(BaseModel):
    """Persistable context shared by Chat Copilot and Action Executors."""

    session_id: str
    language: str = "zh-CN"
    state: AgentState = AgentState.READY
    current_run_id: str | None = None
    current_pr_url: str | None = None
    current_finding_id: str | None = None
    current_action: str | None = None
    local_model: str | None = None
    remote_model: str | None = None
    review_status: str | None = None
    last_error: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def transition(self, state: AgentState, *, error: str | None = None) -> "ChatContext":
        """Return a copy with an updated state and optional error."""

        return self.model_copy(update={"state": state, "last_error": error})
