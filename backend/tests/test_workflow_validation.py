"""Tests for required LLM output validation and bounded correction."""
from __future__ import annotations

import pytest

from app.services.workflows.validation import (
    InvalidRequiredOutputError,
    request_valid_output,
    required_tagged_text,
)

_SECOND_ATTEMPT = 2
_MAX_ATTEMPTS = 5


def test_required_tagged_text_rejects_missing_and_empty_content() -> None:
    """Required tagged output must contain non-whitespace payload text."""
    with pytest.raises(ValueError, match="missing REFINED_ISSUE"):
        required_tagged_text("plain response", "REFINED_ISSUE")
    with pytest.raises(ValueError, match="content was empty"):
        required_tagged_text(
            "<REFINED_ISSUE>  </REFINED_ISSUE>", "REFINED_ISSUE"
        )


@pytest.mark.asyncio
async def test_request_valid_output_corrects_once() -> None:
    """A valid second response returns without making further requests."""
    prompts: list[str] = []
    responses = iter(["", "<RESULT>usable</RESULT>"])

    async def send(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    result = await request_valid_output(
        send, "original", lambda text: required_tagged_text(text, "RESULT"),
        "result",
    )

    assert result == "usable"
    assert len(prompts) == _SECOND_ATTEMPT
    assert "missing RESULT block" in prompts[1]


@pytest.mark.asyncio
async def test_request_valid_output_stops_after_five_attempts() -> None:
    """Invalid required output has a fixed five-call limit."""
    calls = 0

    async def send(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return ""

    with pytest.raises(InvalidRequiredOutputError, match="after 5 attempts"):
        await request_valid_output(
            send, "original", lambda text: required_tagged_text(text, "RESULT"),
            "result",
        )
    assert calls == _MAX_ATTEMPTS
