"""The body of the change request delivery opens (feature 043).

For UI work the coder commits screenshots of the changed screens under
:data:`SCREENSHOTS_DIR`, or a ``README.md`` there saying why it could
not (``specialists/coder/prompt.md``). The body shows each screenshot as
an image served by the code host from the pushed branch, or states the
reason — so the operator reviews UI work without opening the branch.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.services.board.workspace import WorkspaceService

#: Where the coder commits screenshots on the workflow's branch.
SCREENSHOTS_DIR = ".kestrel/screenshots"

_README = f"{SCREENSHOTS_DIR}/README.md"

#: The README is agent output going into a public-facing body: keep
#: only a short reason.
_MAX_NOTE = 1000


@dataclass(frozen=True)
class Screenshots:
    """What the branch carries under :data:`SCREENSHOTS_DIR`.

    :param images: The committed PNG paths, sorted.
    :param note: The README's reason, when there is one.
    """

    images: tuple[str, ...] = ()
    note: str | None = None


async def read_screenshots(
    workspace: WorkspaceService, workflow_id: str
) -> Screenshots:
    """Read the screenshots committed on *workflow_id*'s branch."""
    files = await workspace.committed_files(workflow_id, SCREENSHOTS_DIR)
    images = tuple(sorted(f for f in files if f.lower().endswith(".png")))
    note = None
    if _README in files:
        text = await workspace.committed_text(workflow_id, _README)
        note = (text or "").strip()[:_MAX_NOTE] or None
    return Screenshots(images=images, note=note)


def _screenshots_section(
    screenshots: Screenshots, file_url: Callable[[str], str]
) -> str | None:
    if screenshots.images:
        lines = [
            f"![{PurePosixPath(path).stem}]({file_url(path)})"
            for path in screenshots.images
        ]
        return "## Screenshots\n\n" + "\n\n".join(lines)
    if screenshots.note:
        return f"## Screenshots\n\nNo screenshots: {screenshots.note}"
    return None


def pr_body(
    task_ref: str,
    screenshots: Screenshots,
    file_url: Callable[[str], str],
) -> str:
    """Compose the change request's body.

    :param file_url: Maps a committed path to the URL the code host
        serves it at on the pushed branch.
    """
    parts = [f"Implements {task_ref}"]
    section = _screenshots_section(screenshots, file_url)
    if section:
        parts.append(section)
    parts.append("Opened by kestrel.")
    return "\n\n".join(parts)
