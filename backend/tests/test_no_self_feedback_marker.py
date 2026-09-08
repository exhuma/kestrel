"""Regression test (feature 013, T053).

Covers guard 1 of research.md R6's three independent self-feedback-loop
guards: kestrel must never emit its own configured trigger marker
(``settings.feedback_marker``, default ``"@kestrel"``) in any
comment/message template it writes back to a ticket. Guard 2 (the author
denylist / bot-type check) is covered by ``test_feedback_marker.py``;
guard 3 (dedup via ``feedback_item.external_id``) is covered by
``test_feedback_store.py``. This test covers guard 1 mechanically — by
extracting the literal string constants out of every known
comment-authoring template's *source*, not by eyeballing the code — so a
future edit that slips the marker into one of these templates fails CI
rather than relying on review discipline.

Scope: every place in the non-test codebase that calls
``TaskSource.post_comment`` (or otherwise composes a comment/message body)
with a fixed template, as of this feature:

- ``app.notifications``: ``_MESSAGES`` (per-status gate/terminal
  templates), ``render_message``'s unmatched-status fallback, and
  ``TaskSourceNotifier.notify``'s appended deep-link line.
- ``app.services.workflows.driver.deliver``: the two landing-comment
  templates (new change request vs. idempotent re-delivery, feature 013
  US3).
- ``app.services.jira_poll.JiraPollService._comment_unresolved``: the
  "could not determine the target repository" comment.
- ``app.services.lifecycle.render_footer``: the lifecycle-footer
  fragments ("kestrel:", "status → …", "active: …", "waiting on you: …").

Dynamically-substituted values (task labels, PR URLs, durations,
deep-links) are deliberately excluded from the scan: they are not
templates kestrel "writes", they are runtime data, and a marker arriving
via that path is a different risk (an attacker-controlled ticket title
echoing the marker back) that guards 2/3 exist to bound, not guard 1.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Callable

import pytest

from app.config import get_settings
from app.notifications import _MESSAGES, TaskSourceNotifier, render_message
from app.services import jira_poll, lifecycle
from app.services.feedback.marker import has_marker
from app.services.workflows import driver


def _literal_strings(source_of: object) -> list[str]:
    """Extract every literal (non-interpolated) string constant that
    appears in ``source_of``'s source code.

    Handles f-strings correctly: only the literal text segments of a
    ``JoinedStr`` are collected, never the ``{...}`` interpolated
    expressions (those carry runtime data, not template text).

    :param source_of: A function, method, or other object
        ``inspect.getsource`` accepts.
    :returns: Every literal string fragment found in the source.
    """
    source = textwrap.dedent(inspect.getsource(source_of))
    tree = ast.parse(source)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


def _assert_none_carry_marker(literals: list[str], marker: str) -> None:
    """Fail with the offending literal named, if any literal has the
    marker as a whole token (mirrors the real gate's own matching rule
    from ``services/feedback/marker.py``)."""
    offenders = [text for text in literals if has_marker(text, marker)]
    assert not offenders, (
        f"template literal(s) contain the feedback marker {marker!r}, "
        f"which would trigger kestrel's own feedback loop on itself: "
        f"{offenders!r}"
    )


@pytest.fixture(name="marker")
def _marker() -> str:
    return get_settings().feedback_marker


def test_notifications_messages_never_carry_marker(marker: str) -> None:
    """None of the per-status notification templates emit the marker."""
    literals = list(_MESSAGES.values())
    _assert_none_carry_marker(literals, marker)


def test_render_message_fallback_never_carries_marker(marker: str) -> None:
    """``render_message``'s own source (incl. its unmatched-status
    fallback template) never emits the marker."""
    _assert_none_carry_marker(_literal_strings(render_message), marker)


def test_task_source_notifier_deep_link_line_never_carries_marker(
    marker: str,
) -> None:
    """The "Open in kestrel: {link}" line ``TaskSourceNotifier.notify``
    appends never itself carries the marker."""
    _assert_none_carry_marker(
        _literal_strings(TaskSourceNotifier.notify), marker
    )


def test_driver_landing_comments_never_carry_marker(marker: str) -> None:
    """``deliver()``'s two landing-comment templates (new-CR vs.
    idempotent re-delivery, US3) never carry the marker."""
    _assert_none_carry_marker(_literal_strings(driver.deliver), marker)


def test_jira_poll_unresolved_comment_never_carries_marker(
    marker: str,
) -> None:
    """The "could not determine the target repository" Jira comment
    never carries the marker."""
    _assert_none_carry_marker(
        _literal_strings(jira_poll.JiraPollService._comment_unresolved),
        marker,
    )


def test_lifecycle_footer_never_carries_marker(marker: str) -> None:
    """None of the lifecycle-footer fragments ``render_footer`` composes
    ever carry the marker."""
    _assert_none_carry_marker(_literal_strings(lifecycle.render_footer), marker)


@pytest.mark.parametrize(
    "func",
    [
        render_message,
        TaskSourceNotifier.notify,
        driver.deliver,
        jira_poll.JiraPollService._comment_unresolved,
        lifecycle.render_footer,
    ],
)
def test_default_marker_also_never_appears(func: Callable) -> None:
    """Belt-and-braces: even independent of whatever marker is currently
    configured in this environment, the shipped default ("@kestrel")
    never appears in any of these templates either."""
    _assert_none_carry_marker(_literal_strings(func), "@kestrel")
