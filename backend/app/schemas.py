"""Response/DTO schemas shared across the service and router layers.

These mirror the frontend business types in ``frontend/src/types/``;
keep them in sync when the API changes (see ``contract.md``).
"""
from __future__ import annotations

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """Summary of one session for the list endpoint.

    :param session_id: Unique id of the session.
    :param status: Current lifecycle status (e.g. running, idle).
    :param event_count: Number of events recorded so far.
    """

    session_id: str
    status: str
    event_count: int
