"""The agent boundary for documents (constitution Principle VI).

Agents read and write Markdown. This is the one place board code turns a
document into prompt text and an agent's Markdown into a document; every
other board module works with :class:`~app.documents.Document` only.
"""
from __future__ import annotations

from app.document_formats.markdown import parse_markdown, render_markdown
from app.documents import Document


def to_prompt(value: Document) -> str:
    """A document as an agent reads it."""
    return render_markdown(value)


def from_agent(text: str) -> Document:
    """Agent-authored Markdown as a document, when its result is accepted."""
    return parse_markdown(text)
