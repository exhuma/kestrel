"""Small document builders shared by the tests (feature 046)."""
from __future__ import annotations

from app.documents import Document, Text, document, paragraph


def doc(text: str) -> Document:
    """A one-paragraph document holding *text*."""
    return document(paragraph(Text(text)))
