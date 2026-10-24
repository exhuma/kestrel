"""Stateless OpenAI-compatible translation client."""
from __future__ import annotations

import json

import httpx

from app.config_models import TranslationConfig

_PROMPT = (
    "Translate this text to English. If it is already English, respond with "
    "exactly <ORIGINAL>. Otherwise respond only with the English translation "
    "inside <TRANSLATION> and </TRANSLATION> tags.\n\nTEXT:\n"
)


class OpenAICompatTranslator:
    """Translates one text at a time without workflow-session state."""

    def __init__(
        self, config: TranslationConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model
        self._api_key = config.secret()
        self._timeout = config.timeout
        self._client = client

    async def translate(self, text: str) -> str:
        """Return English, preserving ``text`` when the model marks it so."""
        headers = self._headers()
        payload = self._payload(text)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return self._translation(text, response.json())
        finally:
            if self._client is None:
                await client.aclose()

    def _headers(self) -> dict[str, str]:
        """Return the optional bearer authentication header."""
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    def _payload(self, text: str) -> dict[str, object]:
        """Build the non-streaming chat-completions request body."""
        return {
            "model": self._model,
            "messages": [{"role": "user", "content": _PROMPT + text}],
        }

    def _translation(self, original: str, data: object) -> str:
        """Validate tagged model output and return its translated content."""
        content = _content_of(data).strip()
        if content == "<ORIGINAL>":
            return original
        if content.startswith("<TRANSLATION>") and content.endswith(
            "</TRANSLATION>"
        ):
            translation = content[13:-14].strip()
            if translation:
                return translation
        raise RuntimeError("translation endpoint returned an invalid response")


def _content_of(data: object) -> str:
    """Extract assistant content from an OpenAI-compatible response object."""
    try:
        return data["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        excerpt = json.dumps(data)[:200]
        raise RuntimeError(
            f"unexpected translation response: {excerpt}"
        ) from exc
