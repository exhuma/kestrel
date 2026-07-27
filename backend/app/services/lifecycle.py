"""Lifecycle-event dispatch: native status/time transitions, comment-footer
fallback, and operator hooks (feature 006).

Structurally a ``Notifier`` (see ``app.notifications``): a synchronous
``notify(run)`` entry point that schedules its actual work as an
``asyncio`` task, exactly like ``TaskSourceNotifier``. Added as one more
entry in the existing ``CompositeNotifier`` fan-out so a broken lifecycle
dispatch never blocks another notifier or the run itself.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Literal

from app.notifications import gate_deep_link
from app.ports import LifecycleEvent
from app.services.hooks import HookRunner

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun
    from app.ports import TaskSource

_log = logging.getLogger("kestrel.lifecycle")

#: Run statuses that warrant a lifecycle dispatch, mapped to the
#: ``LifecycleEvent.kind`` they produce. Exhaustive and mutually
#: exclusive — a failed/escalated/rejected run can never produce
#: ``kind="done"`` because its status never maps to "done" here.
_Kind = Literal["start", "done", "failed", "escalated", "rejected"]
_KIND_BY_STATUS: dict[str, _Kind] = {
    "cloning": "start",
    "done": "done",
    "failed": "failed",
    "escalated": "escalated",
    "rejected": "rejected",
}


def _is_lifecycle_event(status: str) -> bool:
    """Whether ``status`` is one this dispatcher acts on."""
    return status in _KIND_BY_STATUS


def _build_event(run: "WorkflowRun", public_base_url: str) -> LifecycleEvent:
    """Build the source-neutral event for ``run``'s current status.

    Time metrics are only meaningful at a terminal event ("start" has
    nothing to report yet, so both stay ``None`` — a footer with only a
    status line, not a noisy "active: 0m").
    """
    kind = _KIND_BY_STATUS[run.status]
    is_terminal = kind != "start"
    return LifecycleEvent(
        kind=kind,
        active_seconds=run.active_seconds if is_terminal else None,
        wait_seconds=run.wait_seconds if is_terminal else None,
        deep_link=gate_deep_link(public_base_url, run.id),
    )


def render_footer(
    event: LifecycleEvent, *, include_status: bool, include_time: bool
) -> str:
    """Render the comment-footer fallback for fields not natively applied.

    :param event: The lifecycle event being reported.
    :param include_status: Whether the status wasn't natively applied.
    :param include_time: Whether the time metrics weren't natively applied.
    :returns: The footer text, or "" when neither field needs reporting
        (the caller then posts no comment at all).
    """
    if not include_status and not include_time:
        return ""
    parts = ["kestrel:"]
    if include_status:
        parts.append(f"status → {event.kind}")
    if include_time and event.active_seconds is not None:
        active = _format_duration(event.active_seconds)
        parts.append(f"active: {active}")
        if event.wait_seconds:
            wait = _format_duration(event.wait_seconds)
            parts.append(f"waiting on you: {wait}")
    return f"---\n{' · '.join(parts)}" if len(parts) > 1 else ""


def _format_duration(seconds: float) -> str:
    """Render a duration in seconds as ``"2h 14m"``-style text."""
    total_minutes = round(seconds / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _hook_payload(run: "WorkflowRun", event: LifecycleEvent) -> dict:
    """Build the JSON payload sent to a hook's stdin (feature 006, see
    ``contracts/hook-wire-format.md``)."""
    return {
        "event": event.kind,
        "run_id": run.id,
        "task_ref": run.task_ref,
        "source": run.source,
        "active_seconds": event.active_seconds,
        "wait_seconds": event.wait_seconds,
        "pr_url": run.pr_url,
        "deep_link": event.deep_link,
        "error": run.error if event.kind != "start" else None,
    }


class LifecycleTransitioner:
    """Dispatches a run's lifecycle events to its task source and hooks.

    :param sources: ``run.source`` -> ``TaskSource``, mirroring
        ``TaskSourceNotifier``'s constructor (feature 003).
    :param public_base_url: Configured public UI base URL, for deep links.
    :param hooks_dir_for: Resolves a run to its configured per-source
        hooks directory (empty ⇒ none). Omitted disables hook dispatch
        entirely.
    :param hook_runner: Override for testing; defaults to a real
        :class:`HookRunner`.
    """

    def __init__(
        self,
        sources: "dict[str, object]",
        public_base_url: str = "",
        hooks_dir_for: "Callable[[WorkflowRun], str] | None" = None,
        hook_runner: HookRunner | None = None,
    ) -> None:
        self._sources = sources
        self._public_base_url = public_base_url
        self._hooks_dir_for = hooks_dir_for
        self._hooks = hook_runner or HookRunner()
        #: Keep fire-and-forget tasks referenced so they are not GC'd.
        self._tasks: set[asyncio.Task] = set()

    def notify(self, run: "WorkflowRun") -> None:
        """Schedule this run's lifecycle dispatch, if status warrants one."""
        if not _is_lifecycle_event(run.status):
            return
        source = self._sources.get(run.source)
        if source is None or not run.task_ref:
            return
        event = _build_event(run, self._public_base_url)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _log.warning(
                "no running loop; skipping lifecycle dispatch for %s", run.id
            )
            return
        task = loop.create_task(self._dispatch(source, run, event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(
        self, source: "TaskSource", run: "WorkflowRun", event: LifecycleEvent
    ) -> None:
        task_ref = run.task_ref
        try:
            native_status_ok = await source.transition(task_ref, event)
        except Exception:  # noqa: BLE001 — best-effort; footer is the fallback
            _log.exception("native transition failed for %s", task_ref)
            native_status_ok = False
        hooks_dir = self._hooks_dir_for(run) if self._hooks_dir_for else ""
        hook_response = await self._hooks.run(
            hooks_dir, _hook_payload(run, event)
        )
        has_time = event.active_seconds is not None
        include_time = has_time and not source.supports_time_spent()
        footer = render_footer(
            event,
            include_status=not native_status_ok,
            include_time=include_time,
        )
        if footer and not hook_response.get("comment_posted"):
            try:
                await source.post_comment(task_ref, footer)
            except Exception:  # noqa: BLE001 — best-effort; logged
                _log.exception(
                    "failed to post lifecycle footer for %s", task_ref
                )
