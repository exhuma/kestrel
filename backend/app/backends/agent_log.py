"""Agent output in the server log, keyed by session id.

Kestrel keeps no copy of what an agent did: the only record is the
``kestrel.agent`` logger. Every record it emits carries the backend's
session id (and the card id when the turn works for a card) both in the
message and as ``session_id`` / ``card_id`` fields, so one ``grep`` or log
query by session id returns a turn's whole story. The id is stored on the
card attempt (``board_card_attempt.session_id``) to get from the board to it.

Levels: canonical events at DEBUG, the turn's start and result at INFO, a
failed turn or an error result at WARNING. Free text is truncated
(:data:`MAX_TEXT`) so a log line stays bounded however much the agent says.
"""
from __future__ import annotations

import logging

from app.models import CanonicalEvent

#: Name of the logger every agent record goes through.
LOGGER_NAME = "kestrel.agent"
#: Longest stretch of agent free text kept in one log line, in characters.
MAX_TEXT = 500

_logger = logging.getLogger(LOGGER_NAME)


def clip(text: str | None, limit: int = MAX_TEXT) -> str:
    """Collapse *text* onto one line and cut it to *limit* characters.

    :returns: The text, with ``…(+N chars)`` noting what was left out.
    """
    if not text:
        return ""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return f"{flat[:limit]}…(+{len(flat) - limit} chars)"


def describe(event: CanonicalEvent) -> str:
    """One bounded line describing a canonical event."""
    parts = [event.kind.value]
    if event.tool_name:
        parts.append(event.tool_name)
    if event.tool_summary:
        parts.append(clip(event.tool_summary, MAX_TEXT // 2))
    if event.subtype:
        parts.append(event.subtype)
    if event.is_error:
        parts.append("(error)")
    body = clip(event.text or event.summary)
    if body:
        parts.append(body)
    return " ".join(parts)


class AgentLog:
    """The ``kestrel.agent`` records of one agent session.

    :param session_id: The backend's session id; on every record.
    :param card_id: The card the turn works for, if any.
    :param backend_id: The backend running the session, if known.
    """

    def __init__(
        self,
        session_id: str,
        card_id: str | None = None,
        backend_id: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._card_id = card_id
        self._backend_id = backend_id

    def _emit(self, level: int, message: str) -> None:
        """Log *message*, tagged with the session (and card) id."""
        if not _logger.isEnabledFor(level):
            return
        _logger.log(
            level,
            "session=%s card=%s %s",
            self._session_id,
            self._card_id or "-",
            message,
            extra={"session_id": self._session_id, "card_id": self._card_id},
        )

    def started(self, resumed: bool = False) -> None:
        """Note that a turn began on this session."""
        verb = "resumed" if resumed else "started"
        self._emit(
            logging.INFO, f"agent session {verb} backend={self._backend_id}"
        )

    def event(self, event: CanonicalEvent) -> None:
        """Log one canonical event at DEBUG."""
        if _logger.isEnabledFor(logging.DEBUG):
            self._emit(logging.DEBUG, describe(event))

    def finished(
        self,
        text: str | None,
        *,
        is_error: bool = False,
        duration_ms: int | None = None,
    ) -> None:
        """Log the turn's result: INFO, or WARNING when it is an error."""
        took = f" in {duration_ms} ms" if duration_ms is not None else ""
        status = "failed" if is_error else "finished"
        self._emit(
            logging.WARNING if is_error else logging.INFO,
            f"agent turn {status}{took}: {clip(text)}",
        )

    def failed(self, reason: str) -> None:
        """Log a turn that ended without a result (crash, stop, timeout)."""
        self._emit(logging.WARNING, f"agent turn aborted: {clip(reason)}")
