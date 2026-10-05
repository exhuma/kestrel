"""The HTTP API boundary for documents (constitution Principle VI).

The frontend renders Markdown; documents leave the API as Markdown, so
response shapes and the frontend's type contract stay unchanged.
"""
from __future__ import annotations

from app.document_formats.markdown import render_markdown
from app.documents import Document

#: How a document artifact is described to the frontend.
MARKDOWN_MIME = "text/markdown"


def api_markdown(value: Document | None) -> str:
    """A document as the API returns it ("" for none)."""
    return render_markdown(value) if value is not None else ""
