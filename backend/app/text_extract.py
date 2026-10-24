"""Shared tagged-block extraction for LLM output.

Lives at the top level (like ``policy.py``/``config.py``) rather than
under either the fixed driver or the board domain, since both depend on
it and it has no dependency of its own on either.
"""
from __future__ import annotations

import re


def extract_tag(text: str, tag: str) -> str | None:
    """Return the trimmed content of a ``<tag>...</tag>`` block, or None.

    Tries an exact match first; on failure, falls back to a case-
    insensitive prefix match (minimum 6 chars) to tolerate minor LLM
    typos in the tag name (e.g. ``<UNDERSTING>`` for ``<UNDERSTANDING>``).
    """
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fuzzy fallback: match a tag whose name starts with at least the
    # first 6 characters of the expected tag (case-insensitive).
    prefix = tag[:6]
    pattern = r"<([A-Z_]{6,})>\s*(.*?)\s*</\1>"
    for m in re.finditer(pattern, text, re.DOTALL):
        if m.group(1).upper().startswith(prefix):
            return m.group(2).strip()
    return None
