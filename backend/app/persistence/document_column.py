"""A database column holding a :class:`~app.documents.Document`.

Persistence is a system boundary (constitution Principle VI): documents
are stored as document JSON.
"""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.document_formats.document_json import dump_document, load_document
from app.documents import Document

#: The media type of an artifact that holds a document (feature 046).
DOCUMENT_MIME = "application/vnd.kestrel.document+json"


def encode_document(value: Document) -> str:
    """A document as stored: document JSON text."""
    return dump_document(value)


def decode_document(text: str) -> Document:
    """A stored document back from its document JSON text."""
    return load_document(text)


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
        """Read JSON text back into a document."""
        return None if value is None else decode_document(value)
