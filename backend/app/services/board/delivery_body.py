"""Kestrel's section of the change request's description (feature 043).

For UI work the coder commits screenshots of the changed screens under
:data:`SCREENSHOTS_DIR`, or a ``README.md`` there saying why it could
not (``specialists/coder/prompt.md``). The section shows each screenshot
as an image served by the code host from the pushed branch, or states
the reason, so the operator reviews UI work without opening the branch.
It also lists the rounds of work after the change request was opened.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.documents import (
    Block,
    BulletList,
    Document,
    Heading,
    Image,
    ListItem,
    Text,
    document,
    paragraph,
)
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
) -> list[Block]:
    heading = Heading(3, (Text("Screenshots"),))
    if screenshots.images:
        return [heading, *(
            Image(file_url(path), PurePosixPath(path).stem)
            for path in screenshots.images
        )]
    if screenshots.note:
        return [heading,
                paragraph(Text(f"No screenshots: {screenshots.note}"))]
    return []


#: The first and last lines of kestrel's section of the description:
#: visible, so people know what kestrel rewrites (``splice_section``).
SECTION_HEADING = "Maintained by kestrel"
SECTION_END = "End of the section kestrel maintains."


def kestrel_section(
    task_ref: str,
    rounds: tuple[str, ...],
    screenshots: Screenshots,
    file_url: Callable[[str], str],
) -> Document:
    """Kestrel's section of the change request's description: what it
    implements, each later round, and the committed screenshots. Kestrel
    rewrites it on every delivery; the rest of the description is left
    as people wrote it.

    :param file_url: Maps a committed path to the URL the code host
        serves it at on the pushed branch.
    """
    blocks: list[Block] = [
        Heading(2, (Text(SECTION_HEADING),)),
        paragraph(Text(
            "kestrel keeps this section up to date on every delivery and "
            "replaces edits made inside it."
        )),
        paragraph(Text(f"Implements {task_ref}.")),
    ]
    if rounds:
        blocks += [
            Heading(3, (Text("Later rounds"),)),
            BulletList(tuple(
                ListItem((paragraph(Text(line)),)) for line in rounds
            )),
        ]
    blocks += _screenshots_section(screenshots, file_url)
    blocks.append(paragraph(Text(SECTION_END)))
    return document(*blocks)
