"""Durable artifact content-store tests (feature 026, T037).

A handoff artifact's body is content-addressed and immutable: writing the
same content twice is idempotent, writing different content never
overwrites an existing hash's path, and content survives independent of
any particular workflow's snapshot (FR-013, FR-014).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
    ContentNotFoundError,
)

_SHA256_HEX_LENGTH = 64


def _store(tmp_path: Path) -> BoardArtifactContentStore:
    return BoardArtifactContentStore(tmp_path / "artifacts")


class TestWriteAndRead:
    """Content round-trips through its content-addressed reference."""

    def test_written_content_can_be_read_back(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        ref, content_hash = store.write("hello world")
        assert store.read(ref) == "hello world"
        assert len(content_hash) == _SHA256_HEX_LENGTH

    def test_the_ref_encodes_the_content_hash(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        ref, content_hash = store.write("hello world")
        assert content_hash in ref

    def test_reading_an_unknown_ref_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(ContentNotFoundError):
            store.read("does-not-exist")


class TestContentAddressing:
    """Identical content shares storage; different content never collides."""

    def test_writing_identical_content_twice_is_idempotent(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        first_ref, first_hash = store.write("same content")
        second_ref, second_hash = store.write("same content")
        assert first_ref == second_ref
        assert first_hash == second_hash

    def test_different_content_gets_different_refs(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        ref_a, _hash_a = store.write("content A")
        ref_b, _hash_b = store.write("content B")
        assert ref_a != ref_b
        assert store.read(ref_a) == "content A"
        assert store.read(ref_b) == "content B"

    def test_root_directory_is_created_on_first_write(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "nested" / "artifacts"
        store = BoardArtifactContentStore(root)
        store.write("hello")
        assert root.exists()
