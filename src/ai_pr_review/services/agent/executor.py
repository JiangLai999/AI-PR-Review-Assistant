"""Safe, reusable dispatch primitives for Chat and Agent Actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_pr_review.services.agent.actions import ActionResult, ChatAction
from ai_pr_review.services.agent.context import ChatContext

ActionHandler = Callable[[ChatAction, ChatContext], ActionResult]
ToolHandler = Callable[..., Any]


class ActionConfirmationRequired(PermissionError):
    """Raised when a high-risk Action has not been confirmed by the user."""


class UnknownActionError(KeyError):
    """Raised when no executor has been registered for an Action."""


class ToolRegistry:
    """Small explicit registry; it never executes arbitrary shell input."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if not name or not name.strip():
            raise ValueError("Tool name must not be empty")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = handler

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            handler = self._tools[name]
        except KeyError as exc:
            raise UnknownActionError(f"Unknown tool: {name}") from exc
        return handler(*args, **kwargs)


class ActionExecutor:
    """Dispatches validated Actions to explicitly registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, action: str, handler: ActionHandler) -> None:
        if not action or not action.strip():
            raise ValueError("Action name must not be empty")
        if action in self._handlers:
            raise ValueError(f"Action already registered: {action}")
        self._handlers[action] = handler

    def has(self, action: str) -> bool:
        return action in self._handlers

    def execute(self, action: ChatAction, context: ChatContext) -> ActionResult:
        if not action.is_confirmed:
            raise ActionConfirmationRequired(f"Action requires confirmation: {action.action}")
        try:
            handler = self._handlers[action.action]
        except KeyError as exc:
            raise UnknownActionError(f"Unknown action: {action.action}") from exc
        result = handler(action, context)
        if result.action != action.action:
            raise ValueError(f"Action handler returned {result.action!r} for {action.action!r}")
        return result
