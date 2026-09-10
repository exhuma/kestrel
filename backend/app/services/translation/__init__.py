"""Translation service contracts and composition root."""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.config import get_settings
from app.services.translation.router import TranslationRouter


class Translator(Protocol):
    """Converts text to English, returning the input unchanged when English."""

    async def translate(self, text: str) -> str:
        """Return English, or exactly ``text`` when it is already English."""
        ...


@lru_cache
def get_translator() -> Translator | None:
    """Return the configured translator, or ``None`` when translation is off."""
    return TranslationRouter(get_settings()).translator()
