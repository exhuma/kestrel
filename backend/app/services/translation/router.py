"""Configuration router for the dedicated translation backing service."""
from __future__ import annotations

from app.config import Settings
from app.services.translation.openai_compat import OpenAICompatTranslator


class TranslationRouter:
    """Builds translation clients separately from workflow backend routing."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def translator(self) -> OpenAICompatTranslator | None:
        """Return the configured OpenAI-compatible translator, or ``None``."""
        config = self._settings.translation
        return OpenAICompatTranslator(config) if config else None
