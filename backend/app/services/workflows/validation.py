"""Validation and bounded correction for required model output."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

_MAX_REQUIRED_OUTPUT_ATTEMPTS = 5
_T = TypeVar("_T")


class InvalidRequiredOutputError(ValueError):
    """Raised when required model output remains invalid after correction."""


def required_tagged_text(text: str, tag: str) -> str:
    """Return nonempty ``tag`` content or raise a concise validation error."""
    opening, closing = f"<{tag}>", f"</{tag}>"
    start = text.find(opening)
    end = text.find(closing, start + len(opening))
    if start < 0 or end < 0:
        raise ValueError(f"missing {tag} block")
    content = text[start + len(opening):end].strip()
    if not content:
        raise ValueError(f"{tag} content was empty")
    return content


async def request_valid_output(
    send: Callable[[str], Awaitable[str]],
    prompt: str,
    parse: Callable[[str], _T],
    label: str,
) -> _T:
    """Request and validate a required artifact within five total attempts.

    ``parse`` returns the usable artifact or raises ``ValueError`` explaining
    why the response is invalid. Correction attempts repeat the complete
    original prompt, so each fresh stateless model turn retains its context.
    """
    current_prompt = prompt
    reason = ""
    for attempt in range(1, _MAX_REQUIRED_OUTPUT_ATTEMPTS + 1):
        response = await send(current_prompt)
        try:
            return parse(response)
        except ValueError as exc:
            reason = str(exc)
            if attempt == _MAX_REQUIRED_OUTPUT_ATTEMPTS:
                break
            current_prompt = _correction_prompt(prompt, label, reason, response)
    raise InvalidRequiredOutputError(
        f"{label} returned invalid output after "
        f"{_MAX_REQUIRED_OUTPUT_ATTEMPTS} "
        f"attempts: {reason}"
    )


def _correction_prompt(
    prompt: str, label: str, reason: str, response: str
) -> str:
    """Return a correction request retaining the original required context."""
    return (
        f"{prompt}\n\nYOUR PRIOR {label.upper()} RESPONSE WAS INVALID: "
        f"{reason}. Return the required nonempty structured output only. "
        f"Do not discuss this correction.\n\nINVALID RESPONSE:\n{response}"
    )
