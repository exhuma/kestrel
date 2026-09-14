"""Framework-neutral rendering for externally posted review revisions."""

from __future__ import annotations

from difflib import ndiff

_MAX_DELTA_LINE_LENGTH = 120
_MAX_DELTA_LINES = 3


def _excerpt(line: str) -> str:
    """Bound one changed line so a delta can never reproduce an artifact."""
    cutoff = _MAX_DELTA_LINE_LENGTH - 3
    if len(line) <= _MAX_DELTA_LINE_LENGTH:
        return line
    return f"{line[:cutoff]}..."


def render_review_request(
    message: str, revision: int, token: str, artifact: str = ""
) -> str:
    """Render an external review with its artifact before response metadata.

    :param message: Brief description of the review gate.
    :param revision: Durable revision number for this post.
    :param token: Opaque token required when responding to this revision.
    :param artifact: Complete reviewable artifact, or empty for legacy callers.
    :returns: A tokenized review post whose artifact, when present, is first.
    """
    artifact_prefix = f"{artifact}\n\n---\n\n" if artifact else ""
    return (
        f"{artifact_prefix}{message}\n\n"
        f"Revision {revision}: `[kestrel-review:{token}]`\n\n"
        "Reply with one command:\n"
        f"- Approve with `@kestrel approve [kestrel-review:{token}]`\n"
        f"- Reject with `@kestrel reject [kestrel-review:{token}]`\n"
        "- Request changes with "
        f"`@kestrel request changes [kestrel-review:{token}]`."
    )


def render_delta_summary(
    previous: str, revised: str, canonical_reference: str
) -> str:
    """Render a concise, changed-lines-only artifact update and reference."""
    changes = [
        _excerpt(line[2:])
        for line in ndiff(previous.splitlines(), revised.splitlines())
        if line.startswith("+ ")
    ]
    excerpt = "\n".join(f"- {line}" for line in changes[:_MAX_DELTA_LINES])
    if len(changes) > _MAX_DELTA_LINES:
        excerpt += "\n- Additional requested changes applied."
    return (
        f"Requested changes applied:\n{excerpt or '- Content revised.'}\n\n"
        f"Canonical artifact: {canonical_reference}"
    )
