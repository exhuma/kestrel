"""Tests for the isolated OpenAI-compatible translation backing service."""
from __future__ import annotations

import json
from typing import Callable

import httpx
import pytest

from app.config import Settings
from app.config_models import TranslationConfig
from app.services.translation.openai_compat import OpenAICompatTranslator


def _translator(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAICompatTranslator:
    """Build a translator backed by an injectable HTTP transport."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = TranslationConfig(
        base_url="http://translation.local/v1", model="translator"
    )
    return OpenAICompatTranslator(config, client)


def test_translation_config_is_file_only_and_separate_from_backends(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Translation config uses its own TOML section and env-backed secret."""
    monkeypatch.setenv("TRANSLATION_KEY", "from-env")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[translation]\n"
        'base_url = "http://translator.local/v1"\n'
        'model = "translate"\n'
        'api_key_env = "TRANSLATION_KEY"\n'
    )

    settings = Settings(_env_file=None, config_file=str(config_file))

    assert settings.translation is not None
    assert settings.translation.secret() == "from-env"
    assert [backend.id for backend in settings.backends] == ["claude"]


@pytest.mark.asyncio
async def test_translate_posts_stateless_tagged_prompt() -> None:
    """The endpoint receives source text and returns only its translation."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Capture the request and return a valid tagged translation."""
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "<TRANSLATION>Hello</TRANSLATION>"}}
                ]
            },
        )

    result = await _translator(handler).translate("Hola")

    assert result == "Hello"
    assert captured[0]["model"] == "translator"
    assert captured[0]["messages"][0]["content"].endswith("TEXT:\nHola")


@pytest.mark.asyncio
async def test_translate_returns_original_for_english() -> None:
    """The marker for English input prevents an unnecessary source reply."""
    def handler(_request: httpx.Request) -> httpx.Response:
        """Return the explicit no-translation marker."""
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "<ORIGINAL>"}}]}
        )

    result = await _translator(handler).translate("Already English")

    assert result == "Already English"
