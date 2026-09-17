"""Framework-neutral rendering for externally posted review revisions."""

from __future__ import annotations

from difflib import ndiff

from app.documents import (
    BulletList,
    Code,
    Document,
    ListItem,
    Rule,
    Text,
    document,
    paragraph,
    parse_markdown,
)
from app.markers import ReviewTokenMarker

_MAX_DELTA_LINE_LENGTH = 120
_MAX_DELTA_LINES = 3


def _artifact_blocks(artifact: str) -> tuple:
    """Build artifact blocks, parsing the Markdown into canonical form."""
    if not artifact:
        return ()
    parsed = parse_markdown(artifact)
    return (*parsed.blocks, Rule())


def _excerpt(line: str) -> str:
    """Bound one changed line so a delta can never reproduce an artifact."""
    cutoff = _MAX_DELTA_LINE_LENGTH - 3
    if len(line) <= _MAX_DELTA_LINE_LENGTH:
        return line
    return f"{line[:cutoff]}..."


def render_review_request(
    message: str, revision: int, token: str, artifact: str = ""
) -> Document:
    """Render an external review with its artifact before response metadata.

    :param message: Brief description of the review gate.
    :param revision: Durable revision number for this post.
    :param token: Opaque token required when responding to this revision.
    :param artifact: Complete reviewable artifact, or empty for legacy callers.
    :returns: A tokenized review document whose artifact is first when present.
    """
    review_token = ReviewTokenMarker(token).render()
    artifact_blocks = _artifact_blocks(artifact)
    return document(
        *artifact_blocks,
        paragraph(Text(message)),
        paragraph(Text(f"Revision {revision}: "), Code(review_token)),
        paragraph(Text("Reply with one command:")),
        BulletList(
            (
                ListItem((paragraph(
                    Text("Approve with "),
                    Code(f"@kestrel approve {review_token}"),
                ),)),
                ListItem((paragraph(
                    Text("Reject with "),
                    Code(f"@kestrel reject {review_token}"),
                ),)),
                ListItem((paragraph(
                    Text("Request changes with "),
                    Code(f"@kestrel request changes {review_token}"),
                ),)),
            )
        ),
    )


def render_delta_summary(
    previous: str, revised: str, canonical_reference: str
) -> Document:
    """Render a concise, changed-lines-only artifact update and reference."""
    changes = [
        _excerpt(line[2:])
        for line in ndiff(previous.splitlines(), revised.splitlines())
        if line.startswith("+ ") and line[2:].strip()
    ]
    entries = changes[:_MAX_DELTA_LINES]
    if len(changes) > _MAX_DELTA_LINES:
        entries.append("Additional requested changes applied.")
    items = tuple(ListItem((paragraph(Text(entry)),)) for entry in entries)
    fallback = (ListItem((paragraph(Text("Content revised.")),)),)
    return document(
        paragraph(Text("Requested changes applied:")),
        BulletList(items or fallback),
        paragraph(Text(f"Canonical artifact: {canonical_reference}")),
    )
