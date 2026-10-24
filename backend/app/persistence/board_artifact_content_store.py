"""Durable, content-addressed handoff-artifact bodies (feature 026, FR-013).

Content lives on disk under its own sha256 hash, sharded two levels deep
(the same layout convention as git's object store) so the directory
never grows unbounded flat. Identity by hash makes every write
idempotent and immutable by construction: two different contents can
never collide on one path, and rewriting the same content is a no-op.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

_REF_PREFIX = "board-artifact://"


class ContentNotFoundError(Exception):
    """Raised when a content ref does not resolve to stored content."""


class BoardArtifactContentStore:
    """File-backed, content-addressed store for artifact bodies."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def write(self, content: str) -> tuple[str, str]:
        """Durably store *content*; returns ``(content_ref, content_hash)``."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = self._path_for(content_hash)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return f"{_REF_PREFIX}{content_hash}", content_hash

    def read(self, content_ref: str) -> str:
        """Return the content stored under *content_ref*.

        :raises ContentNotFoundError: If the ref is malformed or its
            content is missing.
        """
        if not content_ref.startswith(_REF_PREFIX):
            raise ContentNotFoundError(
                f"not a board-artifact ref: {content_ref}"
            )
        content_hash = content_ref.removeprefix(_REF_PREFIX)
        path = self._path_for(content_hash)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ContentNotFoundError(
                f"no content for ref: {content_ref}"
            ) from exc

    def _path_for(self, content_hash: str) -> Path:
        return self._root / content_hash[:2] / content_hash


@lru_cache
def get_board_artifact_content_store() -> BoardArtifactContentStore:
    """Return the process-wide BoardArtifactContentStore singleton."""
    return BoardArtifactContentStore(get_settings().board_artifacts_root)
