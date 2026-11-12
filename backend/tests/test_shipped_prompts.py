"""The rules the shipped coder and verifier prompts must keep, so an edit
cannot drop one silently. The model ignored a softer wording once: it
scripted a browser although a browser tool was there."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.board.specialists import load_roster

_SHIPPED = Path(__file__).parents[1] / "specialists"


def _prompt(role: str) -> str:
    return " ".join(load_roster(str(_SHIPPED)).get(role).prompt.split())


@pytest.mark.parametrize("rule", [
    "Using the browser tool is part of the task, not an option.",
    "navigate action",
    "screenshot action",
    "Never, not even in `.kestrel/scratch/`, install a browser library",
    "with the tool's name and the exact error message, and nothing else",
    "no suggestion about what kestrel should provide",
    "<CHANGE_SUMMARY>",
])
def test_the_coder_must_use_the_browser_tool(rule: str) -> None:
    """Ensure the coder is told to use the tool, how, and what not to do."""
    assert rule in _prompt("coder")


@pytest.mark.parametrize("rule", [
    "Open the running app with your browser tool",
    "is a `verification_gap` whenever your browser tool can open the app",
    "whether committed or left behind in the working tree",
])
def test_the_verifier_checks_with_the_browser_tool(rule: str) -> None:
    """Ensure missing screenshots and browser scripts become findings."""
    assert rule in _prompt("verifier")


@pytest.mark.parametrize("rule", [
    "in plain language a non-technical reporter can check",
    "no technical analysis",
    "Ask at most three questions",
    "\"I don't know\" is a fine answer",
    "never ask it again",
])
def test_the_understanding_stays_light(rule: str) -> None:
    """Ensure the first step stays short and non-technical."""
    assert rule in _prompt("pm")
