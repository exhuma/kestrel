"""What kestrel logs to explain itself: decisions at INFO, failed tool
calls at WARNING, and whole transcripts only when asked for."""
from __future__ import annotations

import logging

import httpx
import pytest

from app.backends.agent_log import AgentLog
from app.backends.base import TurnRequest
from app.backends.limiter import BackendLimiter
from app.backends.opencode_parts import part_events
from app.config_reasoning import ReasoningEndpoint
from app.logging_config import build_log_config, parse_log_levels
from app.models import CanonicalEvent, EventKind, map_claude_dict
from app.models_board import WorkCard
from app.reasoning.client import ReasoningClient, ReasoningTarget
from app.services.board import decision_log

_CARD = WorkCard(
    id="card-9", workflow_id="wf-1", kind="verification", title="Verify",
    state="review", task_node_id="t1",
)


def test_per_logger_levels_are_parsed_and_applied() -> None:
    """Ensure one logger can be followed at debug while the rest stays at
    info, and a typo fails at startup."""
    config = build_log_config("info", "text", "kestrel.reasoning=debug")

    assert config["root"]["level"] == "INFO"
    assert config["loggers"]["kestrel.reasoning"]["level"] == "DEBUG"
    with pytest.raises(ValueError, match="logger=level"):
        parse_log_levels("kestrel.agent:debug")


def test_a_failed_tool_call_is_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a tool's error is visible at the usual level, naming the
    tool, even when debug is off."""
    log = AgentLog("ses-1", "card-1", "oc")
    caplog.set_level(logging.INFO, logger="kestrel.agent")

    log.event(CanonicalEvent(EventKind.TOOL_USE, "ses-1", tool_name="fetch"))
    log.event(CanonicalEvent(
        EventKind.TOOL_RESULT, "ses-1", text="ECONNREFUSED via proxy",
        is_error=True,
    ))

    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "tool call failed: fetch: ECONNREFUSED via proxy" in (
        record.getMessage()
    )


def test_an_opencode_tool_error_carries_its_error_text() -> None:
    """Ensure a failed opencode tool reports its error, not nothing."""
    events = part_events({
        "type": "tool", "tool": "bash",
        "state": {"status": "error", "input": {"command": "curl x"},
                  "error": "connection refused"},
    }, "ses-1")

    assert events[-1].is_error
    assert events[-1].text == "connection refused"


def test_claude_thinking_is_kept_as_reasoning() -> None:
    """Ensure Claude's thinking blocks reach the log like opencode's."""
    event = map_claude_dict({
        "type": "assistant", "session_id": "s",
        "message": {"content": [{"type": "thinking", "thinking": "Hmm."}]},
    })

    assert (event.kind, event.subtype, event.summary) == (
        EventKind.SYSTEM, "reasoning", "Hmm.",
    )


def test_the_text_limit_can_be_lifted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure ``log_text_limit = 0`` keeps an agent's whole answer."""
    caplog.set_level(logging.INFO, logger="kestrel.agent")
    long_answer = "x" * 900

    AgentLog("s", text_limit=0).finished(long_answer)

    assert long_answer in caplog.records[0].getMessage()


def test_a_verification_says_its_round_and_findings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure work handed back to the coder says why, at INFO."""
    caplog.set_level(logging.INFO, logger="kestrel.board.decisions")

    decision_log.verified(
        _CARD, [("nonconformance", "export ignores the date filter")],
        " (round 2 of 3, task t1)",
    )

    (record,) = caplog.records
    assert record.workflow_id == "wf-1"
    assert "round 2 of 3" in record.getMessage()
    assert "nonconformance: export ignores the date filter" in (
        record.getMessage()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("level", "seen"), [
    (logging.INFO, False), (logging.DEBUG, True),
])
async def test_reasoning_transcripts_only_at_debug(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch, level: int, seen: bool,
) -> None:
    """Ensure the whole prompt and answer are logged only when asked for,
    since they carry ticket content."""
    monkeypatch.setenv("TEST_RSN_KEY", "k")
    answer = {"choices": [{"finish_reason": "stop",
                           "message": {"content": "The verdict"}}]}
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _r: httpx.Response(200, json=answer)
    ))
    client = ReasoningClient(
        ReasoningTarget("pm", ReasoningEndpoint(
            base_url="https://llm/v1", model="m", api_key_env="TEST_RSN_KEY",
        )),
        BackendLimiter(1), http,
    )
    caplog.set_level(level, logger="kestrel.reasoning")

    await client.run_turn(TurnRequest(
        prompt="The whole prompt", cwd="", permission_mode="read_only",
    ))

    text = caplog.text
    assert ("The whole prompt" in text and "The verdict" in text) is seen
    assert "reasoning turn finished" in text
