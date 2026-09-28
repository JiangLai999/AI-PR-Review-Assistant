from __future__ import annotations

import pytest

from ai_pr_review.services.agent import (
    ActionConfirmationRequired,
    ActionExecutor,
    ActionResult,
    AgentEvent,
    AgentState,
    ChatAction,
    ChatContext,
    ToolRegistry,
    UnknownActionError,
)


def test_chat_context_transition_is_immutable() -> None:
    context = ChatContext(session_id="session-1")
    running = context.transition(AgentState.REVIEW_RUNNING)

    assert context.state == AgentState.READY
    assert running.state == AgentState.REVIEW_RUNNING


def test_agent_event_validates_progress_range() -> None:
    event = AgentEvent(
        event_type="file_completed",
        phase="ai_review",
        progress=0.5,
        completed=1,
        total=2,
    )

    assert event.progress == 0.5

    with pytest.raises(ValueError):
        AgentEvent(event_type="bad", progress=1.5)


def test_action_executor_requires_confirmation_for_risky_action() -> None:
    executor = ActionExecutor()
    context = ChatContext(session_id="session-1")
    executor.register(
        "start_review",
        lambda action, ctx: ActionResult(action=action.action, data={"run": "1"}),
    )

    with pytest.raises(ActionConfirmationRequired):
        executor.execute(
            ChatAction(
                action="start_review",
                requires_confirmation=True,
                risk_level="high",
            ),
            context,
        )

    result = executor.execute(
        ChatAction(action="start_review", requires_confirmation=True, confirmed=True),
        context,
    )
    assert result.ok is True
    assert result.data["run"] == "1"


def test_action_executor_rejects_unknown_action() -> None:
    with pytest.raises(UnknownActionError):
        ActionExecutor().execute(ChatAction(action="unknown"), ChatContext(session_id="1"))


def test_tool_registry_only_dispatches_registered_tools() -> None:
    registry = ToolRegistry()
    registry.register("echo", lambda value: value)

    assert registry.execute("echo", "ok") == "ok"
    with pytest.raises(UnknownActionError):
        registry.execute("shell", "echo unsafe")


@pytest.mark.asyncio
async def test_local_router_uses_deterministic_pr_url_route():
    from ai_pr_review.services.agent import ChatActionRouter

    class UnexpectedProvider:
        async def chat(self, *args, **kwargs):
            raise AssertionError("deterministic route should not call the model")

    context = ChatContext(session_id="session-1")
    action = await ChatActionRouter(UnexpectedProvider(), model_name="qwen3.5:4b").route(
        "帮我审查 https://github.com/example/repo/pull/12", context
    )

    assert action.action == "start_review"
    assert action.arguments["pr_url"].endswith("/pull/12")
    assert action.requires_confirmation is True
