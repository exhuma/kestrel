"""Documents leave the HTTP API as Markdown (feature 046, Principle VI)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.document_formats.document_json import dump_document
from app.documents import Heading, Strong, Text, document, paragraph
from tests.test_board_router_views import _client, _record_artifact


@pytest.mark.asyncio
async def test_a_document_artifact_is_served_as_markdown(
    tmp_path: Path,
) -> None:
    """Ensure documents leave the API as Markdown, so the response shape
    and the frontend contract stay as they were (Principle I, feature 046)."""
    client, _store, _claims = _client(tmp_path)
    _record_artifact(
        tmp_path,
        artifact_id="artifact-1",
        content=dump_document(document(
            Heading(2, (Text("PRD"),)), paragraph(Strong("Scope")),
        )),
        trust="agent_output",
        mime_type="application/vnd.kestrel.document+json",
    )
    async with client as c:
        resp = await c.get("/api/board/artifacts/artifact-1/content")
    assert resp.status_code == httpx.codes.OK
    assert resp.json() == {
        "content": "## PRD\n\n**Scope**",
        "trust": "agent_output",
        "mime_type": "text/markdown",
    }
