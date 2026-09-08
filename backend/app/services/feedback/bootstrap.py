"""Composition root: builds the process-wide FeedbackDispatcher singleton.

Kept separate from ``dispatch.py`` (mirroring
``app.services.workflows.bootstrap``'s already-established split) so
``dispatch.py`` — imported directly by the driver submodules for
``drain_feedback`` — stays free of a module-level import on
``app.services.workflows`` or ``app.services.ingestion`` (which itself
imports ``app.services.workflows``), either of which would be a real
circular import (see ``dispatch.py``'s module docstring).
"""
from __future__ import annotations

from functools import lru_cache

from app.persistence.feedback_store import get_feedback_store
from app.services.feedback.dispatch import FeedbackDispatcher
from app.services.ingestion import get_ingestion_service
from app.services.workflows import get_workflow_service


@lru_cache
def get_feedback_dispatcher() -> FeedbackDispatcher:
    """Return the process-wide FeedbackDispatcher singleton."""
    return FeedbackDispatcher(
        get_workflow_service(), get_feedback_store(), get_ingestion_service()
    )
