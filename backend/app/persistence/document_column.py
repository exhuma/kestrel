"""A database column holding a :class:`~app.documents.Document`.

Persistence is a system boundary (constitution Principle VI): documents
are stored as document JSON. A value written before feature 046 is the
Markdown that was stored then; it is parsed when read, so no row needs
migrating.
"""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.document_formats.document_json import dump_document, load_document
from app.document_formats.markdown import parse_markdown
from app.documents import Document

#: The media type of an artifact that holds a document (feature 046).
DOCUMENT_MIME = "application/vnd.kestrel.document+json"
#: Artifacts stored before feature 046 held their documents as Markdown.
_LEGACY_MARKDOWN_MIME = "text/markdown"


def encode_document(value: Document) -> str:
    """A document as stored: document JSON text."""
    return dump_document(value)


def decode_document(text: str, mime_type: str = DOCUMENT_MIME) -> Document:
    """A stored document back, legacy Markdown included.

    Content stored as document JSON is loaded; anything else (a Markdown
    artifact written before feature 046) is parsed as Markdown.
    """
    if mime_type != _LEGACY_MARKDOWN_MIME:
        try:
            return load_document(text)
        except ValueError:
            pass
    return parse_markdown(text)


class DocumentText(TypeDecorator[Document]):
    """``Document`` in Python, document JSON in a ``TEXT`` column."""

    impl = Text
    cache_ok = True

    def process_bind_param(
        self, value: Document | None, _dialect: Dialect
    ) -> str | None:
        """Store a document as JSON text."""
        return None if value is None else dump_document(value)

    def process_result_value(
        self, value: str | None, _dialect: Dialect
    ) -> Document | None:
        """Read JSON text back; a legacy Markdown value is parsed."""
        return None if value is None else decode_document(value)
